"""Safe display names for coins: a token contract chooses its own symbol(), so it is never trusted."""

import re

# Known Base coins by lowercase address: shown by their real name whatever symbol() says.
KNOWN_BASE_COINS: dict[str, str] = {
    "0x4200000000000000000000000000000000000006": "WETH",
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
}
MAX_SYMBOL_LENGTH = 11
_UNSAFE = re.compile(r"[^A-Za-z0-9.$_-]")


def sanitize_symbol(raw: str) -> str:
    """At most 11 characters from [A-Za-z0-9.$_-]; "tokens" when nothing is left."""
    return _UNSAFE.sub("", raw)[:MAX_SYMBOL_LENGTH] or "tokens"


def coin_label(address: str, raw_symbol: str) -> str:
    """The text to show for an ERC-20: its real name if known, else a sanitised unverified label."""
    known = KNOWN_BASE_COINS.get(address.lower())
    if known:
        return known
    return f"{sanitize_symbol(raw_symbol)} (unverified {address[:6]}…{address[-4:]})"
