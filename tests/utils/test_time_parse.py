"""Tests for timeout / duration parsing."""

from __future__ import annotations

import pytest

from mergecraft.utils.time_parse import (
    TIMEOUT_DISABLED,
    is_valid_time_string,
    normalize_timeout_input,
    parse_time_string,
    parse_timeout,
    resolve_timeout_ms,
)


@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        ("10m", 600_000),
        ("1h", 3_600_000),
        ("30s", 30_000),
        ("1h30m", 5_400_000),
        ("10m12s", 612_000),
        ("1h30m45s", 5_445_000),
        ("2h", 7_200_000),
        ("90m", 5_400_000),
        ("0m", 0),
        ("0s", 0),
    ],
)
def test_parse_time_string_valid(input_value: str, expected: int) -> None:
    assert parse_time_string(input_value) == expected


@pytest.mark.parametrize(
    "input_value",
    ["", "abc", "10", "10x", "h10m", "m10", "10 m", "-10m", "10.5m", "10m 30s"],
)
def test_parse_time_string_invalid(input_value: str) -> None:
    assert parse_time_string(input_value) is None


@pytest.mark.parametrize("input_value", ["10m", "1h", "30s", "1h30m", "10m12s", "1h30m45s"])
def test_is_valid_time_string_true(input_value: str) -> None:
    assert is_valid_time_string(input_value) is True


@pytest.mark.parametrize("input_value", ["", "abc", "10", "10x", "-10m", "10.5m"])
def test_is_valid_time_string_false(input_value: str) -> None:
    assert is_valid_time_string(input_value) is False


@pytest.mark.parametrize(
    ("input_value", "expected"),
    [("1h", 3_600_000), ("10m", 600_000), ("1h30m", 5_400_000)],
)
def test_resolve_timeout_ms_valid(input_value: str, expected: int) -> None:
    assert resolve_timeout_ms(input_value) == expected


def test_resolve_timeout_ms_rejects_zero_and_overflow() -> None:
    assert resolve_timeout_ms(None) is None
    assert resolve_timeout_ms("0m") is None
    assert resolve_timeout_ms("0s") is None
    assert resolve_timeout_ms("999h") is None
    assert resolve_timeout_ms("600h") is None
    assert resolve_timeout_ms("abc") is None
    assert resolve_timeout_ms("596h31m23s") == 2_147_483_000


def test_normalize_and_parse_timeout_notimeout() -> None:
    assert normalize_timeout_input("--notimeout") == TIMEOUT_DISABLED
    assert normalize_timeout_input("notimeout") == TIMEOUT_DISABLED
    assert normalize_timeout_input("none") == TIMEOUT_DISABLED
    assert parse_timeout("--notimeout") is None
    assert parse_timeout("10m") == 600_000
    assert parse_timeout("0m") is None
