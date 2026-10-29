"""Decoding Seaport's OrderFulfilled out of a transaction receipt, and naming the sale."""

from dataclasses import dataclass
from typing import Any

from app.chain.abi import address
from app.chain.abi import words as abi_words
from app.core.logging import get_logger
from app.core.store import MarketplaceMark, MarkKind
from app.nft.models import ZERO_ADDRESS
from app.shared.exceptions import AeonForgeBotError

logger = get_logger(__name__)

SEAPORT_1_6 = "0x0000000000000068f116a894984e2db1123eb395"
SEAPORT_1_5 = "0x00000000000000adc04c56bf30ac9d3c0aaf14dc"
ORDER_FULFILLED_TOPIC = "0x9d9af8e38d66c62e2c12f0225249fd9d721c54b83f48d9352c97c6cacdcb6f31"

UNMARKED_SEAPORT_SALE = "Other marketplace (Seaport)"

# Seaport ItemType values
NATIVE, ERC20, ERC721, ERC1155 = 0, 1, 2, 3
NFT_ITEM_TYPES = (ERC721, ERC1155)

TAG_HEX_CHARS = 8  # a calldata tag is 4 bytes


class SeaportError(AeonForgeBotError):
    """Raised when an OrderFulfilled event does not have the shape the bot can price."""


@dataclass(frozen=True)
class SeaportItem:
    """One offer or consideration item; recipient is set on consideration items only."""

    item_type: int
    token: str
    identifier: int
    amount: int
    recipient: str | None


@dataclass(frozen=True)
class SeaportSale:
    """One tracked token sold through a Seaport order; the currency is an address (zero is ETH)."""

    asset_contract: str
    token_id: int
    seller: str
    buyer: str
    total_price: int
    currency: str
    zone: str
    fee_recipients: tuple[str, ...]


def _items(data: list[int], offset_word: int, size: int, with_recipient: bool) -> list[SeaportItem]:
    start = data[offset_word] // 32
    count = data[start]
    items = []
    for i in range(count):
        item = data[start + 1 + i * size : start + 1 + (i + 1) * size]
        items.append(
            SeaportItem(
                item_type=item[0],
                token=address(item[1]),
                identifier=item[2],
                amount=item[3],
                recipient=address(item[4]) if with_recipient else None,
            )
        )
    return items


def _payment(items: list[SeaportItem]) -> tuple[int, str]:
    """The summed amount and coin of the payment items; they must all be one coin."""
    coins = {item.token if item.item_type == ERC20 else ZERO_ADDRESS for item in items}
    if len(coins) != 1:
        raise SeaportError(
            f"Seaport order pays in {len(coins)} coins, expected one: {sorted(coins)}"
        )
    return sum(item.amount for item in items), coins.pop()


def seaport_sales(receipt_logs: list[dict[str, Any]]) -> list[SeaportSale]:
    """The tracked-token sales among a receipt's logs: one per NFT item of each fulfilled order.

    A listing fill has the NFT in the offer and the payment in the consideration (fees and
    royalties included); an offer fill has the payment in the offer and the NFT in the
    consideration, with the fee items already part of the offered amount.
    """
    sales: list[SeaportSale] = []
    for log in receipt_logs:
        topics = log["topics"]
        if log["address"].lower() not in (SEAPORT_1_6, SEAPORT_1_5) or (
            topics[0] != ORDER_FULFILLED_TOPIC
        ):
            continue
        data = abi_words(log["data"])
        offerer, zone = address(int(topics[1], 16)), address(int(topics[2], 16))
        recipient = address(data[1])
        offer = _items(data, 2, 4, with_recipient=False)
        consideration = _items(data, 3, 5, with_recipient=True)
        if any(item.item_type in NFT_ITEM_TYPES for item in offer):
            nfts = [item for item in offer if item.item_type in NFT_ITEM_TYPES]
            payments = [item for item in consideration if item.item_type not in NFT_ITEM_TYPES]
            seller, buyer = offerer, recipient
        else:
            nfts = [item for item in consideration if item.item_type in NFT_ITEM_TYPES]
            payments = offer
            seller, buyer = recipient, offerer
        try:
            total_price, currency = _payment(payments)
        except SeaportError as error:
            logger.warning("skipping an unpriceable Seaport order: %s", error)
            continue
        fee_recipients = tuple(
            item.recipient
            for item in consideration
            if item.recipient and item.item_type not in NFT_ITEM_TYPES
        )
        sales.extend(
            SeaportSale(
                nft.token,
                nft.identifier,
                seller,
                buyer,
                total_price,
                currency,
                zone,
                fee_recipients,
            )
            for nft in nfts
        )
    return sales


def name_seaport_sale(sale: SeaportSale, tx_input: str, marks: tuple[MarketplaceMark, ...]) -> str:
    """The marketplace that made the sale: the first mark hit, else the unmarked name.

    Order: the transaction input's last 4 bytes (the submitting site), the 4 bytes before
    (aggregator-routed fills append two tags), the order's zone, then any fee wallet paid.
    """
    names = {(mark.kind, mark.value): mark.marketplace for mark in marks}
    body = tx_input.removeprefix("0x")
    candidates: list[tuple[MarkKind, str]] = [("calldata_tag", "0x" + body[-TAG_HEX_CHARS:])]
    if len(body) >= 2 * TAG_HEX_CHARS:
        candidates.append(("calldata_tag", "0x" + body[-2 * TAG_HEX_CHARS : -TAG_HEX_CHARS]))
    candidates.append(("zone", sale.zone))
    candidates.extend(("fee_wallet", wallet) for wallet in sale.fee_recipients)
    for candidate in candidates:
        if candidate in names:
            return names[candidate]
    return UNMARKED_SEAPORT_SALE
