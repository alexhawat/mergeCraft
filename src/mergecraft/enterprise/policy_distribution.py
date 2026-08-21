"""Org policy distribution without a dashboard (#381, D6).

Wraps ``mergecraft.policy`` — does not re-author it.

Exports:
    distribute_org_policy: Distribute policy rules from a file path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mergecraft.policy import parse_rules_document

__all__ = [
    "distribute_org_policy",
]


def distribute_org_policy(
    rules_path: Path | None,
    *,
    dashboard_url: str | None,
) -> Any:
    """Distribute organisation policy rules from a file.

    Policy distribution is **file/API-only** — a dashboard URL is refused so
    the workflow cannot depend on a dashboard being available (#381).

    Args:
        rules_path: Path to a YAML rules document.  Must be provided and must
            exist when *dashboard_url* is ``None``.
        dashboard_url: Must be ``None``.  Passing a non-``None`` value raises
            ``ValueError`` because distribution must work without a dashboard.

    Returns:
        The parsed rules document returned by :func:`mergecraft.policy.parse_rules_document`.

    Raises:
        ValueError: When *dashboard_url* is not ``None``.
        ValueError: When *rules_path* is ``None`` (no source available).
    """
    if dashboard_url is not None:
        msg = (
            "policy distribution via a dashboard URL is not supported — "
            "distribution must work without a dashboard (#381)"
        )
        raise ValueError(msg)
    if rules_path is None:
        msg = "rules_path is required when dashboard_url is None"
        raise ValueError(msg)

    text = Path(rules_path).read_text(encoding="utf-8")
    return parse_rules_document(text)
