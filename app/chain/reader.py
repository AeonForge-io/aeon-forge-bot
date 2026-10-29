"""The chain reader: one per chain, turning ERC-721 mints into stored, posted events.

The websocket subscription tells the reader that a block holds tracked Transfer logs; the
logs themselves are read with eth_getLogs, the same way catch-up reads them. So a live block
and a replayed block take one path, and the cursor moves only after a block's mints are stored.
"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypeVar

from app.chain.abi import TRANSFER_TOPIC
from app.chain.element import element_sales
from app.chain.forum_one import DecodedSale, forum_one_sales
from app.chain.other_marketplace import Payment, erc20_payment, trace_payment
from app.chain.rarible import rarible_sale
from app.chain.rpc import (
    Block,
    ChainConnectionError,
    ChainRpc,
    RpcResponseError,
    SubscriptionError,
    hex_to_int,
)
from app.chain.seaport import SeaportSale, name_seaport_sale, seaport_sales
from app.core.logging import get_logger
from app.core.settings_reload import SettingsReloader
from app.core.store import Collection, PostStatus, Store
from app.discord.event_publisher import EventPublisher
from app.marketplace.forum_one import FORUM_ONE_CHAIN_IDS
from app.marketplace.forum_one import MARKETPLACE as FORUM_ONE_MARKETPLACE
from app.nft.metadata import token_image_url
from app.nft.models import (
    ZERO_ADDRESS,
    NFTBurnEvent,
    NFTMintEvent,
    NFTSaleEvent,
    NFTTransferEvent,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class _FoundSale:
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
TOTAL_SUPPLY_SELECTOR = "0x18160ddd"
MAX_SUPPLY_SELECTOR = "0xd5abeb01"

CATCH_UP_WINDOW_SECONDS = 6 * 60 * 60
# Alchemy pay-as-you-go (the plan in the spec) takes wide eth_getLogs ranges; 2000 blocks is a
# conservative slice. The free tier allows only 10 blocks per call and would need 10 here.
LOG_RANGE_BLOCKS = 2000
WEI_PER_ETH = Decimal(10**18)

BACKOFF_START_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 60.0

# Chains that poll eth_getLogs when the websocket refuses the logs subscription
POLLING_FALLBACK_CHAINS = frozenset({"base-sepolia"})
POLL_INTERVAL_SECONDS = 30.0


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


class ChainReader:
    """Reads one chain's tracked contracts and posts their mints, burns and transfers."""

    def __init__(
        self,
        chain: str,
        rpc: ChainRpc,
        store: Store,
        reloader: SettingsReloader,
        publisher: EventPublisher,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.chain = chain
        self.rpc = rpc
        self.store = store
        self.reloader = reloader
        self.publisher = publisher
        self.sleep = sleep
        self.contracts = reloader.current.tracked_contracts.get(chain, frozenset())
        self._next_contracts: frozenset[str] | None = None
        self._contracts_changed = asyncio.Event()

    def replace_contracts(self, contracts: frozenset[str]) -> None:
        """Track a new contract set; the subscription is replaced at the next safe point."""
        self._next_contracts = contracts
        self._contracts_changed.set()

    # ---- Running ----

    async def run(self) -> None:
        """Read the chain forever: reconnect with backoff, poll if websocket logs fail."""
        delay = BACKOFF_START_SECONDS
        polling = False
        while True:
            try:
                if polling:
                    await self._poll_forever()
                else:
                    await self.connect_once()
                delay = BACKOFF_START_SECONDS
            except SubscriptionError as e:
                if self.chain not in POLLING_FALLBACK_CHAINS:
                    raise
                logger.warning("chain.subscription.refused", chain=self.chain, error=str(e))
                polling = True
                continue
            except ChainConnectionError as e:
                logger.warning("chain.connection.lost", chain=self.chain, error=str(e))
                delay = min(delay * 2, BACKOFF_MAX_SECONDS)
            if not self._contracts_changed.is_set():
                await self.sleep(delay)

    async def connect_once(self) -> None:
        """Catch up, then follow the subscription until it ends or the contract set changes."""
        await self._adopt_new_contracts()
        await self.sync_to(await self.rpc.block())
        if not self.contracts:
            # An empty address filter matches every contract, so wait for a tracked one instead
            await self._contracts_changed.wait()
            return
        live = asyncio.ensure_future(self._follow_subscription())
        changed = asyncio.ensure_future(self._contracts_changed.wait())
        try:
            await asyncio.wait({live, changed}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            live.cancel()
            changed.cancel()
            await asyncio.gather(live, changed, return_exceptions=True)
        if live.done() and not live.cancelled():
            live.result()

    async def _follow_subscription(self) -> None:
        log_filter = {"address": sorted(self.contracts), "topics": [TRANSFER_TOPIC]}
        async for log in self.rpc.transport.subscribe_logs(log_filter):
            if log.get("removed"):
                logger.info("chain.log.removed", chain=self.chain, tx=log["transactionHash"])
                continue
            await self.sync_to(await self.rpc.block(hex_to_int(log["blockNumber"])))

    async def _poll_forever(self) -> None:
        while True:
            await self._adopt_new_contracts()
            await self.sync_to(await self.rpc.block())
            await self.sleep(POLL_INTERVAL_SECONDS)

    async def _adopt_new_contracts(self) -> None:
        """Switch to the new contract set, after reading what the old set owes up to the head.

        A collection added later is therefore tracked from the current block onward.
        """
        if self._next_contracts is None:
            return
        await self.sync_to(await self.rpc.block())
        self.contracts = self._next_contracts
        self._next_contracts = None
        self._contracts_changed.clear()

    # ---- Catch-up and cursor ----

    async def sync_to(self, head: Block) -> None:
        """Store and post the events between the cursor and the head, then move the cursor."""
        cursor = await self.store.get_cursor(self.chain)
        if cursor is None:
            await self._save_cursor(head)
            logger.info("chain.cursor.started", chain=self.chain, block=head.number)
            return
        if head.number <= cursor.last_block:
            return
        start = cursor.last_block + 1
        cutoff = head.timestamp - CATCH_UP_WINDOW_SECONDS
        if cursor.last_block_time is None or cursor.last_block_time.timestamp() < cutoff:
            start = await self._first_block_since(cutoff, start, head.number)
            logger.warning(
                "chain.catchup.gap_skipped",
                chain=self.chain,
                cursor_block=cursor.last_block,
                resumed_at=start,
            )
        if not self.contracts:
            await self._save_cursor(head)
            return
        for low in range(start, head.number + 1, LOG_RANGE_BLOCKS):
            high = min(low + LOG_RANGE_BLOCKS - 1, head.number)
            logs = await self.rpc.logs(low, high, sorted(self.contracts), [TRANSFER_TOPIC])
            by_block: dict[int, list[dict[str, Any]]] = defaultdict(list)
            for log in logs:
                if log.get("removed"):
                    continue
                by_block[hex_to_int(log["blockNumber"])].append(log)
            for number in sorted(by_block):
                block = await self.rpc.block(number)
                await self._store_block_events(block, by_block[number])
                await self._save_cursor(block)
        await self._save_cursor(head)

    async def _first_block_since(self, cutoff: int, low: int, high: int) -> int:
        """The first block in [low, high] whose time is at or after the cutoff."""
        while low < high:
            middle = (low + high) // 2
            if (await self.rpc.block(middle)).timestamp >= cutoff:
                high = middle
            else:
                low = middle + 1
        return low

    async def _save_cursor(self, block: Block) -> None:
        await self.store.set_cursor(
            self.chain, block.number, datetime.fromtimestamp(block.timestamp, UTC)
        )

    # ---- Events ----

    async def _store_block_events(self, block: Block, logs: list[dict[str, Any]]) -> None:
        by_contract: dict[str, list[TransferLog]] = defaultdict(list)
        for transfer in transfer_logs(logs):
            by_contract[transfer.contract].append(transfer)
        # A receipt is fetched once per transaction, however many tracked tokens it moved
        receipts: dict[str, list[dict[str, Any]]] = {}
        for contract, transfers in by_contract.items():
            collection = self._collection(contract)
            if collection is None:
                continue
            mints = [t for t in transfers if t.sender == ZERO_ADDRESS]
            if mints:
                await self._store_contract_mints(block, collection, mints)
            for transfer in transfers:
                if transfer.recipient == ZERO_ADDRESS:
                    await self._store_burn(block, collection, transfer)
                elif transfer.sender != ZERO_ADDRESS:
                    await self._store_transfer(block, collection, transfer, receipts)

    async def _store_burn(self, block: Block, collection: Collection, burn: TransferLog) -> None:
        event = NFTBurnEvent(
            collection_id=collection.id,
            token_id=str(burn.token_id),
            from_address=burn.sender,
            chain=self.chain,
            token_image_url=token_image_url(collection, str(burn.token_id)),
            transaction_hash=burn.tx_hash,
            block_number=block.number,
            event_timestamp=datetime.fromtimestamp(block.timestamp, UTC),
        )
        status = PostStatus.PENDING if collection.post_burns else PostStatus.SKIPPED
        event_id = await self.store.insert_burn(event, status)
        if event_id is not None and status is PostStatus.PENDING:
            await self.publisher.post_burn(collection, event_id, event)

    async def _store_transfer(
        self,
        block: Block,
        collection: Collection,
        transfer: TransferLog,
        receipts: dict[str, list[dict[str, Any]]],
    ) -> None:
        """Record a transfer; the mode decides whether it is posted or kept as skipped.

        A transfer that is part of a sale is kept as skipped: the sale is what gets posted.
        """
        found = await self._find_sale(block, collection, transfer, receipts)
        if found is not None:
            await self._store_sale(block, collection, transfer, found)
        is_company = self.reloader.current.company_label(transfer.sender) is not None
        posts = found is None and (
            collection.transfer_mode == "all"
            or (collection.transfer_mode == "company" and is_company)
        )
        status = PostStatus.PENDING if posts else PostStatus.SKIPPED
        event = NFTTransferEvent(
            collection_id=collection.id,
            token_id=str(transfer.token_id),
            from_address=transfer.sender,
            to_address=transfer.recipient,
            chain=self.chain,
            token_image_url=token_image_url(collection, str(transfer.token_id)),
            transaction_hash=transfer.tx_hash,
            block_number=block.number,
            event_timestamp=datetime.fromtimestamp(block.timestamp, UTC),
        )
        event_id = await self.store.insert_transfer(event, status)
        if event_id is not None and status is PostStatus.PENDING:
            await self.publisher.post_transfer(collection, event_id, event)

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
    ) -> _FoundSale | None:
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
    ) -> _FoundSale | None:
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
            symbol, decimals = coin.symbol, coin.decimals
        return _FoundSale(sale, marketplace, seller_received, symbol, decimals)

    async def _store_sale(
        self,
        block: Block,
        collection: Collection,
        transfer: TransferLog,
        found: _FoundSale,
    ) -> None:
        sale, marketplace, seller_received = found.sale, found.marketplace, found.seller_received
        symbol, decimals = found.symbol, found.decimals
        event = NFTSaleEvent(
            collection_id=collection.id,
            token_id=str(transfer.token_id),
            token_image_url=token_image_url(collection, str(transfer.token_id)),
            seller_address=sale.seller,
            buyer_address=sale.buyer,
            marketplace=marketplace,
            price_native=Decimal(sale.total_price) / Decimal(10) ** decimals,
            currency=symbol,
            seller_received=seller_received,
            sale_id=f"{transfer.tx_hash}:{transfer.token_id}",
            transaction_hash=transfer.tx_hash,
            event_timestamp=datetime.fromtimestamp(block.timestamp, UTC),
        )
        status = PostStatus.PENDING if collection.post_sales else PostStatus.SKIPPED
        event_id = await self.store.insert_sale(event, status)
        if event_id is not None and status is PostStatus.PENDING:
            await self.publisher.post_sale(collection, event_id, event)

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

    async def _store_contract_mints(
        self, block: Block, collection: Collection, mints: list[TransferLog]
    ) -> None:
        """Record a contract's mints in one block and post the new ones."""
        supply = await self.rpc.call_uint(
            collection.contract_address, TOTAL_SUPPLY_SELECTOR, block.number
        )
        max_supply = await self.rpc.call_uint(
            collection.contract_address, MAX_SUPPLY_SELECTOR, block.number
        )
        minted_per_tx: dict[str, int] = defaultdict(int)
        for mint in mints:
            minted_per_tx[mint.tx_hash] += 1
        price_per_token: dict[str, Decimal | None] = {}
        for tx_hash, count in minted_per_tx.items():
            value = Decimal((await self.rpc.transaction(tx_hash)).value_wei) / WEI_PER_ETH
            price_per_token[tx_hash] = value / count if value > 0 else None

        status = PostStatus.PENDING if collection.post_mints else PostStatus.SKIPPED
        new_mints: list[tuple[int, NFTMintEvent]] = []
        for position, mint in enumerate(mints):
            later_mints = len(mints) - 1 - position
            event = NFTMintEvent(
                collection_id=collection.id,
                token_id=str(mint.token_id),
                to_address=mint.recipient,
                chain=self.chain,
                token_image_url=token_image_url(collection, str(mint.token_id)),
                price_native=price_per_token[mint.tx_hash],
                progress_number=supply - later_mints,
                max_supply=max_supply,
                transaction_hash=mint.tx_hash,
                block_number=block.number,
                event_timestamp=datetime.fromtimestamp(block.timestamp, UTC),
            )
            event_id = await self.store.insert_mint(event, status)
            if event_id is not None and status is PostStatus.PENDING:
                new_mints.append((event_id, event))
        if new_mints:
            await self.publisher.post_mints(collection, new_mints)
