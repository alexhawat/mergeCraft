"""Review-only capability manifest — shared by CLI and MCP (#350 / D10)."""

from __future__ import annotations

from typing import Final, TypedDict

from mergecraft.modes import _MODE_DEFS

ALLOWED_CAPABILITIES: Final[tuple[str, ...]] = (
    "identify",
    "investigate",
    "verify",
    "explain",
    "prioritize",
    "suggest",
)
FORBIDDEN_CAPABILITIES: Final[tuple[str, ...]] = (
    "edit_source",
    "apply_fixes",
    "commit",
    "push",
    "open_code_changing_pr",
)


class CapabilitiesManifest(TypedDict):
    """Machine-readable review-only capability contract (no ``schema_version``)."""

    review_only: bool
    modes: list[str]
    allowed: list[str]
    forbidden: list[str]


def capabilities_manifest() -> CapabilitiesManifest:
    """Return the review-only capability manifest.

    JSON callers inherit ``schema_version`` from the global ``--format json``
    envelope; this payload must not include it.
    """
    return {
        "review_only": True,
        "modes": [name for name, _, _ in _MODE_DEFS],
        "allowed": list(ALLOWED_CAPABILITIES),
        "forbidden": list(FORBIDDEN_CAPABILITIES),
    }


__all__ = [
    "ALLOWED_CAPABILITIES",
    "FORBIDDEN_CAPABILITIES",
    "CapabilitiesManifest",
    "capabilities_manifest",
]
