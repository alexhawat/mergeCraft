"""RED unit tests for the workflow YAML surgical mutator (#484 / BG).

Pins owned-key surgery on ``with:``/``env:`` blocks inside ``uses:
alexhawat/mergeCraft`` steps — byte-stable comments, parse-verify loop, refusal
when the target step is missing, and no edits to timeout literals (#465) or
header comment regions (#486).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import yaml
from tests.cli.support_provider_registry import (
    NOUS_BASE_URL,
    WORKFLOW_ONE_STEP_TEMPLATE,
    WORKFLOW_OWNED_ENV_PREFIXES,
    WORKFLOW_OWNED_WITH_KEYS,
    WORKFLOW_TWO_STEP_TEMPLATE,
    assert_only_owned_workflow_keys_changed,
    format_model_slug,
    indexed_custom_provider_api_key,
    indexed_custom_provider_base_url,
    require_workflow_wf_yaml_symbols,
)

if TYPE_CHECKING:
    from pathlib import Path


def _write_workflow(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Owned-key constants
# ---------------------------------------------------------------------------


def test_workflow_owned_key_constants_match_registry_contract() -> None:
    module = require_workflow_wf_yaml_symbols()
    assert tuple(module.WORKFLOW_OWNED_WITH_KEYS) == WORKFLOW_OWNED_WITH_KEYS
    assert tuple(module.WORKFLOW_OWNED_ENV_PREFIXES) == WORKFLOW_OWNED_ENV_PREFIXES


# ---------------------------------------------------------------------------
# Provider env wiring
# ---------------------------------------------------------------------------


def test_apply_provider_env_wiring_writes_indexed_custom_provider_keys(tmp_path: Path) -> None:
    module = require_workflow_wf_yaml_symbols()
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, WORKFLOW_ONE_STEP_TEMPLATE)

    change = module.apply_provider_env_wiring(
        workflow_path=workflow,
        env_index=1,
        label="nous",
        base_url=NOUS_BASE_URL,
        secret_name="LLM_PROVIDER_1_API_KEY",
        step_selector="primary",
        force=False,
    )
    assert change.was_modified
    new = change.new_text
    assert indexed_custom_provider_base_url(1) in new
    assert indexed_custom_provider_api_key(1) in new
    assert NOUS_BASE_URL in new
    assert "${{ secrets.LLM_PROVIDER_1_API_KEY }}" in new
    parsed = yaml.safe_load(new)
    env_map = parsed["jobs"]["review"]["steps"][0]["env"]
    assert env_map[indexed_custom_provider_base_url(1)] == NOUS_BASE_URL


def test_apply_provider_env_wiring_is_idempotent(tmp_path: Path) -> None:
    module = require_workflow_wf_yaml_symbols()
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, WORKFLOW_ONE_STEP_TEMPLATE)

    first = module.apply_provider_env_wiring(
        workflow_path=workflow,
        env_index=1,
        label="nous",
        base_url=NOUS_BASE_URL,
        secret_name="LLM_PROVIDER_1_API_KEY",
        step_selector="primary",
        force=False,
    )
    workflow.write_text(first.new_text, encoding="utf-8")
    second = module.apply_provider_env_wiring(
        workflow_path=workflow,
        env_index=1,
        label="nous",
        base_url=NOUS_BASE_URL,
        secret_name="LLM_PROVIDER_1_API_KEY",
        step_selector="primary",
        force=False,
    )
    assert not second.was_modified


def test_apply_provider_env_wiring_preserves_surrounding_comments(tmp_path: Path) -> None:
    module = require_workflow_wf_yaml_symbols()
    workflow_text = """\
name: mergecraft
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft review
        # === DO NOT TOUCH THIS COMMENT ===
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@5b9ded9ff3a27090f5c6d3cf722b2452596360bd
        with:
          prompt: x
          timeout: ${{ env.MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES }}m
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
      # === END PRECIOUS HEADER ===
