"""Multicall3 aggregate3 over eth_call: many read-only contract calls in one RPC request.

Multicall3 is a public contract at the same address on Ethereum and Base. Each call is
allowed to fail alone, so one reverting subcall does not lose the others.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from app.chain.rpc import RpcResponseError

MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"
AGGREGATE3_SELECTOR = "0x82ad56cb"  # aggregate3((address,bool,bytes)[])
WORD = 32


class Requester(Protocol):
    """The one transport call a lookup needs."""

    async def request(self, method: str, params: list[Any]) -> Any:  # noqa: ANN401  # JSON-RPC results are untyped JSON
        """Send one JSON-RPC call and return its result."""
        ...


@dataclass(frozen=True)
class Call:
    """One read: a contract and its ABI-encoded call data."""

    target: str
    data: bytes


def word(value: int) -> bytes:
    """An unsigned integer as one ABI word."""
    return value.to_bytes(WORD, "big")


def address_word(address: str) -> bytes:
    """A hex address as one ABI word."""
    return bytes.fromhex(address.removeprefix("0x")).rjust(WORD, b"\0")


def padded(raw: bytes) -> bytes:
    """Bytes right-padded with zeros to a whole number of words."""
    return raw.ljust(-(-len(raw) // WORD) * WORD, b"\0")


def encode_aggregate3(calls: list[Call]) -> str:
    """The calldata of aggregate3 with allowFailure = true on every call."""
    tuples = []
    for call in calls:
        tuples.append(
            address_word(call.target)
            + word(1)
            + word(3 * WORD)  # the bytes start after the three head words
            + word(len(call.data))
            + padded(call.data)
        )
    offsets = []
    position = len(calls) * WORD
    for encoded in tuples:
        offsets.append(word(position))
        position += len(encoded)
    body = word(WORD) + word(len(calls)) + b"".join(offsets) + b"".join(tuples)
    return AGGREGATE3_SELECTOR + body.hex()


def decode_aggregate3(result: str, expected: int) -> list[bytes | None]:
    """The return data of each subcall, None for one that failed.

    Raises RpcResponseError when the answer is not an aggregate3 result of the expected length.
    """
    try:
        raw = bytes.fromhex(result.removeprefix("0x"))
        count = _int_at(raw, WORD)
        if count != expected:
            raise RpcResponseError(f"aggregate3 answered {count} results for {expected} calls")
        elements = 2 * WORD  # offsets are relative to the first one
        answers: list[bytes | None] = []
        for i in range(count):
            start = elements + _int_at(raw, elements + i * WORD)
            success = _int_at(raw, start)
            data_start = start + _int_at(raw, start + WORD)
            length = _int_at(raw, data_start)
            data = raw[data_start + WORD : data_start + WORD + length]
            if len(data) != length:
                raise RpcResponseError("aggregate3 result is cut short")
            answers.append(data if success else None)
    except ValueError as e:
        raise RpcResponseError(f"aggregate3 result is not valid: {e}") from None
    return answers


def _int_at(raw: bytes, position: int) -> int:
    if position + WORD > len(raw):
        raise ValueError("cut short")
    return int.from_bytes(raw[position : position + WORD], "big")


async def aggregate3(chain: Requester, calls: list[Call]) -> list[bytes | None]:
    """Run the calls in one eth_call; a failed subcall gives None.

    Raises ChainConnectionError (or RpcResponseError) when the whole request fails.
    """
    result = await chain.request(
        "eth_call", [{"to": MULTICALL3, "data": encode_aggregate3(calls)}, "latest"]
    )
    if not isinstance(result, str):
        raise RpcResponseError(f"aggregate3 returned {result!r}")
    return decode_aggregate3(result, len(calls))


def address_in(data: bytes | None) -> str | None:
    """The address in one returned address word, None for a failed call or a zero address."""
    if data is None or len(data) < WORD or not any(data[:WORD]):
        return None
    return "0x" + data[WORD - 20 : WORD].hex()


def string_in(data: bytes | None) -> str | None:
    """The ABI string whose offset is the first word, None for a failed call or an empty string."""
    if data is None:
        return None
    try:
        start = _int_at(data, 0)
        length = _int_at(data, start)
        if length == 0 or start + WORD + length > len(data):
            return None
        return data[start + WORD : start + WORD + length].decode()
    except ValueError:  # includes UnicodeDecodeError
        return None
