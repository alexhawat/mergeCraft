"""RED unit tests for ``provider migrate`` planning helpers (#483 / BF).

Pins migration planning, fingerprint redaction, config/secret split validation,
legacy precedence (D7), and Bedrock/Vertex ``cloud_chain`` suffix mapping (D10).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.cli.support_provider_registry import (
    AUTH_KIND_CLOUD_CHAIN,
    BEDROCK_LEGACY_SECRET_KEYS,
    LEGACY_API_KEY_MIGRATIONS,
    VERTEX_LEGACY_SECRET_KEYS,
    indexed_env_key,
    read_config,
    require_provider_migrate_symbols,
    scaffold_mergecraft_home,
    stub_mergecraft_env,
    write_env_pairs,
)

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_OPENAI_SECRET = "sk-openai-plan-SECRET9999"


def test_plan_migration_detects_legacy_openai_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module = require_provider_migrate_symbols()
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    write_env_pairs(tmp_path, {"OPENAI_API_KEY": _OPENAI_SECRET})

    plan = module.plan_provider_migration(
        env_path=tmp_path / ".env",
        config_path=tmp_path / ".mergecraft" / "config.yaml",
    )
    labels = {item["label"] for item in plan.providers}
    assert "openai" in labels
    assert any(
        step.get("source") == "OPENAI_API_KEY"
        for step in plan.env_writes
        if step.get("provider") == "openai"
    )


def test_plan_migration_lists_target_indexed_key_names_only(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module = require_provider_migrate_symbols()
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    write_env_pairs(tmp_path, {"NOUS_API_KEY": "nous-plan-secret-ABC"})

    plan = module.plan_provider_migration(
        env_path=tmp_path / ".env",
        config_path=tmp_path / ".mergecraft" / "config.yaml",
    )
    target_keys = {step["target"] for step in plan.env_writes}
    assert indexed_env_key(1, "API_KEY") in target_keys or any(
        key.endswith("_API_KEY") for key in target_keys
    )
    values = {step.get("value") for step in plan.env_writes}
    assert "nous-plan-secret-ABC" not in values


def test_migration_secret_fingerprint_redacts_full_value() -> None:
    module = require_provider_migrate_symbols()
    fingerprint = module.migration_secret_fingerprint(_OPENAI_SECRET)
    assert fingerprint != _OPENAI_SECRET
    assert _OPENAI_SECRET not in fingerprint
    assert "9999" in fingerprint or "…" in fingerprint or "*" in fingerprint


def test_validate_config_secret_split_flags_credential_in_yaml(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module = require_provider_migrate_symbols()
    scaffold_mergecraft_home(
        tmp_path,
        config_body=(
            "providers:\n"
            "  - label: leaked\n"
            "    harness: opencode\n"
            "    envIndex: 1\n"
            "    apiKey: should-not-live-here\n"
        ),
    )
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)

    violations = module.validate_config_secret_split(
        config_path=tmp_path / ".mergecraft" / "config.yaml",
        env_path=tmp_path / ".env",
    )
    assert violations
    joined = " ".join(violations).lower()
    assert "apikey" in joined or "credential" in joined or "secret" in joined


def test_validate_config_secret_split_flags_structure_in_env(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module = require_provider_migrate_symbols()
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    (tmp_path / ".env").write_text("harness=opencode\nLLM_PROVIDER_1=nous\n", encoding="utf-8")

    violations = module.validate_config_secret_split(
        config_path=tmp_path / ".mergecraft" / "config.yaml",
        env_path=tmp_path / ".env",
    )
    assert violations
    assert any("harness" in item.lower() for item in violations)


@pytest.mark.parametrize("legacy_key", sorted(LEGACY_API_KEY_MIGRATIONS))
def test_registry_credential_precedence_over_legacy_env(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    legacy_key: str,
) -> None:
    module = require_provider_migrate_symbols()
    provider_label, suffix = LEGACY_API_KEY_MIGRATIONS[legacy_key]
    scaffold_mergecraft_home(
        tmp_path,
        config_body=(
            f"providers:\n  - label: {provider_label}\n    harness: opencode\n    envIndex: 1\n"
        ),
    )
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    registry_value = f"registry-{provider_label}-WINS"
    legacy_value = f"legacy-{provider_label}-LOSES"
    write_env_pairs(
        tmp_path,
        {
            "LLM_PROVIDER_1": provider_label,
            indexed_env_key(1, suffix): registry_value,
            legacy_key: legacy_value,
        },
    )

    entry = read_config(tmp_path)["providers"][0]
    resolved = module.resolve_indexed_credential(entry)
    assert resolved == registry_value


def test_cloud_chain_migration_bedrock_suffixes_under_one_index(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module = require_provider_migrate_symbols()
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    write_env_pairs(
        tmp_path,
        {
            "AWS_ACCESS_KEY_ID": "AKIA-BEDROCK",
            "AWS_SECRET_ACCESS_KEY": "bedrock-secret",
        },
    )

    plan = module.plan_provider_migration(
        env_path=tmp_path / ".env",
        config_path=tmp_path / ".mergecraft" / "config.yaml",
    )
    bedrock = next(item for item in plan.providers if item["label"] == "bedrock")
    assert bedrock.get("authKind") == AUTH_KIND_CLOUD_CHAIN
    env_index = int(bedrock["envIndex"])
    targets = {step["target"] for step in plan.env_writes if step.get("provider") == "bedrock"}
    for suffix in BEDROCK_LEGACY_SECRET_KEYS:
        assert indexed_env_key(env_index, suffix) in targets


def test_cloud_chain_migration_vertex_suffixes_under_one_index(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module = require_provider_migrate_symbols()
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    write_env_pairs(
        tmp_path,
        {"GOOGLE_APPLICATION_CREDENTIALS": "/etc/vertex/sa.json"},
    )

    plan = module.plan_provider_migration(
        env_path=tmp_path / ".env",
        config_path=tmp_path / ".mergecraft" / "config.yaml",
    )
    vertex = next(item for item in plan.providers if item["label"] == "vertex")
    env_index = int(vertex["envIndex"])
    targets = {step["target"] for step in plan.env_writes if step.get("provider") == "vertex"}
    for suffix in VERTEX_LEGACY_SECRET_KEYS:
        assert indexed_env_key(env_index, suffix) in targets


def test_apply_provider_migration_is_idempotent(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    module = require_provider_migrate_symbols()
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    write_env_pairs(tmp_path, {"DEEPSEEK_API_KEY": "deepseek-apply-key"})

    env_path = tmp_path / ".env"
    config_path = tmp_path / ".mergecraft" / "config.yaml"
    plan = module.plan_provider_migration(env_path=env_path, config_path=config_path)
    module.apply_provider_migration(plan, env_path=env_path, config_path=config_path)
    after_first = env_path.read_text(encoding="utf-8")

    second_plan = module.plan_provider_migration(env_path=env_path, config_path=config_path)
    assert not second_plan.env_writes
    assert not second_plan.providers
    module.apply_provider_migration(second_plan, env_path=env_path, config_path=config_path)
    assert env_path.read_text(encoding="utf-8") == after_first