"""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, workflow_text)
    before = workflow.read_text(encoding="utf-8")

    change = module.apply_provider_env_wiring(
        workflow_path=workflow,
        env_index=1,
        label="nous",
        base_url=NOUS_BASE_URL,
        secret_name="LLM_PROVIDER_1_API_KEY",
        step_selector="primary",
        force=False,
    )
    after = change.new_text
    assert "=== DO NOT TOUCH THIS COMMENT ===" in after
    assert "=== END PRECIOUS HEADER ===" in after
    assert "${{ env.MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES }}m" in after
    assert_only_owned_workflow_keys_changed(before, after)


def test_apply_provider_env_wiring_raises_when_no_mergecraft_step(tmp_path: Path) -> None:
    module = require_workflow_wf_yaml_symbols()
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(
        workflow,
        """\
name: other
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
""",
    )
    with pytest.raises(module.WorkflowYamlError) as exc:
        module.apply_provider_env_wiring(
            workflow_path=workflow,
            env_index=1,
            label="nous",
            base_url=NOUS_BASE_URL,
            secret_name="LLM_PROVIDER_1_API_KEY",
            step_selector="primary",
            force=False,
        )
    assert "mergeCraft" in str(exc.value) or "uses:" in str(exc.value)


# ---------------------------------------------------------------------------
# Model ``with:`` wiring
# ---------------------------------------------------------------------------


def test_apply_model_wiring_updates_with_model_key(tmp_path: Path) -> None:
    module = require_workflow_wf_yaml_symbols()
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, WORKFLOW_ONE_STEP_TEMPLATE)
    slug = format_model_slug("nous", "tencent/hy3")

    change = module.apply_model_wiring(
        workflow_path=workflow,
        model_slug=slug,
        step_selector="primary",
        force=False,
    )
    assert change.was_modified
    parsed = yaml.safe_load(change.new_text)
    assert parsed["jobs"]["review"]["steps"][0]["with"]["model"] == slug


def test_apply_model_wiring_step_selector_targets_named_step(tmp_path: Path) -> None:
    module = require_workflow_wf_yaml_symbols()
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, WORKFLOW_TWO_STEP_TEMPLATE)

    change = module.apply_model_wiring(
        workflow_path=workflow,
        model_slug="openai/gpt-codex",
        step_selector="mergecraft_codex",
        force=False,
    )
    parsed = yaml.safe_load(change.new_text)
    codex = next(
        step for step in parsed["jobs"]["review"]["steps"] if step.get("id") == "mergecraft_codex"
    )
    nous = next(
        step for step in parsed["jobs"]["review"]["steps"] if step.get("id") == "mergecraft_nous"
    )
    assert codex["with"]["model"] == "openai/gpt-codex"
    assert nous["with"]["model"] == "nous/tencent/hy3"


def test_apply_model_wiring_rejects_invalid_secret_name(tmp_path: Path) -> None:
    module = require_workflow_wf_yaml_symbols()
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, WORKFLOW_ONE_STEP_TEMPLATE)

    with pytest.raises(module.WorkflowYamlError) as exc:
        module.apply_provider_env_wiring(
            workflow_path=workflow,
            env_index=1,
            label="nous",
            base_url=NOUS_BASE_URL,
            secret_name="LLM_PROVIDER_1_API_KEY; rm -rf /",
            step_selector="primary",
            force=False,
        )
    assert "invalid" in str(exc.value).lower() or "secret" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# Diff rendering
# ---------------------------------------------------------------------------


def test_render_workflow_diff_emits_unified_diff(tmp_path: Path) -> None:
    module = require_workflow_wf_yaml_symbols()
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, WORKFLOW_ONE_STEP_TEMPLATE)

    change = module.apply_provider_env_wiring(
        workflow_path=workflow,
        env_index=1,
        label="nous",
        base_url=NOUS_BASE_URL,
        secret_name="LLM_PROVIDER_1_API_KEY",
        step_selector="primary",
        force=False,
    )
    diff = module.render_workflow_diff(workflow, change)
    assert "---" in diff
    assert "+++" in diff
    assert indexed_custom_provider_api_key(1) in diff or NOUS_BASE_URL in diff
