"""Decoding Rarible's ExchangeMetaV2 Match event out of a transaction receipt."""

from typing import Any

from app.chain.abi import address
from app.chain.abi import words as abi_words
from app.chain.forum_one import ForumOneSale
from app.nft.models import ZERO_ADDRESS

EXCHANGE_META_V2 = "0x6c65a3c3aa67b126e43f86da85775e0f5e9743f7"
# Match(bytes32 leftHash, bytes32 rightHash, uint256 newLeftFill, uint256 newRightFill)
MATCH_TOPIC = "0x956cd63ee4cdcd81fda5f0ec7c6c36dceda99e1b412f4a650a5d26055dc3c450"
ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

LEFT_FILL_WORD, RIGHT_FILL_WORD = 2, 3
ERC721_AMOUNT = 1


def rarible_sale(
    receipt_logs: list[dict[str, Any]], contract: str, token_id: int, seller: str, buyer: str
) -> ForumOneSale | None:
    """The sale a receipt's Match event made of the given token, or None without a Match.

    Match names no token, seller, buyer or coin, so the caller supplies the token and its
    transfer parties. The price is the fill word that is not the NFT amount, and the coin is
    the ERC-20 paid out to the seller, ETH when there is none.
    """
    for log in receipt_logs:
        if log["address"].lower() != EXCHANGE_META_V2 or log["topics"][0] != MATCH_TOPIC:
            continue
        data = abi_words(log["data"])
        left, right = data[LEFT_FILL_WORD], data[RIGHT_FILL_WORD]
        return ForumOneSale(
            asset_contract=contract,
            token_id=token_id,
            seller=seller,
            buyer=buyer,
            total_price=right if left == ERC721_AMOUNT else left,
            currency=_payout_coin(receipt_logs, seller),
        )
    return None


def _payout_coin(receipt_logs: list[dict[str, Any]], seller: str) -> str:
    """The ERC-20 whose Transfer pays the seller; 3 topics tell it from an ERC-721 Transfer."""
    for log in receipt_logs:
        topics = log["topics"]
        if (
            len(topics) == 3
            and topics[0] == ERC20_TRANSFER_TOPIC
            and address(int(topics[2], 16)) == seller
        ):
            return address(int(log["address"], 16))
    return ZERO_ADDRESS
