"""Operator provider registry helpers (#477 / BA)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from mergecraft.agents.resolution.runtime import (
    NATIVE_HARNESS_PROVIDERS,
)
from mergecraft.agents.resolution.runtime import (
    harness_supports_provider as harness_supports_provider,
)

BUILTIN_HARNESS_DEFAULTS: dict[str, str] = {
    "openai": "codex",
    "anthropic": "claude",
    "google": "gemini",
    "cursor": "cursor",
}

_CLOUD_CHAIN_LABELS = frozenset({"bedrock", "vertex"})
_DEVICE_CODE_LABELS = frozenset({"openai", "codex"})
_OAUTH_LABELS = frozenset({"anthropic", "claude"})
_OPENCODE_ZEN_LABELS = frozenset({"opencode"})


@dataclass(frozen=True, slots=True)
class HarnessRow:
    """One supported agent harness row for ``provider harnesses``."""

    name: str
    description: str


def _harness_rows() -> tuple[HarnessRow, ...]:
    """Build harness metadata from the agent-resolve tables (no doc literals)."""
    native = NATIVE_HARNESS_PROVIDERS
    return (
        HarnessRow(
            "opencode",
            "any OpenAI-compatible endpoint (generic multi-provider harness)",
        ),
        HarnessRow("codex", f"OpenAI / Codex CLI ({', '.join(sorted(native['codex']))})"),
        HarnessRow("claude", f"Anthropic / Claude CLI ({', '.join(sorted(native['claude']))})"),
        HarnessRow("gemini", f"Google / Gemini CLI ({', '.join(sorted(native['gemini']))})"),
        HarnessRow("cursor", f"Cursor CLI ({', '.join(sorted(native['cursor']))})"),
    )


def list_supported_harnesses() -> Sequence[HarnessRow]:
    """Return harness rows generated from code (D4 / issue #477)."""
    return _harness_rows()


def supported_harness_names() -> frozenset[str]:
    """Closed set of harness names accepted by ``provider add``."""
    return frozenset(row.name for row in _harness_rows())


def allocate_env_index(
    entries: Sequence[Mapping[str, Any]],
    *,
    high_water: int = 0,
    occupied: Iterable[int] = (),
) -> int:
    """Return one past the highest env index ever used, or ``1`` when none was (D3).

    Gaps are preserved — freed indices are never recycled. The live entries alone
    cannot show that: ``provider delete`` removes an entry's row, so the registry
    also records the highest freed index as ``high_water``. ``occupied`` names
    indices whose ``LLM_PROVIDER_<N>`` keys are still in the local ``.env``, which
    covers registries written before that mark existed.
    """
    indices = [
        int(entry["envIndex"])
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("envIndex") is not None
    ]
    return max([0, high_water, *indices, *occupied]) + 1


def validate_http_url(url: str) -> str:
    """Require an absolute ``http`` or ``https`` URL (reuses gateway urlparse rule).

    Interior control characters are rejected: ``strip()`` only clears the ends,
    and a stored URL is written verbatim into workflow YAML, so an embedded
    newline would open a new key or step there.
    """
    stripped = url.strip()
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in stripped):
        msg = "url must not contain whitespace or control characters"
        raise ValueError(msg)
    parsed = urlparse(stripped)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = "url must be an absolute http(s) URL"
        raise ValueError(msg)
    return stripped


def default_harness_for_label(label: str) -> str | None:
    """Return the built-in default harness for *label*, or ``None`` when required."""
    return BUILTIN_HARNESS_DEFAULTS.get(label)


def default_auth_kind_for_label(label: str) -> str | None:
    """Return the default ``authKind`` for a seeded built-in catalog label."""
    lowered = label.strip().lower()
    if lowered in _CLOUD_CHAIN_LABELS:
        return "cloud_chain"
    if lowered in _DEVICE_CODE_LABELS:
        return "device_code"
    if lowered in _OAUTH_LABELS:
        return "oauth"
    if lowered in _OPENCODE_ZEN_LABELS:
        return "opencode_zen"
    return "api_key"


__all__ = [
    "BUILTIN_HARNESS_DEFAULTS",
    "HarnessRow",
    "allocate_env_index",
    "default_auth_kind_for_label",
    "default_harness_for_label",
    "harness_supports_provider",
    "list_supported_harnesses",
    "supported_harness_names",
    "validate_http_url",
]
