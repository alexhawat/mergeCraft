"""Shared copy for api-only review scope (plan 13 W4 / D2)."""

from __future__ import annotations

API_ONLY_SCOPE = "api-only"

API_ONLY_SCOPE_GUIDANCE = (
    "The diff is complete and authoritative; head-side file reads are unavailable — "
    "use `git show <base>:path` and the diff; do not claim to have read a head file."
)

CHECKOUT_STEP_NOTE = (
    '**api-only scope:** when `checkout_pr` returns `scope: "api-only"`, ' + API_ONLY_SCOPE_GUIDANCE
)


def degraded_checkout_reason(*, detail: str) -> str:
    """Human-readable degradation reason for ``checkout_pr`` payloads."""
    return (
        f"PR head could not be fetched locally ({detail}); review scope is "
        f"{API_ONLY_SCOPE} — {API_ONLY_SCOPE_GUIDANCE}"
    )


__all__ = [
    "API_ONLY_SCOPE",
    "API_ONLY_SCOPE_GUIDANCE",
    "CHECKOUT_STEP_NOTE",
    "degraded_checkout_reason",
]
