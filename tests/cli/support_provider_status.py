"""Shared helpers for wave 16 — ``provider status`` roster view."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from tests.cli.support_agent_roster import (
    WORKFLOW_INDEXED_STEP,
    plain_cli_output,
    two_reviewer_config,
    write_config,
)
from tests.cli.support_provider_registry import (
    NOUS_BASE_URL,
    NOUS_TENCENT_HY3,
    format_model_slug,
    scaffold_mergecraft_home,
    scaffold_workflow_file,
    stub_mergecraft_env,
    write_provider_entry,
)

PROVIDER_STATUS_MODULE = "mergecraft.cli.provider_status"
STATUS_JSON_SCHEMA_VERSION = 1

STATUS_JSON_REQUIRED_TOP = frozenset({"schemaVersion", "reviewers"})
STATUS_SLOT_REQUIRED = frozenset({"slot", "model", "provider", "credential", "wired"})
STATUS_CREDENTIAL_REQUIRED = frozenset({"available", "looked_for"})

WORKFLOW_UNWIRED_STEP = """\
name: mergecraft
on:
  pull_request_target:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review (anthropic only)
        uses: alexhawat/mergeCraft@pre-0.0.1
        with:
          model: anthropic/claude-sonnet
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
"""

CHAIN_REVIEWER_CONFIG = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
agents:
  reviewer:
    modelChain:
      - anthropic/claude-sonnet
      - openai/gpt-5.3-codex
  reviewer2:
    role: reviewer
    after: reviewer
    modelChain:
      - openai/gpt-5.3-codex
"""


def import_provider_status() -> Any:
    try:
        return importlib.import_module(PROVIDER_STATUS_MODULE)
    except ImportError as exc:
        pytest.fail(f"{PROVIDER_STATUS_MODULE} is not implemented: {exc}")


def require_status_json_schema() -> Any:
    module = import_provider_status()
    schema = getattr(module, "STATUS_JSON_SCHEMA", None)
    if schema is None:
        pytest.fail(f"{PROVIDER_STATUS_MODULE}.STATUS_JSON_SCHEMA is not defined")
    return schema


def bootstrap_status_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    config_body: str = CHAIN_REVIEWER_CONFIG,
    workflow_body: str = WORKFLOW_INDEXED_STEP,
    cwd: Path | None = None,
) -> Path:
    """Minimal repo with roster, workflow, and provider registry."""
    root = cwd or tmp_path
    scaffold_mergecraft_home(root, config_body=config_body.strip())
    stub_mergecraft_env(monkeypatch, root)
    scaffold_workflow_file(root, workflow_body)
    monkeypatch.chdir(root)
    return root


def register_chain_providers(tmp_path: Path, invoke: Any) -> tuple[str, str]:
    anthropic = invoke(
        "provider",
        "add",
        "--label",
        "anthropic",
        "--harness",
        "claude",
        "--cwd",
        str(tmp_path),
    )
    assert anthropic.exit_code == 0, anthropic.stdout + anthropic.stderr
    openai = invoke(
        "provider",
        "add",
        "--label",
        "openai",
        "--harness",
        "codex",
        "--cwd",
        str(tmp_path),
    )
    assert openai.exit_code == 0, openai.stdout + openai.stderr
    nous = invoke(
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
        "--cwd",
        str(tmp_path),
    )
    assert nous.exit_code == 0, nous.stdout + nous.stderr
    add_model = invoke(
        "model",
        "add",
        "--provider",
        "nous",
        NOUS_TENCENT_HY3,
        "--cwd",
        str(tmp_path),
    )
    assert add_model.exit_code == 0, add_model.stdout + add_model.stderr
    return format_model_slug("anthropic", "claude-sonnet"), format_model_slug(
        "openai", "gpt-5.3-codex"
    )


def parse_status_json(payload: str) -> dict[str, Any]:
    data = json.loads(payload)
    assert isinstance(data, dict), "status --json must emit a JSON object"
    return data


def validate_status_payload(data: dict[str, Any]) -> None:
    missing_top = STATUS_JSON_REQUIRED_TOP - set(data)
    assert not missing_top, f"status JSON missing keys: {sorted(missing_top)}"
    assert data["schemaVersion"] == STATUS_JSON_SCHEMA_VERSION
    reviewers = data["reviewers"]
    assert isinstance(reviewers, list), "reviewers must be a list"
    assert reviewers, "reviewers must be a non-empty list"
    for reviewer in reviewers:
        assert isinstance(reviewer, dict)
        slots = reviewer.get("slots")
        assert isinstance(slots, list), "each reviewer needs slots list"
        assert slots, "each reviewer needs slots"
        for slot in slots:
            assert isinstance(slot, dict)
            missing_slot = STATUS_SLOT_REQUIRED - set(slot)
            assert not missing_slot, f"slot missing keys: {sorted(missing_slot)}"
            assert re.fullmatch(r"p\d+", str(slot["slot"])), slot["slot"]
            credential = slot["credential"]
            assert isinstance(credential, dict)
            missing_cred = STATUS_CREDENTIAL_REQUIRED - set(credential)
            assert not missing_cred, f"credential missing keys: {sorted(missing_cred)}"


def assert_no_secret_material(text: str, *, secrets: tuple[str, ...] = ()) -> None:
    for secret in secrets:
        assert secret not in text, "status output leaked a credential value"
    assert "sk-" not in text
    assert "sha256:" not in text.lower()
    assert "fingerprint" not in text.lower()


def snapshot_paths(repo: Path) -> dict[str, float]:
    watched = [
        repo / ".mergecraft" / "config.yaml",
        repo / ".mergecraft" / "config.local.yaml",
        repo / ".env",
        repo / ".github" / "workflows" / "mergecraft.yml",
    ]
    return {str(path): path.stat().st_mtime for path in watched if path.is_file()}


__all__ = [
    "CHAIN_REVIEWER_CONFIG",
    "PROVIDER_STATUS_MODULE",
    "STATUS_JSON_REQUIRED_TOP",
    "STATUS_JSON_SCHEMA_VERSION",
    "WORKFLOW_UNWIRED_STEP",
    "assert_no_secret_material",
    "bootstrap_status_repo",
    "import_provider_status",
    "parse_status_json",
    "plain_cli_output",
    "register_chain_providers",
    "require_status_json_schema",
    "snapshot_paths",
    "two_reviewer_config",
    "validate_status_payload",
    "write_config",
    "write_provider_entry",
]
