"""Finding payment for a tracked transfer that no named marketplace decoder recognised."""

from dataclasses import dataclass
from typing import Any

from app.chain.abi import TRANSFER_TOPIC, address
from app.nft.models import ZERO_ADDRESS

ERC20_TRANSFER_TOPIC_COUNT = 3  # an ERC-721 Transfer indexes the token id too, making 4


@dataclass(frozen=True)
class Payment:
    """What was paid for a token; the currency is an address (zero is ETH)."""

    currency: str
    total_price: int
    seller_received: bool


def erc20_payment(receipt_logs: list[dict[str, Any]], seller: str, buyer: str) -> Payment | None:
    """The ERC-20 payment to the seller in a receipt, or None when no ERC-20 reaches the seller.

    The coin is the first token paid to the seller. The price is the buyer's gross outflow of that
    token (fees and royalties included); with none from the buyer, it is what the seller received.
    """
    transfers = [
        (
            address(int(log["address"], 16)),
            address(int(log["topics"][1], 16)),
            address(int(log["topics"][2], 16)),
            int(log["data"], 16),
        )
        for log in receipt_logs
        if len(log["topics"]) == ERC20_TRANSFER_TOPIC_COUNT and log["topics"][0] == TRANSFER_TOPIC
    ]
    paid_to_seller = [t for t in transfers if t[2] == seller]
    if not paid_to_seller:
        return None
    coin = paid_to_seller[0][0]
    from_buyer = sum(
        amount for token, payer, _, amount in transfers if token == coin and payer == buyer
    )
    if from_buyer:
        return Payment(coin, from_buyer, seller_received=False)
    received = sum(amount for token, _, _, amount in paid_to_seller if token == coin)
    return Payment(coin, received, seller_received=True)


def trace_payment(trace: dict[str, Any], seller: str, buyer: str) -> Payment | None:
    """The ETH payment in a callTracer trace, or None when no value call reaches the seller.

    The price is the value the buyer's wallet sent out; with none from the buyer, it is no sale.
    """
    value_calls = _value_calls(trace)
    if not any(to == seller for _, to, _ in value_calls):
        return None
    from_buyer = sum(value for sender, _, value in value_calls if sender == buyer)
    if not from_buyer:
        return None
    return Payment(ZERO_ADDRESS, from_buyer, seller_received=False)


def _value_calls(call: dict[str, Any]) -> list[tuple[str, str, int]]:
    """Every (from, to, value) in the call tree that carries ETH."""
    found = []
    value = int(call.get("value", "0x0"), 16)
    if value:
        found.append((call["from"].lower(), call["to"].lower(), value))
    for inner in call.get("calls", []):
        found.extend(_value_calls(inner))
    return found
