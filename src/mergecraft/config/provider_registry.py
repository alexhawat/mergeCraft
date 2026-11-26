"""Operator provider registry helpers (#477 / BA)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from pydantic import TypeAdapter, ValidationError

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

# Reads a row's ``envIndex`` exactly as ``ProviderRegistryEntry`` validates one.
_ENTRY_ENV_INDEX: TypeAdapter[int] = TypeAdapter(int)


class InvalidEnvIndexError(ValueError):
    """A provider registry row whose ``envIndex`` the settings model rejects (#1592)."""


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


def entry_env_index(entry: Mapping[str, Any]) -> int:
    """Return *entry*'s ``envIndex``, parsed as ``RepoSettings`` parses it.

    Args:
        entry: One raw ``providers:`` row from ``.mergecraft/config.yaml``.

    Returns:
        int: The row's env index.

    Raises:
        InvalidEnvIndexError: When the value is missing or not an integer. The
            message names the provider and the ``envIndex`` field.
    """
    raw = entry.get("envIndex")
    try:
        return _ENTRY_ENV_INDEX.validate_python(raw)
    except ValidationError:
        label = str(entry.get("label") or "").strip()
        who = f"provider {label!r}" if label else "a provider row"
        problem = "has no envIndex" if raw is None else f"has an invalid envIndex {raw!r}"
        msg = (
            f"{who} {problem} in the providers registry: envIndex must be an integer; "
            "correct the row or remove it with `mergecraft provider delete`"
        )
        raise InvalidEnvIndexError(msg) from None


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

    Every row is validated, as ``ProviderRegistryEntry`` validates it: a row
    whose ``envIndex`` is missing or ``null`` is as invalid as a nonnumeric one,
    so allocation never writes a new row into a registry settings would reject.

    Raises:
        InvalidEnvIndexError: When a row's ``envIndex`` is missing or not an integer.
    """
    indices = [entry_env_index(entry) for entry in entries if isinstance(entry, Mapping)]
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
    "InvalidEnvIndexError",
    "allocate_env_index",
    "default_auth_kind_for_label",
    "default_harness_for_label",
    "entry_env_index",
    "harness_supports_provider",
    "list_supported_harnesses",
    "supported_harness_names",
    "validate_http_url",
]
