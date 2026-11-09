"""BR1.2 / BR3 — length-relative entropy redaction (MCB-26, D5/D6/D17)."""

from __future__ import annotations

import random
import secrets
import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mergecraft.redaction_sentinel import REDACTION_SENTINEL

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


_BASE62 = string.ascii_letters + string.digits


def _seeded_base62_tokens(length: int, *, lead: str, count: int = 200) -> list[str]:
    """Deterministic random base-62 tokens whose first character is ``lead``-cased."""
    rng = random.Random(f"redact-1232-{lead}-{length}")
    first = string.ascii_lowercase if lead == "lower" else string.ascii_uppercase
    return [
        rng.choice(first) + "".join(rng.choice(_BASE62) for _ in range(length - 1))
        for _ in range(count)
    ]


@pytest.mark.parametrize("lead", ["lower", "upper"])
@pytest.mark.parametrize("length", [24, 32, 64, 80, 120])
def test_random_base62_tokens_never_leak_through_free_text(length: int, lead: str) -> None:
    """#1232: camelCase exemption, length-relative threshold and the 64-char cut leaked tokens."""
    from mergecraft.analyzers.redact import redact_secrets

    leaked = [
        token
        for token in _seeded_base62_tokens(length, lead=lead)
        if token in redact_secrets(f"error: value {token} rejected")
        or token in redact_secrets(token)
    ]
    assert leaked == []


@pytest.mark.parametrize(
    "key",
    [
        "ruleId",
        "startLine",
        "physicalLocation",
        "partialFingerprints",
        "artifactLocation",
        "originalUriBaseIds",
        "primaryLocationLineHash",
        "fullyQualifiedName",
        "toolExecutionNotifications",
        "getHTTPResponseCode",
        "contextRetrievalTimeoutS",
        "sha256Digest",
    ],
)
def test_wordy_camel_case_keys_stay_readable(key: str) -> None:
    """#1232: tightening the camelCase shape must keep real SARIF/config keys benign."""
    from mergecraft.analyzers.redact import redact_secrets

    assert redact_secrets(key) == key
    assert redact_secrets(f"missing {key} in result") == f"missing {key} in result"


def test_long_benign_shapes_survive_the_absolute_entropy_ceiling() -> None:
    """#1232: the capped threshold must not blank hex digests or plain long paths."""
    from mergecraft.analyzers.redact import redact_secrets

    sha512 = "0123456789abcdef" * 8
    path = "src/mergecraft/analyzers/parsers/very_long_module_name_for_testing_paths.py"
    for value in (sha512, path, f"see {path}:12"):
        assert redact_secrets(value) == value


def _fake_credential(prefix: str, length: int) -> str:
    rng = random.Random(prefix)
    return prefix + "".join(rng.choice(_BASE62) for _ in range(length))


@pytest.mark.parametrize(
    "secret",
    [
        pytest.param(_fake_credential("github" + "_pat_", 82), id="github-fine-grained-pat"),
        pytest.param(_fake_credential("pypi" + "-AgEIcHlwaS5vcmc", 60), id="pypi-token"),
        pytest.param(_fake_credential("sk-" + "ant-api03-", 40), id="anthropic-key"),
        pytest.param(_fake_credential("sk-" + "proj-", 40), id="openai-project-key"),
    ],
)
def test_prefixed_credentials_are_redacted_in_free_text(secret: str) -> None:
    """#1232: provider token prefixes redact regardless of the entropy heuristics."""
    from mergecraft.analyzers.redact import redact_secrets

    redacted = redact_secrets(f"auth failed for {secret} (401)")
    assert secret not in redacted
    assert redacted == f"auth failed for {REDACTION_SENTINEL} (401)"


def test_bearer_credential_is_redacted_and_scheme_kept() -> None:
    """#1232: ``Bearer <token>`` keeps the scheme word, drops the credential."""
    from mergecraft.analyzers.redact import redact_secrets

    token = "abc.def-ghi_jkl~mno+pq/rs="
    redacted = redact_secrets(f"Authorization: Bearer {token}")
    assert redacted == f"Authorization: Bearer {REDACTION_SENTINEL}"
    assert redact_secrets("use a bearer token here") == "use a bearer token here"


def test_pypi_workflow_slug_is_not_a_pypi_token() -> None:
    """#1232: the PyPI rule anchors on the macaroon header, not any ``pypi-`` slug."""
    from mergecraft.analyzers.redact import redact_secrets

    slug = "pypi-publish-release-workflow"
    assert redact_secrets(f"job {slug} finished") == f"job {slug} finished"


def test_long_rejected_identifier_does_not_backtrack() -> None:
    import subprocess
    import sys

    subprocess.run(
        [
            sys.executable,
            "-c",
            "from mergecraft.analyzers.redact import redact_secrets; "
            "redact_secrets('a' + '_0' * 10000 + '+'); "
            "redact_secrets('a_' + '_0' * 10000 + '+')",
        ],
        check=True,
        timeout=10,
    )


@pytest.mark.parametrize("identifier", ["a_b", "a__", "a_b__c_", "_private_name", "UPPER_CASE"])
def test_snake_case_identifier_shapes_remain_readable(identifier: str) -> None:
    from mergecraft.analyzers.redact import _is_benign_identifier

    assert _is_benign_identifier(identifier)
