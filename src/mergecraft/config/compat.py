"""Config schema version, migrations, deprecations, and published contracts (#368).

Unversioned ``.mergecraft/config.yaml`` files migrate to ``CONFIG_SCHEMA_VERSION``
on load. Unknown versions fail closed. Capability/version negotiation for the
agent protocol is out of scope (D8 / #368).

Exports:
    CONFIG_LTS_POLICY: Long-term support expectations for the config schema.
    CONFIG_SCHEMA_VERSION: Current repo-config schema version.
    MIN_SCHEMA_VERSION: Oldest versioned schema this release accepts after migrate.
    backward_compat_policy: Named supported schema range.
    lts_policy: Copy of ``CONFIG_LTS_POLICY``.
    migrate_config: Upgrade a raw config mapping to the current schema.
    publish_agent_protocol_contract: Versioned agent JSONL contract (not negotiated).
    publish_cli_contract: Versioned CLI JSON contract.
    warn_deprecated_config_key: Warn before a breaking key removal.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import Any, Final, TypedDict

CONFIG_SCHEMA_VERSION: Final[str] = "1.0.0"
MIN_SCHEMA_VERSION: Final[str] = "1.0.0"


class BackwardCompatPolicy(TypedDict):
    """Supported schema range for repo config."""

    min_schema_version: str
    current: str


class LtsPolicy(TypedDict):
    """Long-term support expectations for the config schema."""

    support: str
    lts: str
    schema: str


class CliContract(TypedDict):
    """Published CLI JSON envelope version."""

    schema_version: str
    surface: str


class AgentProtocolContract(TypedDict):
    """Published agent JSONL protocol version (no capability negotiation)."""

    protocol_version: str
    surface: str


CONFIG_LTS_POLICY: Final[LtsPolicy] = {
    "support": "the current schema version is supported for the 0.x series",
    "lts": "unversioned pre-1.0 configs migrate to 1.0.0 on load",
    "schema": CONFIG_SCHEMA_VERSION,
}

_SUPPORTED_VERSIONS: Final[frozenset[str]] = frozenset({CONFIG_SCHEMA_VERSION})


def _declared_schema_version(payload: Mapping[str, Any]) -> str | None:
    if "schema_version" in payload:
        raw = payload["schema_version"]
    elif "schemaVersion" in payload:
        raw = payload["schemaVersion"]
    else:
        return None
    if raw is None:
        return None
    return str(raw)


def migrate_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Upgrade a raw config mapping to ``CONFIG_SCHEMA_VERSION``.

    Args:
        payload: Parsed YAML mapping (may omit ``schema_version``).

    Returns:
        A new mapping with ``schema_version`` set to the current pin.

    Raises:
        TypeError: If ``payload`` is not a mapping.
        ValueError: If the declared schema version is unsupported.
    """
    if not isinstance(payload, Mapping):
        msg = f"config schema must be a mapping, got {type(payload).__name__}"
        raise TypeError(msg)
    out = dict(payload)
    version = _declared_schema_version(out)
    if version is None:
        out["schema_version"] = CONFIG_SCHEMA_VERSION
        return out
    if version in _SUPPORTED_VERSIONS:
        out["schema_version"] = version
        return out
    msg = f"unsupported config schema version {version!r} (current {CONFIG_SCHEMA_VERSION})"
    raise ValueError(msg)


def warn_deprecated_config_key(key: str) -> None:
    """Emit a deprecation warning for a config key that will be removed.

    Args:
        key: The consumer-facing key name.
    """
    warnings.warn(
        f"config key {key!r} is deprecated and will be removed in a future schema",
        DeprecationWarning,
        stacklevel=2,
    )


def backward_compat_policy() -> BackwardCompatPolicy:
    """Return the supported schema range for this release."""
    return {
        "min_schema_version": MIN_SCHEMA_VERSION,
        "current": CONFIG_SCHEMA_VERSION,
    }


def lts_policy() -> LtsPolicy:
    """Return long-term support expectations for the config schema."""
    return CONFIG_LTS_POLICY


def publish_cli_contract() -> CliContract:
    """Publish the stable CLI JSON contract version."""
    from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION

    return {
        "schema_version": CLI_JSON_SCHEMA_VERSION,
        "surface": "cli-json",
    }


def publish_agent_protocol_contract() -> AgentProtocolContract:
    """Publish the agent JSONL protocol version without capability negotiation."""
    from mergecraft.cli.agent_protocol import AGENT_PROTOCOL_VERSION

    return {
        "protocol_version": AGENT_PROTOCOL_VERSION,
        "surface": "agent-jsonl",
    }


__all__ = [
    "CONFIG_LTS_POLICY",
    "CONFIG_SCHEMA_VERSION",
    "MIN_SCHEMA_VERSION",
    "backward_compat_policy",
    "lts_policy",
    "migrate_config",
    "publish_agent_protocol_contract",
    "publish_cli_contract",
    "warn_deprecated_config_key",
]
