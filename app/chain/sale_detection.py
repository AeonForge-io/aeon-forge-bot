"""Sale detection for the chain reader: which marketplace a transfer was sold on, and for how much.

Split out of app.chain.reader; ChainReader mixes SaleDetection in and uses TransferLog and FoundSale.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from app.chain.element import element_sales
from app.chain.forum_one import DecodedSale, forum_one_sales
from app.chain.other_marketplace import Payment, erc20_payment, trace_payment
from app.chain.rarible import rarible_sale
from app.chain.rpc import (
    Block,
    ChainConnectionError,
    ChainRpc,
    RpcResponseError,
    hex_to_int,
)
from app.chain.seaport import SeaportSale, name_seaport_sale, seaport_sales
from app.core.logging import get_logger
from app.core.settings_reload import SettingsReloader
from app.core.store import Collection
from app.marketplace.forum_one import FORUM_ONE_CHAIN_IDS
from app.marketplace.forum_one import MARKETPLACE as FORUM_ONE_MARKETPLACE
from app.nft.coin_symbol import coin_label
from app.nft.models import ZERO_ADDRESS

logger = get_logger(__name__)


@dataclass(frozen=True)
class FoundSale:
    """A detected sale with its marketplace name and price coin, ready to store."""

    sale: DecodedSale | SeaportSale
    marketplace: str
    seller_received: bool
    symbol: str
    decimals: int


_SaleT = TypeVar("_SaleT", DecodedSale, SeaportSale)

ELEMENT_MARKETPLACE = "Element"
RARIBLE_MARKETPLACE = "Rarible"
OTHER_MARKETPLACE = "Other marketplace"


class TransferLog:
    """A decoded ERC-721 Transfer."""

    def __init__(self, log: dict[str, Any]) -> None:
        topics = log["topics"]
        self.contract: str = log["address"].lower()
        self.token_id = hex_to_int(topics[3])
        self.sender = "0x" + topics[1][-40:]
        self.recipient = "0x" + topics[2][-40:]
        self.tx_hash: str = log["transactionHash"]
        self.log_index = hex_to_int(log["logIndex"])


def transfer_logs(logs: list[dict[str, Any]]) -> list[TransferLog]:
    """The ERC-721 transfers among the logs (4 topics; ERC-20 Transfers have 3), in log order."""
    return sorted(
        (TransferLog(log) for log in logs if len(log["topics"]) == 4),
        key=lambda transfer: transfer.log_index,
    )


class SaleDetection:
    """Finds the sale a transfer is part of; mixed into ChainReader."""

    chain: str
    rpc: ChainRpc
    reloader: SettingsReloader

    async def _receipt_logs(
        self, transfer: TransferLog, receipts: dict[str, list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        if transfer.tx_hash not in receipts:
            receipts[transfer.tx_hash] = await self.rpc.transaction_logs(transfer.tx_hash)
        return receipts[transfer.tx_hash]

    async def _matching_sale(
        self,
        transfer: TransferLog,
        receipts: dict[str, list[dict[str, Any]]],
        decode: Callable[[list[dict[str, Any]]], list[_SaleT]],
    ) -> _SaleT | None:
        """The decoded sale in the transfer's receipt whose token is the transferred one."""
        return next(
            (
                sale
                for sale in decode(await self._receipt_logs(transfer, receipts))
                if sale.asset_contract == transfer.contract and sale.token_id == transfer.token_id
            ),
            None,
        )

    async def _forum_one_sale(
        self,
        collection: Collection,
        transfer: TransferLog,
        receipts: dict[str, list[dict[str, Any]]],
    ) -> DecodedSale | None:
        if collection.chain not in FORUM_ONE_CHAIN_IDS:
            return None  # the Forum One proxy is Base-only; test contracts are never decoded
        if not collection.track_marketplace or FORUM_ONE_MARKETPLACE not in collection.marketplaces:
            return None
        return await self._matching_sale(transfer, receipts, forum_one_sales)

    async def _element_sale(
        self,
        collection: Collection,
        transfer: TransferLog,
        receipts: dict[str, list[dict[str, Any]]],
    ) -> DecodedSale | None:
        if collection.chain not in FORUM_ONE_CHAIN_IDS or not collection.track_marketplace:
            return None  # ElementEx's address is Base's; test contracts are never decoded
        return await self._matching_sale(transfer, receipts, element_sales)

    async def _rarible_sale(
        self,
        collection: Collection,
        transfer: TransferLog,
        receipts: dict[str, list[dict[str, Any]]],
    ) -> DecodedSale | None:
        if collection.chain not in FORUM_ONE_CHAIN_IDS or not collection.track_marketplace:
            return None  # ExchangeMetaV2's address is Base's; test contracts are never decoded
        return rarible_sale(
            await self._receipt_logs(transfer, receipts),
            transfer.contract,
            transfer.token_id,
            transfer.sender,
            transfer.recipient,
            transfer.log_index,
        )

    async def _seaport_sale(
        self,
        collection: Collection,
        transfer: TransferLog,
        receipts: dict[str, list[dict[str, Any]]],
    ) -> SeaportSale | None:
        if collection.chain not in FORUM_ONE_CHAIN_IDS or not collection.track_marketplace:
            return None  # the Seaport addresses are Base's; test contracts are never decoded
        return await self._matching_sale(transfer, receipts, seaport_sales)

    async def _other_marketplace_payment(
        self,
        collection: Collection,
        transfer: TransferLog,
        receipts: dict[str, list[dict[str, Any]]],
    ) -> Payment | None:
        """Payment to the seller, from the receipt, then the transaction, then a trace."""
        if collection.chain not in FORUM_ONE_CHAIN_IDS or not collection.track_marketplace:
            return None  # test contracts are never decoded
        receipt_logs = await self._receipt_logs(transfer, receipts)
        moved = max(
            1,
            sum(
                1
                for t in transfer_logs(receipt_logs)
                if t.sender == transfer.sender
                and t.recipient == transfer.recipient
                and self._collection(t.contract) is not None
            ),
        )  # a bundle's payment is split across the tracked tokens moved from seller to buyer
        payment = erc20_payment(receipt_logs, transfer.sender, transfer.recipient, moved)
        if payment is not None:
            return payment
        tx = await self.rpc.transaction(transfer.tx_hash)
        if tx.value_wei > 0 and tx.sender == transfer.recipient:
            return Payment(ZERO_ADDRESS, tx.value_wei // moved, seller_received=False)
        if tx.to == transfer.contract:
            return None  # the NFT contract was called directly: a plain transfer
        return trace_payment(
            await self.rpc.call_trace(transfer.tx_hash), transfer.sender, transfer.recipient, moved
        )

    async def _find_sale(
        self,
        block: Block,
        collection: Collection,
        transfer: TransferLog,
        receipts: dict[str, list[dict[str, Any]]],
    ) -> FoundSale | None:
        """Detect the sale a transfer is part of; a failure to decode one means no sale.

        A refused or undecodable call is logged and skipped so one hostile transaction cannot stop
        the chain; a transport failure still propagates so the block is retried.
        """
        try:
            return await self._detect_sale(collection, transfer, receipts)
        except asyncio.CancelledError:
            raise
        except RpcResponseError as e:
            self._log_detection_failure(block, transfer, e)
        except ChainConnectionError:
            raise
        except Exception as e:  # untrusted receipts can break any decoder
            self._log_detection_failure(block, transfer, e)
        return None

    def _log_detection_failure(self, block: Block, transfer: TransferLog, error: Exception) -> None:
        logger.error(
            "chain.sale.detection_failed",
            chain=self.chain,
            block=block.number,
            tx=transfer.tx_hash,
            token_id=transfer.token_id,
            contract=transfer.contract,
            error=f"{type(error).__name__}: {error}",
        )

    async def _detect_sale(
        self,
        collection: Collection,
        transfer: TransferLog,
        receipts: dict[str, list[dict[str, Any]]],
    ) -> FoundSale | None:
        sale: DecodedSale | SeaportSale
        seller_received = False
        if (forum_one := await self._forum_one_sale(collection, transfer, receipts)) is not None:
            sale, marketplace = forum_one, FORUM_ONE_MARKETPLACE
        elif (element := await self._element_sale(collection, transfer, receipts)) is not None:
            sale, marketplace = element, ELEMENT_MARKETPLACE
        elif (rarible := await self._rarible_sale(collection, transfer, receipts)) is not None:
            sale, marketplace = rarible, RARIBLE_MARKETPLACE
        elif (seaport := await self._seaport_sale(collection, transfer, receipts)) is not None:
            sale = seaport
            marketplace = name_seaport_sale(
                seaport,
                (await self.rpc.transaction(transfer.tx_hash)).input,
                self.reloader.current.marketplace_marks,
            )
        elif payment := await self._other_marketplace_payment(collection, transfer, receipts):
            sale = DecodedSale(
                transfer.contract,
                transfer.token_id,
                transfer.sender,
                transfer.recipient,
                payment.total_price,
                payment.currency,
            )
            marketplace, seller_received = OTHER_MARKETPLACE, payment.seller_received
        else:
            return None
        if sale.currency == ZERO_ADDRESS:
            symbol, decimals = "ETH", 18
        else:
            coin = await self.rpc.erc20_coin(sale.currency)
            symbol, decimals = coin_label(sale.currency, coin.symbol), coin.decimals
        return FoundSale(sale, marketplace, seller_received, symbol, decimals)

    def _collection(self, contract: str) -> Collection | None:
        for collection in self.reloader.current.collections:
            if (
                collection.chain == self.chain
                and collection.contract_address == contract
                and collection.is_active
                and collection.track_onchain
            ):
                return collection
        return None
