"""Redaction layer for ``TraceEvent.attrs`` (D7).

Builds on the existing helpers in :mod:`mergecraft.analyzers.redact` and
:mod:`mergecraft.utils.secrets` — no second matcher is implemented here. The
tracing-specific additions are:

1. A deny-key list — any attr whose key (case-insensitive) appears here has
   its value replaced with the literal ``"[REDACTED]"``.
2. The deny-value patterns ``ghp_*`` / ``sk-*`` already match inside
   :func:`mergecraft.analyzers.redact.redact_secrets`; this module applies
   the existing helper to every string value (recursively into nested
   dicts and lists) so a ``ghp_…`` or ``sk-…`` substring cannot escape.

Exports:
    DENY_KEYS -- tuple of attr keys whose values are dropped wholesale.
    redact_attrs -- recursively redact an ``attrs`` dict, returning a new dict.
    redact_event -- return a deep-copied ``TraceEvent`` with redacted attrs.
    redact_cli_argv -- mask token/secret-like CLI argv values for ``agent.cli_argv``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.redact import redact_secrets

if TYPE_CHECKING:
    from mergecraft.tracing.event import TraceEvent

# A CLI argv token that looks like a secret/credential — mask its value (the
# word after the flag, or the flag's ``=value`` suffix). Matches the project's
# existing redaction policy: anything shaped like ``--token sk-…``,
# ``--api-key=ghp_…``, or a bare ``sk-…`` / ``ghp_…`` bearer is redacted.
_CLI_SECRET_FLAG = re.compile(
    r"^(?:--|[-/])?(?:token|api[-_]?key|secret|password|auth[-_]?token|access[-_]?token"
    r"|refresh[-_]?token|bearer[-_]?token|client[-_]?secret|private[-_]?key"
    r"|pat|passwd|LOGFIRE_TOKEN|GITHUB_TOKEN|ANTHROPIC_API_KEY|OPENAI_API_KEY"
    r"|GEMINI_API_KEY|CODEX_AUTH_JSON|NOUS_API_KEY|TOKENHUB_API_KEY)$",
    re.IGNORECASE,
)
_CLI_SECRET_VALUE = re.compile(
    r"^(?:sk-|ghp_|gho_|ghu_|ghs_|ghr_|eyJ|AKIA|Bearer\s)", re.IGNORECASE
)
_REDACTED = "[REDACTED]"

DENY_KEYS: tuple[str, ...] = (
    "authorization",
    "cookie",
    "api_key",
    "secret",
    "password",
    "access_token",
    "refresh_token",
    "id_token",
    "bearer_token",
    "auth_token",
)

_REDACTED = "[REDACTED]"


def _redact_value(value: Any) -> Any:
    """Recursively redact a value: strings via the shared helper, structures recursively."""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


def redact_attrs(attrs: dict[str, Any] | None) -> dict[str, Any]:
    """Return a redacted copy of ``attrs`` (never the input dict)."""
    if not attrs:
        return {}
    out: dict[str, Any] = {}
    for key, value in attrs.items():
        if key.lower() in DENY_KEYS:
            out[key] = _REDACTED
            continue
        out[key] = _redact_value(value)
    return out


def redact_event(event: TraceEvent) -> TraceEvent:
    """Return a deep-copied :class:`TraceEvent` with redacted ``attrs``."""
    return event.model_copy(update={"attrs": redact_attrs(event.attrs)})


def redact_cli_argv(argv: list[str]) -> str:
    """Mask token/secret-like values in a CLI argv list for ``agent.cli_argv``.

    Preserves the command shape (flags, positional args, model names, paths) so
    an operator can see *which* command ran without exposing any credential. A
    flagged token (``--api-key``, ``GH_TOKEN=…``, etc.) has its value
    replaced with ``[REDACTED]``; a bare bearer-shaped value
    (``sk-…`` / ``ghp_…`` / ``eyJ…``) is masked wherever it appears; and the
    shared substring matcher still catches any ``ghp_…`` / ``sk-…`` that
    slips through.

    Args:
        argv (list[str]): The process argv (e.g. ``sys.argv``).

    Returns:
        str: A single space-joined, redacted command line.

    Examples:
        >>> redact_cli_argv(["mergecraft", "diff-review", "--api-key", "sk-abc123"])
        'mergecraft diff-review --api-key [REDACTED]'
    """
    if not argv:
        return ""
    masked: list[str] = []
    for index, token in enumerate(argv):
        if "=" in token:
            key, _, val = token.partition("=")
            if _CLI_SECRET_FLAG.match(key):
                masked.append(f"{key}={_REDACTED}")
                continue
            if _CLI_SECRET_VALUE.match(val):
                masked.append(f"{key}={_REDACTED}")
                continue
        if _CLI_SECRET_FLAG.match(token) and index + 1 < len(argv):
            masked.append(token)
            masked.append(_REDACTED)
            continue
        if _CLI_SECRET_VALUE.match(token):
            masked.append(_REDACTED)
            continue
        masked.append(redact_secrets(token))
    return " ".join(masked)


__all__ = ["DENY_KEYS", "redact_attrs", "redact_cli_argv", "redact_event"]
