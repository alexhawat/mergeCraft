"""BR1.1 / BR2 — ``redact_url`` scheme preservation (MCB-31)."""

from __future__ import annotations

_HTTP_BASIC = "http://user:canary-basic-auth-pass@example.com/path"
_HTTP_SECRET = "canary-basic-auth-pass"


def test_http_scheme_is_preserved() -> None:
    """MCB-31: basic-auth redaction must not rewrite ``http`` to ``https``."""
    from mergecraft.tracing.redaction import redact_url

    redacted = redact_url(_HTTP_BASIC)
    assert redacted.startswith("http://")
    assert not redacted.startswith("https://")
    assert _HTTP_SECRET not in redacted
