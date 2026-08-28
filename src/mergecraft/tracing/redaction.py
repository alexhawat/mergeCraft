"""Redaction layer for ``TraceEvent.attrs`` (D7).

Builds on the existing helpers in :mod:`mergecraft.analyzers.redact` and
:mod:`mergecraft.utils.secrets` — no second matcher is implemented here. The
tracing-specific additions are:

1. A deny-key list — any attr whose key (case-insensitive) appears here has
   its value replaced with the canonical ``"<redacted>"`` sentinel
   (W4 / H4 — was three different literals across this module, the
   legacy analyzer redaction, and the tool-payload helper).
2. The deny-value patterns ``ghp_*`` / ``sk-*`` already match inside
   :func:`mergecraft.analyzers.redact.redact_secrets`; this module applies
   the existing helper to every string value (recursively into nested
   dicts and lists) so a ``ghp_…`` or ``sk-…`` substring cannot escape.

Exports:
    DENY_KEYS -- tuple of attr keys whose values are dropped wholesale.
    REDACTED -- sentinel literal ``"<redacted>"`` used by URL + tool-payload redaction.
    redact_attrs -- recursively redact an ``attrs`` dict, returning a new dict.
    redact_event -- return a deep-copied ``TraceEvent`` with redacted attrs.
    redact_cli_argv -- mask token/secret-like CLI argv values for ``agent.cli_argv``.
    redact_url -- inline-redact credential-bearing portions of a URL.
    redact_tool_payload -- stringify + cap + secret-redact a tool input/output.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.redaction_sentinel import REDACTION_SENTINEL
from mergecraft.redaction_structured import DENY_KEYS, redact_structured_value
from mergecraft.tracing.cap import TRACE_ATTRS_JSON_MAX_BYTES

if TYPE_CHECKING:
    from mergecraft.tracing.event import TraceEvent

# A CLI argv token that looks like a secret/credential — mask its value (the
# word after the flag, or the flag's ``=value`` suffix). Matches the project's
# existing redaction policy: anything shaped like ``--token sk-…``,
# ``--api-key=ghp_…``, or a bare ``sk-…`` / ``ghp_…`` bearer is redacted.
_CLI_SECRET_FLAG = re.compile(
    r"^(?:--|[-/])?(?:token|api[-_]?key|secret|password|auth[-_]?token|access[-_]?token"
    r"|refresh[-_]?token|bearer[-_]?token|client[-_]?secret|private[-_]?key"
    r"|pat|passwd|LOGFIRE_TOKEN|GITHUB_TOKEN|GH_TOKEN|ANTHROPIC_API_KEY|OPENAI_API_KEY"
    r"|GEMINI_API_KEY|CODEX_AUTH_JSON|NOUS_API_KEY|TOKENHUB_API_KEY)$",
    re.IGNORECASE,
)
_CLI_SECRET_VALUE = re.compile(
    r"^(?:sk-|ghp_|gho_|ghu_|ghs_|ghr_|eyJ|AKIA|Bearer\s|Basic\s)", re.IGNORECASE
)
REDACTED = REDACTION_SENTINEL

# Inline URL redaction markers — T2 / PR D9. ``redact_url`` masks the
# credential-bearing portion of a URL while preserving scheme/host/path so
# the URL stays readable (and parseable) in Logfire rows.
_TELEGRAM_BOT_RE = re.compile(r"https?://api\.telegram\.org/bot[^/?\s]+")
_BASIC_AUTH_RE = re.compile(r"(https?)://([^:@\s]+):[^@\s]+@")
_QUERY_TOKEN_KEYS = ("api_key", "access_token", "token", "key", "secret")
_QUERY_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(_QUERY_TOKEN_KEYS) + r")=([^&\s]+)")
# ``Basic`` covers git-over-HTTPS auth: mergeCraft brokers the GitHub token as
# ``Authorization: Basic base64("x-access-token:<token>")`` (issue #544), so the
# raw ``ghs_``/``gho_`` prefix is no longer visible to the prefix patterns.
_BEARER_RE = re.compile(r"((?:Bearer|Basic)\s)[A-Za-z0-9+/=._-]{16,}")
_EMBEDDED_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(sk-|ghp_|eyJ)[A-Za-z0-9._-]{8,}")


def redact_attrs(attrs: dict[str, Any] | None) -> dict[str, Any]:
    """Return a redacted copy of ``attrs`` (never the input dict)."""
    if not attrs:
        return {}
    redacted = redact_structured_value(attrs, redact_string=redact_secrets)
    if not isinstance(redacted, dict):
        return {}
    return redacted


def redact_event(event: TraceEvent) -> TraceEvent:
    """Return a deep-copied :class:`TraceEvent` with redacted ``attrs``."""
    return event.model_copy(update={"attrs": redact_attrs(event.attrs)})


def redact_cli_argv(argv: list[str]) -> str:
    """Mask token/secret-like values in a CLI argv list for ``agent.cli_argv``.

    Preserves the command shape (flags, positional args, model names, paths) so
    an operator can see *which* command ran without exposing any credential. A
    flagged token (``--api-key``, ``GH_TOKEN=…``, etc.) has its value
    replaced with the canonical :data:`REDACTED` sentinel (``"<redacted>"``);
    a bare bearer-shaped value (``sk-…`` / ``ghp_…`` / ``eyJ…``) is masked
    wherever it appears; and the shared substring matcher still catches any
    ``ghp_…`` / ``sk-…`` that slips through.

    Args:
        argv (list[str]): The process argv (e.g. ``sys.argv``).

    Returns:
        str: A single space-joined, redacted command line.

    Examples:
        >>> redact_cli_argv(["mergecraft", "diff-review", "--api-key", "sk-abc123"])
        'mergecraft diff-review --api-key <redacted>'
    """
    if not argv:
        return ""
    masked: list[str] = []
    skip_next = False
    for index, token in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if "=" in token:
            key, _, val = token.partition("=")
            if _CLI_SECRET_FLAG.match(key):
                masked.append(f"{key}={REDACTED}")
                continue
            if _CLI_SECRET_VALUE.match(val):
                masked.append(f"{key}={REDACTED}")
                continue
        if _CLI_SECRET_FLAG.match(token) and index + 1 < len(argv):
            masked.append(token)
            masked.append(REDACTED)
            skip_next = True
            continue
        if _CLI_SECRET_VALUE.match(token):
            masked.append(REDACTED)
            continue
        masked.append(redact_secrets(token))
    return " ".join(masked)


def redact_url(url: str) -> str:
    """Inline-redact credential-bearing portions of a URL (D9 / T2).

    Patterns, applied in order (first match wins per region):

    1. ``api.telegram.org/bot<TOKEN>`` → ``api.telegram.org/bot<redacted>``
    2. ``https://user:pass@host`` → ``https://user:<redacted>@host`` (basic auth)
    3. ``?api_key=…&token=…&key=…`` → ``?<key>=<redacted>`` (query token params)
    4. ``Bearer sk-…`` / ``Basic <b64>`` → ``<scheme> <redacted>`` (header values)
    5. Catch-all for embedded ``sk-*`` / ``ghp_*`` / ``eyJ*`` substrings.

    The URL stays parseable (D9 "inline, not opaque"): scheme, host, port,
    path, and non-token query parameters are preserved so Logfire's
    path-based grouping keeps working on the redacted form.

    Args:
        url (str): The URL or URL-shaped string to redact.

    Returns:
        str: The redacted URL.

    Examples:
        >>> redact_url("https://api.telegram.org/bot123456:ABC/sendMessage")
        'https://api.telegram.org/bot<redacted>/sendMessage'
        >>> redact_url("https://user:pass@example.com/path")
        'https://user:<redacted>@example.com/path'
        >>> redact_url("https://example.com/v1/messages?api_key=sk-abc&x=1")
        'https://example.com/v1/messages?api_key=<redacted>&x=1'
    """
    if not url:
        return url
    # Pattern 1 — telegram bot token in path. Match-before-basic-auth because
    # telegram URLs do not carry userinfo, but the catch-all embedded-token
    # pattern below already covers the bare token substring; without this
    # explicit shape the bot path would be folded into a generic sk-/ghp- mask
    # and the URL would lose its ``/bot<token>`` shape.
    url = _TELEGRAM_BOT_RE.sub(lambda _m: _m.group(0).split("/bot", 1)[0] + "/bot" + REDACTED, url)
    # Pattern 2 — basic-auth userinfo.
    url = _BASIC_AUTH_RE.sub(r"\1://\2:" + REDACTED + r"@", url)
    # Pattern 3 — known token query params. Per-key replace so non-token
    # params (``x=1``, ``stream=true``) survive untouched (test 6 contract).
    url = _QUERY_TOKEN_RE.sub(lambda m: f"{m.group(1)}={REDACTED}", url)
    # Pattern 4 — Bearer/Basic credentials (header-shaped; URL-safe because URLs
    # do not embed them, but a query string carrying one is still scrubbed).
    url = _BEARER_RE.sub(r"\1" + REDACTED, url)
    # Pattern 5 — embedded sk-/ghp-/eyJ substrings (catch-all, mirrors
    # ``redact_cli_argv`` so behaviour stays consistent across surfaces).
    return _EMBEDDED_TOKEN_RE.sub(REDACTED, url)


def redact_tool_payload(payload: Any) -> str:
    """Redact a tool input/output payload for safe attachment to a span (T1).

    The stringified payload is capped at :data:`TRACE_ATTRS_JSON_MAX_BYTES`
    (64 KiB UTF-8 bytes) so a large tool body cannot blow past the JSONL
    ceiling, and the result is run through :func:`redact_secrets` so embedded
    tokens (``ghp_…`` / ``sk-…`` / bearer headers) cannot leak onto the span.

    Dicts and lists are redacted **as structures** before serialisation, so a
    deny key such as ``password`` or ``token`` is matched on the key rather
    than hoped for in the resulting text. Serialising first loses that: a
    quoted key matches no text pattern and a short value clears no entropy
    threshold. The cap compares UTF-8 byte length, not Python character count.
    A slightly-over-cap payload keeps a head slice plus a visible
    ``… <truncated N bytes>`` marker rather than discarding the whole body.

    Args:
        payload: The raw input/output payload from a driver event or the MCP
            ``tools/call`` handler. May be ``str`` / ``dict`` / ``list`` /
            ``None``. ``None`` returns ``""``.

    Returns:
        str: A redacted, capped string suitable for ``gen_ai.tool.output``.

    Examples:
        >>> redact_tool_payload({"q": "hello"})
        '{"q": "hello"}'
        >>> "hunter2" in redact_tool_payload({"password": "hunter2"})
        False
        >>> redact_tool_payload("Bearer ghp_abcdefghijklmnopqrstuvwxyz1234")
        'Bearer <redacted>'
    """
    if payload is None:
        return ""
    if isinstance(payload, str):
        text = payload
    elif isinstance(payload, (dict, list)):
        # Redact the *structure*, then serialise. Serialising first destroys
        # the only signal a deny-key match has: once ``{"password": "hunter2"}``
        # is a string, the quoted key does not match the text patterns and a
        # short value clears no entropy threshold, so the secret reached
        # ``gen_ai.tool.output`` verbatim. ``redact_attrs`` above already
        # takes this order for span attributes; this path was the exception.
        # ``redact_structured_value`` recurses, so a deny key nested inside a
        # list or a sub-dict is caught too.
        redacted_payload = redact_structured_value(payload, redact_string=redact_secrets)
        try:
            text = json.dumps(redacted_payload, default=str)
        except (TypeError, ValueError):  # fmt: skip
            text = str(redacted_payload)
    elif isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
    else:
        text = str(payload)
    text = redact_secrets(text)
    encoded = text.encode("utf-8")
    if len(encoded) <= TRACE_ATTRS_JSON_MAX_BYTES:
        return text
    return _truncate_utf8_payload(text, encoded, TRACE_ATTRS_JSON_MAX_BYTES)


def _truncate_utf8_payload(text: str, encoded: bytes, max_bytes: int) -> str:
    low = 0
    high = min(max_bytes, len(encoded))
    best = ""
    while low <= high:
        mid = (low + high) // 2
        head = encoded[:mid].decode("utf-8", errors="ignore")
        truncated_bytes = len(encoded) - mid
        marker = f"… <truncated {truncated_bytes} bytes>"
        result = head + marker
        if len(result.encode("utf-8")) <= max_bytes:
            best = result
            low = mid + 1
        else:
            high = mid - 1
    if best:
        return best
    return f"… <truncated {len(encoded)} bytes>"


__all__ = [
    "DENY_KEYS",
    "REDACTED",
    "redact_attrs",
    "redact_cli_argv",
    "redact_event",
    "redact_tool_payload",
    "redact_url",
]
