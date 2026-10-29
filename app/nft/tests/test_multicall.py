"""Parsing of untrusted aggregate3 answers: malformed ones fail the whole call, not one name."""

from typing import Any

import pytest

from app.chain.rpc import RpcResponseError
from app.nft.multicall import Call, aggregate3, decode_aggregate3, string_in, word


def one_result(success: int, data: bytes) -> str:
    body = word(32) + word(1) + word(32) + word(success) + word(64) + word(len(data)) + data
    return "0x" + body.hex()


class Fixed:
    def __init__(self, result: Any) -> None:
        self._result = result

    async def request(self, method: str, params: list[Any]) -> Any:  # noqa: ARG002
        return self._result


def test_decodes_a_success_and_a_failure() -> None:
    assert decode_aggregate3(one_result(1, b"ab"), 1) == [b"ab"]
    assert decode_aggregate3(one_result(0, b"ab"), 1) == [None]


def test_wrong_result_count_is_an_error() -> None:
    with pytest.raises(RpcResponseError):
        decode_aggregate3(one_result(1, b"ab"), 2)


def test_short_result_is_an_error() -> None:
    with pytest.raises(RpcResponseError):
        decode_aggregate3(one_result(1, b"ab")[:-4], 1)
    with pytest.raises(RpcResponseError):
        decode_aggregate3("0x", 1)


def test_invalid_hex_is_an_error() -> None:
    with pytest.raises(RpcResponseError):
        decode_aggregate3("0xzz", 1)


async def test_non_string_result_is_an_error() -> None:
    with pytest.raises(RpcResponseError):
        await aggregate3(Fixed(None), [Call("0x" + "1" * 40, b"")])


def test_string_in_rejects_bad_data() -> None:
    assert string_in(word(32) + word(2) + b"hi".ljust(32, b"\0")) == "hi"
    assert string_in(word(32) + word(2) + b"\xff\xfe".ljust(32, b"\0")) is None
    assert string_in(word(10_000) + word(2)) is None
    assert string_in(word(32) + word(1_000)) is None
    assert string_in(None) is None
