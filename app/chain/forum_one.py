"""Decoding Forum One's sale events out of a transaction receipt."""

from dataclasses import dataclass
from typing import Any

from app.chain.abi import word_hex

FORUM_ONE_PROXY = "0x167afc814c5614c33b7140f6095a784b1f562582"

# keccak256 of each event signature in forumone-smart-contracts IForumOne.sol, mapped to the
# data word holding totalPrice. The data starts [assetContract, tokenId, quantity, ...]; the
# signed events add filledToDate before totalPrice, and currency always follows totalPrice.
TOTAL_PRICE_WORD: dict[str, int] = {
    "0x57922c657d2aa8c0407bcb047bc5a483d91c0f7e28188f214b14a84eab893be8": 3,  # Sale
    "0xf88935f945a788a879b9adf2f3f28f1500f1ccce23c42b83efbedb913fb87dca": 3,  # OfferAccepted
    "0x78a483c83edb347901adcedb783f01dc2e4d71ee9039ff4cb66b869109e8e4b5": 4,  # SignedListingFilled
    "0x3a4038ed4cc3e7ca35508d12ec6915481d30ca4b831828aed2355b4533de1a50": 4,  # SignedOfferAccepted
}


@dataclass(frozen=True)
class ForumOneSale:
    """One token sold through the Forum One proxy; the currency is an address (zero is ETH)."""

    asset_contract: str
    token_id: int
    seller: str
    buyer: str
    total_price: int
    currency: str


def forum_one_sales(receipt_logs: list[dict[str, Any]]) -> list[ForumOneSale]:
    """The sales among a receipt's logs, from the Forum One proxy's own events only."""
    sales = []
    for log in receipt_logs:
        topics = log["topics"]
        if log["address"].lower() != FORUM_ONE_PROXY or topics[0] not in TOTAL_PRICE_WORD:
            continue
        words = word_hex(log["data"])
        price_word = TOTAL_PRICE_WORD[topics[0]]
        sales.append(
            ForumOneSale(
                asset_contract="0x" + words[0][-40:],
                token_id=int(words[1], 16),
                seller="0x" + topics[2][-40:],
                buyer="0x" + topics[3][-40:],
                total_price=int(words[price_word], 16),
                currency="0x" + words[price_word + 1][-40:],
            )
        )
    return sales
