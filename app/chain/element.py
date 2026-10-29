"""Decoding Element's ElementEx fill events out of a transaction receipt."""

from typing import Any

from app.chain.abi import address
from app.chain.abi import words as abi_words
from app.chain.forum_one import DecodedSale
from app.nft.models import ZERO_ADDRESS

ELEMENT_EX = "0xa39a5f160a1952ddf38781bd76e402b0006912a9"
ELEMENT_ETH = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

# Fills of a listing: the maker sold to the taker.
LISTING_FILLED_TOPICS = frozenset(
    {
        "0x9c248aa1a265aa616f707b979d57f4529bb63a4fc34dc7fc61fdddc18410f74e",  # ERC721SellOrderFilled
        "0xfcde121a3f6a9b14a3ce266d61fc00940de86c4d8c1d733fe62d503ae5d99ff9",  # ERC1155SellOrderFilled
    }
)
# Fills of an offer: the maker bought from the taker.
OFFER_ACCEPTED_TOPICS = frozenset(
    {
        "0xd90a5c60975c6ff8eafcf02088e7b50ae5d9e156a79206ba553df1c4fb4594c2",  # ERC721BuyOrderFilled
        "0x105616901449a64554ca9246a5bbcaca973b40b3c0055e5070c6fa191618d9f3",  # ERC1155BuyOrderFilled
    }
)

# Data words, none indexed: orderHash, maker, taker, nonce, erc20Token, amount, fees offset,
# nft, tokenId (the 1155 events append the fill quantity).
MAKER_WORD, TAKER_WORD, COIN_WORD, AMOUNT_WORD, NFT_WORD, TOKEN_ID_WORD = 1, 2, 4, 5, 7, 8


def element_sales(receipt_logs: list[dict[str, Any]]) -> list[DecodedSale]:
    """The sales among a receipt's logs, from ElementEx's own fill events only."""
    sales = []
    for log in receipt_logs:
        if log["address"].lower() != ELEMENT_EX or not log["topics"]:
            continue
        topic = log["topics"][0]
        is_listing = topic in LISTING_FILLED_TOPICS
        if not (is_listing or topic in OFFER_ACCEPTED_TOPICS):
            continue
        data = abi_words(log["data"])
        maker, taker = address(data[MAKER_WORD]), address(data[TAKER_WORD])
        coin = address(data[COIN_WORD])
        sales.append(
            DecodedSale(
                asset_contract=address(data[NFT_WORD]),
                token_id=data[TOKEN_ID_WORD],
                seller=maker if is_listing else taker,
                buyer=taker if is_listing else maker,
                total_price=data[AMOUNT_WORD],
                currency=ZERO_ADDRESS if coin == ELEMENT_ETH else coin,
            )
        )
    return sales
