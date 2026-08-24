"""Operator provider registry helpers (#477 / BA)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from mergecraft.utils import agent_resolve as ar

BUILTIN_HARNESS_DEFAULTS: dict[str, str] = {
    "openai": "codex",
    "anthropic": "claude",
    "google": "gemini",
    "cursor": "cursor",
}

_CLOUD_CHAIN_LABELS = frozenset({"bedrock", "vertex"})

# Alias — single predicate for harness/provider validity (D5).
harness_supports_provider = ar._harness_supports_provider


@dataclass(frozen=True, slots=True)
class HarnessRow:
    """One supported agent harness row for ``provider harnesses``."""

    name: str
    description: str


def _harness_rows() -> tuple[HarnessRow, ...]:
    """Build harness metadata from the agent-resolve tables (no doc literals)."""
    native = ar._NATIVE_HARNESS_PROVIDERS
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


def allocate_env_index(entries: Sequence[Mapping[str, Any]]) -> int:
    """Return ``max(existing envIndex) + 1``, or ``1`` when empty (D3).

    Gaps are preserved — freed indices are never recycled.
    """
    indices = [
        int(entry["envIndex"])
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("envIndex") is not None
    ]
    if not indices:
        return 1
    return max(indices) + 1


def validate_http_url(url: str) -> str:
    """Require an absolute ``http`` or ``https`` URL (reuses gateway urlparse rule)."""
    stripped = url.strip()
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
    if label in _CLOUD_CHAIN_LABELS:
        return "cloud_chain"
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
