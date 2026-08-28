"""BR1.2 / BR3 — length-relative entropy redaction (MCB-26, D5/D6/D17)."""

from __future__ import annotations

import secrets
import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

_BENIGN_STRINGS = [
    "a" * 40,
    "deadbeef" * 8,
    "0123456789abcdef" * 4,
    "my_variable_name",
    "fetch_user_profile",
]


def _high_entropy_token(length: int) -> str:
    alphabet = string.ascii_letters + string.digits + "+/=_-"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@pytest.mark.parametrize("length", [20, 32, 40])
def test_detection_rate_at_lengths_20_32_40(length: int) -> None:
    """D6: statistical detection floor at credential-shaped lengths."""
    from mergecraft.analyzers.redact import redact_secrets

    samples = 32
    detected = 0
    for _ in range(samples):
        token = _high_entropy_token(length)
        if token not in redact_secrets(token):
            detected += 1
    # Floor: at least half of random high-entropy tokens at these lengths redact.
    assert detected >= samples // 2


@pytest.mark.parametrize("benign", _BENIGN_STRINGS)
def test_known_benign_strings_are_untouched(benign: str) -> None:
    """D5/D6: git SHAs, hex runs, and identifiers must survive entropy pass."""
    from mergecraft.analyzers.redact import redact_secrets

    assert redact_secrets(benign) == benign


_TOKEN_ALPHABET = st.characters(
    whitelist_categories=("Lu", "Ll", "Nd"),
    whitelist_characters="+/=_-",
)


@settings(max_examples=60, deadline=None)
@given(
    token=st.text(_TOKEN_ALPHABET, min_size=24, max_size=48).filter(lambda value: len(value) >= 24)
)
def test_hypothesis_high_entropy_tokens_are_redacted(token: str) -> None:
    """D17 / MCB-26: property — long high-entropy tokens are redacted."""
    from mergecraft.analyzers.redact import redact_secrets

    # Skip if token is too uniform to be high-entropy.
    if len(set(token)) < 8:
        return
    redacted = redact_secrets(token)
    assert token not in redacted
