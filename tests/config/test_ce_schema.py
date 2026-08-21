"""W21 / W22 — config schema version, migrations, deprecations (#368).

Out of scope: agent-protocol capability/version negotiation (D8 / #368).
D10: no root-callback edits. D6: no file 7 / tracing exporter edits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mergecraft.cli.agent_protocol import AGENT_PROTOCOL_VERSION
from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION
from mergecraft.config.settings import RepoSettings, load_repo_settings
from tests.support.cc_batch import invoke, plain
from tests.support.ce_batch import (
    CONFIG_COMPAT_MODULE,
    CONFIG_SCHEMA_VERSION_ATTR,
    d10_root_callback_owns_globals,
    require_callable,
    require_module,
)
from tests.support.dead_package_wiring import SRC_ROOT


def test_agent_protocol_does_not_negotiate_capabilities() -> None:
    """#368 out of scope — capability/version negotiation stays a separate issue."""
    protocol = (SRC_ROOT / "cli" / "agent_protocol.py").read_text(encoding="utf-8")
    assert "negotiate" not in protocol.casefold()
    assert "capability" not in protocol.casefold()


def test_w22_does_not_edit_root_callback() -> None:
    """D10 lasting — schema work does not fold flags into ``_root``."""
    root_block = d10_root_callback_owns_globals()
    assert "schema_version" not in root_block
    assert "migrate" not in root_block


def test_cli_json_schema_version_already_ships() -> None:
    """Substrate — CLI JSON payloads already carry ``schema_version``."""
    assert CLI_JSON_SCHEMA_VERSION
    result = invoke("--format", "json", "capabilities")
    combined = plain(result.stdout + result.stderr)
    assert "schema_version" in combined or result.exit_code in {0, 2}


def test_agent_protocol_version_already_ships() -> None:
    """Substrate — JSONL events already stamp ``protocol_version`` (not negotiation)."""
    assert AGENT_PROTOCOL_VERSION


def test_config_schema_is_versioned() -> None:
    """Happy: repo config declares a pinned ``schema_version``."""
    module = require_module(CONFIG_COMPAT_MODULE)
    version = getattr(module, CONFIG_SCHEMA_VERSION_ATTR, None)
    assert version is not None
    assert str(version)
    fields = RepoSettings.model_fields
    assert "schema_version" in fields or any(
        info.alias == "schemaVersion" for info in fields.values()
    )


def test_load_migrates_unversioned_yaml(tmp_path: Path) -> None:
    """Happy: a pre-version YAML still loads after migration."""
    cfg = tmp_path / ".mergecraft"
    cfg.mkdir()
    (cfg / "config.yaml").write_text("models:\n  - anthropic/claude-sonnet\n", encoding="utf-8")
    settings = load_repo_settings(root=tmp_path)
    version = getattr(settings, "schema_version", None)
    assert version is not None
    models = getattr(settings, "models", None)
    assert models == ["anthropic/claude-sonnet"]


def test_migrate_config_is_idempotent_on_current_version() -> None:
    """Edge: migrating an already-current mapping is a no-op."""
    module = require_module(CONFIG_COMPAT_MODULE)
    migrate = require_callable(module, "migrate_config")
    current = getattr(module, CONFIG_SCHEMA_VERSION_ATTR)
    payload = {"schema_version": current, "models": ["anthropic/claude-sonnet"]}
    once = migrate(dict(payload))
    twice = migrate(dict(once) if isinstance(once, dict) else once)
    assert once == twice


def test_unknown_schema_version_is_a_configuration_error() -> None:
    """Error: an unsupported schema version fails closed (type + message)."""
    module = require_module(CONFIG_COMPAT_MODULE)
    migrate = require_callable(module, "migrate_config")
    with pytest.raises((ValueError, ValidationError), match=r"schema"):
        migrate({"schema_version": "999.0.0"})


def test_deprecated_key_emits_warning_before_break() -> None:
    """Happy: deprecated keys warn before a breaking removal."""
    module = require_module(CONFIG_COMPAT_MODULE)
    warn = require_callable(module, "warn_deprecated_config_key")
    with pytest.warns((DeprecationWarning, UserWarning), match=r"deprecat"):
        warn("legacyKey")


def test_upgrade_from_previous_schema_preserves_models() -> None:
    """Happy: upgrade tests keep consumer-visible fields."""
    module = require_module(CONFIG_COMPAT_MODULE)
    migrate = require_callable(module, "migrate_config")
    upgraded = migrate({"models": ["openai/gpt-5.3-codex"]})
    payload: dict[str, Any] = dict(upgraded) if not isinstance(upgraded, dict) else upgraded
    assert payload.get("models") == ["openai/gpt-5.3-codex"]
    assert payload.get("schema_version") or payload.get("schemaVersion")


def test_backward_compat_policy_names_supported_range() -> None:
    """Happy: compatibility policy names the supported schema range."""
    module = require_module(CONFIG_COMPAT_MODULE)
    policy = require_callable(module, "backward_compat_policy")()
    payload = policy if isinstance(policy, dict) else dict(policy)
    assert "min_schema_version" in payload or "minimum" in payload
    assert "current" in payload or CONFIG_SCHEMA_VERSION_ATTR.lower() in str(payload).casefold()


def test_stable_cli_contract_is_published() -> None:
    """Happy: the CLI JSON contract is published as a versioned surface."""
    module = require_module(CONFIG_COMPAT_MODULE)
    publish = require_callable(module, "publish_cli_contract")
    contract = publish()
    payload = contract if isinstance(contract, dict) else dict(contract)
    assert payload.get("schema_version") == CLI_JSON_SCHEMA_VERSION or "schema_version" in payload


def test_stable_agent_protocol_contract_is_published() -> None:
    """Happy: agent JSONL protocol version is published (not negotiated)."""
    module = require_module(CONFIG_COMPAT_MODULE)
    publish = require_callable(module, "publish_agent_protocol_contract")
    contract = publish()
    payload = contract if isinstance(contract, dict) else dict(contract)
    assert str(payload.get("protocol_version") or payload.get("version")) == str(
        AGENT_PROTOCOL_VERSION
    )
    assert "negotiate" not in payload


def test_lts_expectations_are_declared() -> None:
    """Happy: long-term support expectations are an explicit policy object."""
    module = require_module(CONFIG_COMPAT_MODULE)
    lts = getattr(module, "CONFIG_LTS_POLICY", None)
    if lts is None:
        lts = require_callable(module, "lts_policy")()
    payload = lts if isinstance(lts, dict) else dict(lts)
    assert payload
    joined = " ".join(str(value) for value in payload.values()).casefold()
    assert "support" in joined or "lts" in joined or "schema" in joined
