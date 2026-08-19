"""Slash-command comment router with permission gating (DG8).

Library surface only — not wired into the review ``select_mode`` / dispatch path
yet.  DG8.2 extracts routing logic for unit tests; DG7/DG8 follow-on work connects
``route_comment`` and ``route_finding_challenge`` to Action comment handlers.
Only ``/mergecraft review`` resolves to a built-in mode today; ask/explain/verify/describe
refuse with ``mode_not_implemented`` until those modes exist.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.utils.payload import TRUSTED_AUTHOR_ASSOCIATIONS

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings

_SLASH_COMMAND_RE = re.compile(
    r"^/mergecraft\s+(review|ask|explain|verify|describe)\b",
    re.IGNORECASE,
)
_CHALLENGE_RE = re.compile(
    r"^/mergecraft\s+challenge\s+fp:([^\s—\-]+)",
    re.IGNORECASE,
)

# Built-in modes today (see mergecraft.modes) — only these may be routed.
_ROUTABLE_COMMANDS: frozenset[str] = frozenset({"review"})
_MODE_BY_COMMAND: dict[str, str] = {
    "review": "Review",
}

_PERMISSION_RANK: dict[str, int] = {
    "disabled": 0,
    "restricted": 1,
    "enabled": 2,
}


class CommentRouteResult(BaseModel):
    """Outcome of routing a PR comment body."""

    model_config = ConfigDict(extra="forbid")

    refused: bool
    mode: str | None = None
    reason: str | None = None
    effective_permissions: dict[str, str] = Field(default_factory=dict)


class FindingChallengeRouteResult(BaseModel):
    """Outcome of routing a finding-challenge comment."""

    model_config = ConfigDict(extra="forbid")

    refused: bool
    target: str | None = None
    mode: str | None = None
    fingerprint: str | None = None
    reason: str | None = None


def _normalize_association(association: str) -> str:
    return association.strip().upper()


def _author_allowed(
    *, association: str, allowlist: tuple[str, ...], author_login: str | None
) -> bool:
    normalized = _normalize_association(association)
    if normalized in TRUSTED_AUTHOR_ASSOCIATIONS:
        return True
    if author_login and allowlist:
        lowered = author_login.lower()
        return any(entry.lower() == lowered for entry in allowlist)
    return False


def _restrict_permission(repo_value: str, payload_value: str) -> str:
    repo_rank = _PERMISSION_RANK.get(str(repo_value), 0)
    payload_rank = _PERMISSION_RANK.get(payload_value, 0)
    rank = min(repo_rank, payload_rank)
    for name, value in _PERMISSION_RANK.items():
        if value == rank:
            return name
    return "disabled"


def _effective_permissions(
    *,
    repo_settings: RepoSettings,
    payload_permissions: dict[str, str],
) -> dict[str, str]:
    return {
        "shell": _restrict_permission(
            repo_settings.shell,
            str(payload_permissions.get("shell", repo_settings.shell)),
        ),
        "push": _restrict_permission(
            repo_settings.push,
            str(payload_permissions.get("push", repo_settings.push)),
        ),
    }


def route_comment(
    *,
    body: str,
    author_association: str,
    allowlist: tuple[str, ...],
    repo_settings: RepoSettings,
    payload_permissions: dict[str, str],
    author_login: str | None = None,
) -> CommentRouteResult:
    """Route ``/mergecraft …`` comments to built-in modes with permission gating."""
    effective = _effective_permissions(
        repo_settings=repo_settings,
        payload_permissions=payload_permissions,
    )

    if not _author_allowed(
        association=author_association,
        allowlist=allowlist,
        author_login=author_login,
    ):
        return CommentRouteResult(
            refused=True,
            reason=f"association={_normalize_association(author_association)}",
            effective_permissions=effective,
        )

    match = _SLASH_COMMAND_RE.match(body.strip())
    if match is None:
        return CommentRouteResult(
            refused=True,
            reason="unknown_command",
            effective_permissions=effective,
        )

    command = match.group(1).lower()
    if command not in _ROUTABLE_COMMANDS:
        return CommentRouteResult(
            refused=True,
            reason="mode_not_implemented",
            effective_permissions=effective,
        )

    mode = _MODE_BY_COMMAND[command]
    return CommentRouteResult(refused=False, mode=mode, effective_permissions=effective)


def route_finding_challenge(
    *,
    body: str,
    author_association: str,
    allowlist: tuple[str, ...],
    fingerprint: str | None = None,
    author_login: str | None = None,
) -> FindingChallengeRouteResult:
    """Route ``/mergecraft challenge fp:…`` comments to the verifier agent.

    When the comment body contains ``fp:…``, that fingerprint takes precedence
    over the explicit ``fingerprint`` parameter — the body reflects user intent.
    """
    if not _author_allowed(
        association=author_association,
        allowlist=allowlist,
        author_login=author_login,
    ):
        return FindingChallengeRouteResult(
            refused=True,
            reason=f"association={_normalize_association(author_association)}",
        )

    match = _CHALLENGE_RE.match(body.strip())
    parsed_fingerprint = match.group(1) if match else None
    resolved_fingerprint = parsed_fingerprint or fingerprint
    if not resolved_fingerprint:
        return FindingChallengeRouteResult(refused=True, reason="missing_fingerprint")

    return FindingChallengeRouteResult(
        refused=False,
        target="verifier",
        mode="Verify",
        fingerprint=resolved_fingerprint,
    )


__all__ = [
    "CommentRouteResult",
    "FindingChallengeRouteResult",
    "route_comment",
    "route_finding_challenge",
]
