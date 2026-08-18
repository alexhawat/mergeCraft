"""Redacted mismatch diagnostics for provider-harness."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.analyzers.redact import redact_secrets
from tests.support.provider_harness.matcher import (
    AmbiguousFixtureMatch,
    FixtureReuseError,
    NoFixtureMatch,
)
from tests.support.provider_harness.redaction import sanitize_json_text

if TYPE_CHECKING:
    from tests.support.provider_harness.metrics import HarnessMetrics

_BODY_CAP = 2048


def _redact_body(body: object) -> str:
    if body is None:
        return ""
    redacted = sanitize_json_text(body)
    if len(redacted) > _BODY_CAP:
        return redacted[: _BODY_CAP - 3] + "..."
    return redacted


def _redact_reason(reason: str) -> str:
    redacted = redact_secrets(reason)
    if len(redacted) > _BODY_CAP:
        return redacted[: _BODY_CAP - 3] + "..."
    return redacted


def format_mismatch(
    error: Exception,
    *,
    metrics: HarnessMetrics | None = None,
    latency_ms: float | None = None,
) -> str:
    if isinstance(error, NoFixtureMatch):
        req = error.request
        lines = [
            "fixture mismatch: no match",
            f"provider: {req.get('provider', '?')}",
            f"model: {req.get('model', '?')}",
            f"mode: {req.get('mode', '?')}",
            f"turn_index: {req.get('turn_index', 0)}",
            f"request body (redacted): {_redact_body(req.get('body'))}",
            "candidates:",
        ]
        for name, reason in error.candidate_reasons.items():
            lines.append(f"  - {name}: {_redact_reason(reason)}")
    elif isinstance(error, AmbiguousFixtureMatch):
        names = ", ".join(m.name for m in error.matches)
        lines = [f"fixture mismatch: ambiguous match among {names}"]
    elif isinstance(error, FixtureReuseError):
        fix = error.fixture
        lines = [
            f"fixture mismatch: reuse limit for {fix.name!r} "
            f"(max_uses={fix.max_uses}, use_count={fix.used_count})"
        ]
    else:
        return redact_secrets(str(error))

    if metrics is not None:
        snap = metrics.snapshot()
        lines.append(f"fixture_usage: {snap.get('fixture_usage', {})}")
    if latency_ms is not None:
        lines.append(f"latency_ms: {latency_ms:.2f}")
    return "\n".join(lines)
