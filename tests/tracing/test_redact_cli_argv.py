"""BR1.1 / BR2 — ``redact_cli_argv`` contracts (MCB-02, D2, D17)."""

from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# Fixed canaries — never generated (plan rule).
_HUNTER2 = "hunter2correcthorse"
_GLPAT = "glpat-REDTEST-BR1-CANARY-ONLY"
_GEMINI = "AIzaSyREDTESTBR1CANARY000000000"
_PLAIN = "xyz-plain-secret"
_SK_API_KEY = "sk-live-redact-cli-argv-canary-01"


@pytest.mark.parametrize(
    ("argv", "secret"),
    [
        (["mergecraft", "review", "--password", _HUNTER2], _HUNTER2),
        (["tool", f"--token={_GLPAT}"], _GLPAT),
        (["run", "--api-key", _GEMINI], _GEMINI),
        (["scan", "--secret", _PLAIN], _PLAIN),
    ],
    ids=["password-flag", "token-equals", "api-key-flag", "secret-flag"],
)
def test_no_secret_survives_a_flagged_argv(argv: list[str], secret: str) -> None:
    """D2: assert the secret is absent from redacted argv output."""
    from mergecraft.tracing.redaction import redact_cli_argv

    redacted = redact_cli_argv(argv)
    assert secret not in redacted


def test_flagged_value_is_not_doubled() -> None:
    """MCB-02: ``--api-key sk-…`` must not emit the secret after the placeholder."""
    from mergecraft.tracing.redaction import redact_cli_argv

    argv = ["mergecraft", "diff-review", "--api-key", _SK_API_KEY]
    redacted = redact_cli_argv(argv)
    assert _SK_API_KEY not in redacted
    assert redacted.count("<redacted>") == 1


_FLAG_NAMES = st.sampled_from(
    [
        "--api-key",
        "--token",
        "--secret",
        "GH_TOKEN",
        "ANTHROPIC_API_KEY",
    ]
)
_SECRET_VALUES = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters=" \t\n\r"),
    min_size=8,
    max_size=48,
).filter(lambda value: value.strip() and " " not in value)


@settings(max_examples=80, deadline=None)
@given(flag=_FLAG_NAMES, secret=_SECRET_VALUES)
def test_hypothesis_no_secret_ever_follows_a_flag(flag: str, secret: str) -> None:
    """D17 / MCB-02: property — flagged values never survive in argv redaction."""
    from mergecraft.tracing.redaction import redact_cli_argv

    redacted = redact_cli_argv(["mergecraft", "run", flag, secret])
    assert secret not in redacted
    if secret in redacted:
        # Guard against partial overlaps: the full secret token must be absent.
        assert not re.search(re.escape(secret), redacted)
