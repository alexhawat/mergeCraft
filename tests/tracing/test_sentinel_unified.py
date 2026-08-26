"""BR1.7 / BR8 — unified redaction sentinel (MCB-30, D7)."""

from __future__ import annotations


def test_exactly_one_distinct_sentinel_across_redaction_surfaces() -> None:
    """MCB-30: tracing and analyzer redactors must emit one canonical sentinel."""
    from mergecraft.redaction_sentinel import REDACTION_SENTINEL

    from mergecraft.analyzers.redact import redact_secrets
    from mergecraft.tracing.redaction import REDACTED, redact_cli_argv, redact_url

    secret = "sk-br1-sentinel-canary-abcdefghijklmnop"
    cli = redact_cli_argv(["mergecraft", "run", "--api-key", secret])
    url = redact_url(f"https://example.com/v1?api_key={secret}")
    text = redact_secrets(f"bearer {secret}")

    emitted = {REDACTED, REDACTION_SENTINEL}
    for surface, material in (("cli", cli), ("url", url), ("analyzer", text)):
        assert secret not in material, f"{surface} leaked the secret"
        assert any(marker in material for marker in emitted), f"{surface} missing sentinel"
    assert REDACTED == REDACTION_SENTINEL
    assert len({REDACTED, REDACTION_SENTINEL}) == 1

    # Regression guard: legacy dual spellings must not both appear on one surface.
    legacy = {"<redacted>", "[REDACTED]"}
    combined = f"{cli} {url} {text}"
    present = {marker for marker in legacy if marker in combined}
    assert len(present) <= 1
