"""Review-only capability contracts shared by CLI and MCP."""

from __future__ import annotations

from mergecraft.capabilities.manifest import (
    ALLOWED_CAPABILITIES,
    FORBIDDEN_CAPABILITIES,
    CapabilitiesManifest,
    capabilities_manifest,
)

__all__ = [
    "ALLOWED_CAPABILITIES",
    "FORBIDDEN_CAPABILITIES",
    "CapabilitiesManifest",
    "capabilities_manifest",
]
