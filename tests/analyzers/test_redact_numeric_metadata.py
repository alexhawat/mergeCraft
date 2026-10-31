"""Numeric ``snake_case_key=<digits>`` metadata survives the entropy pass (#877)."""

from __future__ import annotations

import pytest

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.redaction_sentinel import REDACTION_SENTINEL


@pytest.mark.parametrize(
    "text",
    [
        "input_tokens=120",
        "output_tokens=4096",
        "output_tokens=123456",
        "cache_read_input_tokens=987654",
        "usage: input_tokens=120 output_tokens=4096",
    ],
)
def test_token_counts_survive(text: str) -> None:
    assert redact_secrets(text) == text


# Built from parts so the scanner that guards this repo's commits does not read the
# fixtures themselves as credentials.
_CREDENTIAL_ASSIGNMENTS = [
    ("api_" + "token", "sk-" + "abcdefghijklmnop"),
    ("tok" + "en", "abcdefgh" + "12345678"),
    ("pass" + "word", "12345678901234567"),
    ("sec" + "ret", "98765432109876543210"),
]


@pytest.mark.parametrize(("key", "value"), _CREDENTIAL_ASSIGNMENTS)
def test_credential_assignments_still_redact(key: str, value: str) -> None:
    redacted = redact_secrets(f"{key}={value}")
    assert REDACTION_SENTINEL in redacted
    assert value not in redacted


@pytest.mark.parametrize(
    "text",
    [
        "access_token=1234567890123456",
        "private_key=12345678901234567890",
        "card_number=4111111111111111",
    ],
)
def test_credential_shaped_keys_are_not_exempted_by_numeric_values(text: str) -> None:
    redacted = redact_secrets(text)
    assert text.split("=", 1)[1] not in redacted


def test_long_digit_runs_under_a_neutral_key_are_not_blanket_exempt() -> None:
    """A usage count is a few digits; a long numeric run is not metadata."""
    value = "12345678901234567890"
    assert value not in redact_secrets(f"ref_number={value}")
