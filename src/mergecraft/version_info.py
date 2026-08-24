"""Version display helpers for CLI and telemetry (#473 / Thermos F17)."""

from __future__ import annotations

from typing import Any


def short_commit(commit: str | None) -> str | None:
    """Return the seven-character short SHA prefix, or ``None`` when unknown."""
    if commit is None:
        return None
    trimmed = commit.strip()
    if not trimmed:
        return None
    return trimmed[:7]


def format_version_display(version: str, commit: str | None) -> str:
    """Render ``<version> (<short-sha>)`` when commit is known; else ``version`` alone."""
    short = short_commit(commit)
    if short is None:
        return version
    return f"{version} ({short})"


def version_json_payload(version: str, commit: str | None) -> dict[str, Any]:
    """Machine-readable version document (``schema_version`` added by the CLI envelope)."""
    return {
        "version": version,
        "commit": short_commit(commit),
    }


__all__ = [
    "format_version_display",
    "short_commit",
    "version_json_payload",
]
