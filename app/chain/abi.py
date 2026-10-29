"""Splitting ABI-encoded receipt data into 32-byte words."""


def word_hex(data: str) -> list[str]:
    """The 64-hex-char words of a log's data."""
    hex_data = data.removeprefix("0x")
    return [hex_data[i : i + 64] for i in range(0, len(hex_data), 64)]


def words(data: str) -> list[int]:
    return [int(word, 16) for word in word_hex(data)]


def address(word: int) -> str:
    """The address held in the low 20 bytes of a word."""
    return "0x" + f"{word:064x}"[-40:]
