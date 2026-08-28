"""RED contracts for the wire-workflow / unwire-workflow YAML mutator.

The mutator lives in :mod:`mergecraft.cli.tracing_logfire_wf_yaml` and is the
shared kernel of the two ``mergecraft tracing logfire wire-workflow`` /
``unwire-workflow`` CLI commands. These tests cover the four behaviors the
operator cares about:

1. **Idempotency**: re-running on an already-wired file is a no-op.
2. **Mismatched refuse**: an existing ``tracing-to: otel`` blocks a re-wire
   unless ``--force`` is passed.
3. **Comment preservation**: the surgery must NOT touch the rich ``#`` comment
   blocks the mergeCraft workflow carries around each step.
4. **Multi-step**: ``--step all`` wires every ``uses: alexhawat/mergeCraft``
   step in the file; ``--step primary`` only the first match.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.tracing_logfire_wf_yaml import (
    DEFAULT_WORKFLOW_RELATIVE_PATH,
    OWNED_ENV_KEYS,
    OWNED_WITH_KEYS,
    REQUIRED_ENV_KEYS,
    LogfireWorkflowError,
    apply_logfire_wiring,
    remove_logfire_wiring,
    render_workflow_diff,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures -- workflow templates
# ---------------------------------------------------------------------------


ONE_STEP_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
concurrency:
  group: mergecraft-pr-1
  cancel-in-progress: true
jobs:
  review:
    name: mergecraft review
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: ${{ steps.prompt.outputs.text }}
          timeout: 25m
          model: nous/deepseek/deepseek-v4-flash
        env:
          NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}
"""

TWO_STEP_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    name: mergecraft review
    steps:
      - name: mergeCraft PR review (Nous primary)
        id: mergecraft_nous
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: ${{ steps.prompt.outputs.text }}
          timeout: 25m
        env:
          NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}

      - name: mergeCraft PR review (Codex fallback)
        id: mergecraft_codex
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: ${{ steps.prompt.outputs.text }}
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
"""

WORKFLOW_NO_STEP = """\
name: some-other-workflow
on:
  pull_request:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
"""


def _write_workflow(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Phase 1 -- the YAML mutator (no CLI)
# ---------------------------------------------------------------------------


def test_apply_logfire_wiring_adds_four_keys_to_one_step(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    assert change.was_modified
    new = change.new_text
    for key in OWNED_WITH_KEYS:
        assert f"{key}:" in new, f"missing {key} after wiring"
    for key in REQUIRED_ENV_KEYS:
        assert f"{key}:" in new, f"missing {key} after wiring"
    # ``MERGECRAFT_TRACING_REGION`` is opt-in (``--region``): it is owned for
    # removal but must not be written by a default wire.
    assert "MERGECRAFT_TRACING_REGION" in OWNED_ENV_KEYS
    assert "MERGECRAFT_TRACING_REGION" not in REQUIRED_ENV_KEYS
    assert "MERGECRAFT_TRACING_REGION:" not in new
    # The merged YAML re-parses cleanly.
    parsed = yaml.safe_load(new)
    assert parsed["jobs"]["review"]["steps"][0]["uses"].startswith("alexhawat/mergeCraft@")
    assert parsed["jobs"]["review"]["steps"][0]["with"]["tracing"] == "true"
    assert parsed["jobs"]["review"]["steps"][0]["with"]["tracing-to"] == "logfire"
    assert (
        parsed["jobs"]["review"]["steps"][0]["with"]["logfire-token"]
        == "${{ secrets.LOGFIRE_TOKEN }}"
    )
    assert (
        parsed["jobs"]["review"]["steps"][0]["env"]["MERGECRAFT_TRACING_PROJECT"]
        == "${{ vars.LOGFIRE_PROJECT }}"
    )


def test_apply_logfire_wiring_is_idempotent(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    first = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    assert first.was_modified
    workflow.write_text(first.new_text, encoding="utf-8")
    second = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    assert not second.was_modified
    assert second.new_text == first.new_text


def test_apply_logfire_wiring_region_writes_env_key(tmp_path: Path) -> None:
    """``--region eu`` writes MERGECRAFT_TRACING_REGION so EU tokens reach the EU host."""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
        region="eu",
    )
    assert change.was_modified
    parsed = yaml.safe_load(change.new_text)
    env = parsed["jobs"]["review"]["steps"][0]["env"]
    assert env["MERGECRAFT_TRACING_REGION"] == "eu"
    assert env["MERGECRAFT_TRACING_PROJECT"] == "${{ vars.LOGFIRE_PROJECT }}"


def test_apply_logfire_wiring_region_is_normalised(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
        region="  EU  ",
    )
    parsed = yaml.safe_load(change.new_text)
    assert parsed["jobs"]["review"]["steps"][0]["env"]["MERGECRAFT_TRACING_REGION"] == "eu"


def test_apply_logfire_wiring_rejects_unknown_region(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    with pytest.raises(LogfireWorkflowError, match="region must be"):
        apply_logfire_wiring(
            workflow_path=workflow,
            secret_name="LOGFIRE_TOKEN",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="primary",
            force=False,
            region="apac",
        )


def test_apply_logfire_wiring_region_is_idempotent(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    first = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
        region="eu",
    )
    workflow.write_text(first.new_text, encoding="utf-8")
    second = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
        region="eu",
    )
    assert not second.was_modified
    assert second.new_text == first.new_text


def test_removal_strips_region_key(tmp_path: Path) -> None:
    """``MERGECRAFT_TRACING_REGION`` is owned, so unwire must strip it too."""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    wired = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
        region="eu",
    )
    workflow.write_text(wired.new_text, encoding="utf-8")
    removed = remove_logfire_wiring(workflow_path=workflow, step_selector="primary")
    assert removed.was_modified
    assert "MERGECRAFT_TRACING_REGION" not in removed.new_text


def test_apply_logfire_wiring_step_all_wires_two_steps(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, TWO_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="all",
        force=False,
    )
    assert change.was_modified
    assert len(change.affected_steps) == 2
    new = change.new_text
    # Each step's `with:` block gets a full set of three keys -> 6 total.
    assert new.count('tracing: "true"') == 2
    assert new.count("tracing-to: logfire") == 2
    assert new.count("logfire-token: ${{ secrets.LOGFIRE_TOKEN }}") == 2
    # Each step's env block gets one MERGECRAFT_TRACING_PROJECT.
    assert new.count("MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}") == 2


def test_apply_logfire_wiring_refuses_mismatched_without_force(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    body = ONE_STEP_TEMPLATE.replace("timeout: 25m", "timeout: 25m\n          tracing-to: otel")
    _write_workflow(workflow, body)
    with pytest.raises(LogfireWorkflowError) as exc:
        apply_logfire_wiring(
            workflow_path=workflow,
            secret_name="LOGFIRE_TOKEN",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="primary",
            force=False,
        )
    assert "tracing-to" in str(exc.value)
    assert "--force" in str(exc.value)


def test_apply_logfire_wiring_force_overwrites_mismatched(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    body = ONE_STEP_TEMPLATE.replace("timeout: 25m", "timeout: 25m\n          tracing-to: otel")
    _write_workflow(workflow, body)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=True,
    )
    assert change.was_modified
    parsed = yaml.safe_load(change.new_text)
    assert parsed["jobs"]["review"]["steps"][0]["with"]["tracing-to"] == "logfire"


def test_apply_logfire_wiring_raises_when_no_mergecraft_step(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, WORKFLOW_NO_STEP)
    with pytest.raises(LogfireWorkflowError) as exc:
        apply_logfire_wiring(
            workflow_path=workflow,
            secret_name="LOGFIRE_TOKEN",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="primary",
            force=False,
        )
    assert "no ``uses: alexhawat/mergeCraft`` step" in str(exc.value)


def test_apply_logfire_wiring_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(LogfireWorkflowError) as exc:
        apply_logfire_wiring(
            workflow_path=tmp_path / "does-not-exist.yml",
            secret_name="LOGFIRE_TOKEN",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="primary",
            force=False,
        )
    assert "not found" in str(exc.value)


def test_apply_logfire_wiring_rejects_invalid_secret_name(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    with pytest.raises(LogfireWorkflowError) as exc:
        apply_logfire_wiring(
            workflow_path=workflow,
            secret_name="LOGFIRE_TOKEN; rm -rf /",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="primary",
            force=False,
        )
    assert "invalid Actions secret" in str(exc.value)


def test_apply_logfire_wiring_preserves_surrounding_comments(tmp_path: Path) -> None:
    workflow_text = """\
name: mergecraft
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft review
        # === DO NOT TOUCH THIS COMMENT ===
        # IMPORTANT: cascade shape explained here.
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: x
        env:
          NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}
      # === END PRECIOUS HEADER ===
"""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, workflow_text)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    new = change.new_text
    assert "=== DO NOT TOUCH THIS COMMENT ===" in new
    assert "IMPORTANT: cascade shape explained here." in new
    assert "=== END PRECIOUS HEADER ===" in new


def test_apply_logfire_wiring_creates_env_block_when_missing(tmp_path: Path) -> None:
    workflow_text = """\
name: mergecraft
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: x
"""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, workflow_text)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    new = change.new_text
    assert "env:" in new
    assert "MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}" in new
    parsed = yaml.safe_load(new)
    env = parsed["jobs"]["review"]["steps"][0]["env"]
    assert env["MERGECRAFT_TRACING_PROJECT"] == "${{ vars.LOGFIRE_PROJECT }}"


NO_ENV_TEMPLATE = """\
name: mergecraft
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: x
"""

NO_ENV_NO_WITH_TEMPLATE = """\
name: mergecraft
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
"""


def test_region_survives_when_the_step_has_no_env_block(tmp_path: Path) -> None:
    """A created ``env:`` must carry every owned key, not just the first.

    Regression: the fallback that creates a missing ``env:`` mapping rendered
    only ``env_canonical[0]``, silently dropping MERGECRAFT_TRACING_REGION.
    ``_assert_wired_semantics`` did not catch it because it asserts only
    REQUIRED_ENV_KEYS, so the command reported success while an EU token kept
    posting to the default US endpoint.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, NO_ENV_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
        region="eu",
    )
    assert change.was_modified
    parsed = yaml.safe_load(change.new_text)
    env = parsed["jobs"]["review"]["steps"][0]["env"]
    assert env["MERGECRAFT_TRACING_REGION"] == "eu"
    assert env["MERGECRAFT_TRACING_PROJECT"] == "${{ vars.LOGFIRE_PROJECT }}"


def test_region_survives_when_the_step_has_neither_env_nor_with(tmp_path: Path) -> None:
    """The ``uses:``-anchored creation path owns the same defect shape."""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, NO_ENV_NO_WITH_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
        region="eu",
    )
    assert change.was_modified
    parsed = yaml.safe_load(change.new_text)
    step = parsed["jobs"]["review"]["steps"][0]
    assert step["env"]["MERGECRAFT_TRACING_REGION"] == "eu"
    assert step["env"]["MERGECRAFT_TRACING_PROJECT"] == "${{ vars.LOGFIRE_PROJECT }}"
    assert step["with"]["tracing-to"] == "logfire"


def test_env_less_wire_then_unwire_round_trips(tmp_path: Path) -> None:
    """A created env block must be fully strippable, region included."""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, NO_ENV_TEMPLATE)
    wired = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
        region="eu",
    )
    workflow.write_text(wired.new_text, encoding="utf-8")
    removed = remove_logfire_wiring(workflow_path=workflow, step_selector="primary")
    assert "MERGECRAFT_TRACING_REGION" not in removed.new_text
    assert "MERGECRAFT_TRACING_PROJECT" not in removed.new_text


def test_env_less_wire_is_idempotent_with_region(tmp_path: Path) -> None:
    """Re-wiring a step whose env block this command created is a no-op."""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, NO_ENV_TEMPLATE)
    first = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
        region="eu",
    )
    workflow.write_text(first.new_text, encoding="utf-8")
    second = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
        region="eu",
    )
    assert not second.was_modified
    assert second.new_text == first.new_text


# ---------------------------------------------------------------------------
# Phase 2 -- render_workflow_diff
# ---------------------------------------------------------------------------


def test_render_workflow_diff_no_modification_returns_empty(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    # Second run sees an already-wired file -> was_modified=False
    workflow.write_text(change.new_text, encoding="utf-8")
    no_op = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    assert not no_op.was_modified
    text = render_workflow_diff(workflow, no_op)
    # No-op diff is empty (only the file headers).
    body_lines = [line for line in text.splitlines() if line.startswith(("+", "-"))]
    assert body_lines == []


def test_render_workflow_diff_truncates_long_diffs(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    text = render_workflow_diff(workflow, change, max_lines=2)
    assert "truncated" in text


# ---------------------------------------------------------------------------
# Phase 3 -- remove_logfire_wiring
# ---------------------------------------------------------------------------


def test_removal_strips_four_keys_from_each_step(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, TWO_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="all",
        force=False,
    )
    workflow.write_text(change.new_text, encoding="utf-8")
    unwire = remove_logfire_wiring(workflow_path=workflow, step_selector="all")
    assert unwire.was_modified
    assert len(unwire.affected_steps) == 2
    new = unwire.new_text
    for key in OWNED_WITH_KEYS:
        assert not any(line.strip().startswith(f"{key}:") for line in new.splitlines())
    for key in OWNED_ENV_KEYS:
        assert not any(line.strip().startswith(f"{key}:") for line in new.splitlines())


def test_removal_idempotent(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, TWO_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="all",
        force=False,
    )
    workflow.write_text(change.new_text, encoding="utf-8")
    first = remove_logfire_wiring(workflow_path=workflow, step_selector="all")
    workflow.write_text(first.new_text, encoding="utf-8")
    second = remove_logfire_wiring(workflow_path=workflow, step_selector="all")
    assert not second.was_modified


def test_removal_raises_when_no_mergecraft_step(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, WORKFLOW_NO_STEP)
    with pytest.raises(LogfireWorkflowError) as exc:
        remove_logfire_wiring(workflow_path=workflow, step_selector="primary")
    assert "no ``uses: alexhawat/mergeCraft`` step" in str(exc.value)


def test_step_selector_named_id_targets_specific_step(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, TWO_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="mergecraft_codex",
        force=False,
    )
    assert change.was_modified
    assert change.affected_steps == ["mergecraft_codex"]
    new = change.new_text
    # Only the ``Codex fallback`` step got wired.
    assert new.count('tracing: "true"') == 1
    assert new.count("MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}") == 1


def test_step_selector_unknown_id_raises(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, TWO_STEP_TEMPLATE)
    with pytest.raises(LogfireWorkflowError) as exc:
        apply_logfire_wiring(
            workflow_path=workflow,
            secret_name="LOGFIRE_TOKEN",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="mergecraft_does_not_exist",
            force=False,
        )
    assert "did not match" in str(exc.value)


# ---------------------------------------------------------------------------
# Phase 4 -- the CLI surface
# ---------------------------------------------------------------------------


def test_cli_wire_workflow_default_dry_run(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    exit_code = runner.invoke(
        app,
        ["tracing", "logfire", "wire-workflow", "--workflow", str(workflow)],
    ).exit_code
    assert exit_code == 0
    body = workflow.read_text(encoding="utf-8")
    assert 'tracing: "true"' not in body
    assert "tracing-to: logfire" not in body


def test_cli_wire_workflow_apply_writes(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    exit_code = runner.invoke(
        app,
        [
            "tracing",
            "logfire",
            "wire-workflow",
            "--workflow",
            str(workflow),
            "--apply",
        ],
    ).exit_code
    assert exit_code == 0
    body = workflow.read_text(encoding="utf-8")
    assert 'tracing: "true"' in body
    assert "tracing-to: logfire" in body
    assert "MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}" in body


def test_cli_wire_workflow_rejects_invalid_secret_name(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    result = runner.invoke(
        app,
        [
            "tracing",
            "logfire",
            "wire-workflow",
            "--workflow",
            str(workflow),
            "--secret",
            "INVALID; rm -rf /",
            "--apply",
        ],
    )
    assert result.exit_code != 0
    assert "invalid" in result.output.lower() or "secret" in result.output.lower()


def test_cli_wire_workflow_force_overwrites(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    body = ONE_STEP_TEMPLATE.replace("timeout: 25m", "timeout: 25m\n          tracing-to: otel")
    _write_workflow(workflow, body)
    result = runner.invoke(
        app,
        [
            "tracing",
            "logfire",
            "wire-workflow",
            "--workflow",
            str(workflow),
            "--force",
            "--apply",
        ],
    )
    assert result.exit_code == 0
    new = workflow.read_text(encoding="utf-8")
    assert "tracing-to: logfire" in new
    assert "tracing-to: otel" not in new


def test_cli_unwire_workflow_applies_symmetrically(tmp_path: Path) -> None:
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    runner.invoke(
        app,
        ["tracing", "logfire", "wire-workflow", "--workflow", str(workflow), "--apply"],
    )
    result = runner.invoke(
        app,
        ["tracing", "logfire", "unwire-workflow", "--workflow", str(workflow), "--apply"],
    )
    assert result.exit_code == 0
    body = workflow.read_text(encoding="utf-8")
    for key in ("tracing", "tracing-to", "logfire-token", "MERGECRAFT_TRACING_PROJECT"):
        assert not any(line.strip().startswith(f"{key}:") for line in body.splitlines())


def test_cli_wire_workflow_default_path_uses_relative_default(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """The default --workflow path is ``.github/workflows/mergecraft.yml``.

    The CLI's ``--workflow`` default is ``DEFAULT_WORKFLOW_RELATIVE_PATH``,
    which is a *relative* path. The CLI resolves it against the current
    working directory at command time. Verifying that the rendered option
    default in ``--help`` matches the constant is enough -- mounting a real
    cwd is test-suite scope creep.
    """
    result = runner.invoke(
        app,
        ["tracing", "logfire", "wire-workflow", "--help"],
    )
    assert result.exit_code == 0
    assert DEFAULT_WORKFLOW_RELATIVE_PATH in result.output


# ---------------------------------------------------------------------------
# Phase 5 -- regression tests for the review comments on PR #207
# ---------------------------------------------------------------------------
#
# Three behaviors were called out by the mergeCraft self-review on the
# initial implementation. These tests pin them down so they cannot regress.
#
# 1. ``logfire_disable`` prints the "Logfire tracing disabled." completion
#    message; ``unwire-workflow`` does not (it only strips workflow keys,
#    the .env / secret clearing is the separate ``disable`` command).
# 2. Wiring a step whose ``with:`` (or ``env:``) is inline -- e.g.
#    ``with: prompt`` or ``env: {}`` -- refuses loudly instead of silently
#    leaving the step partially wired.
# 3. The post-mutation semantic check raises if a selected step's ``with:``
#    is not a mapping at all (e.g. a ``run: |`` script body whose content
#    fooled the line-based detector) or if the four owned keys are absent
#    after a successful-looking syntax pass.


_INLINE_WITH_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with: prompt
        env:
          NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}
"""


_INLINE_ENV_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: hi
        env: {}
"""


# The mutator's ``child_line_re`` requires the line to match
# ``^[ \\t]*(?P<k>[A-Za-z0-9_-]+):`` -- a colon-terminated key. A flow-style
# list ``with: [...]`` is NOT a mapping and cannot accept owned keys; the
# mutator's line-based view sees the ``with:`` line with an inline value
# (``[...]``) and the inline-block guard must refuse the wiring.
_FLOW_LIST_WITH_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with: [foo, bar]
        env:
          NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}
"""


def test_apply_logfire_wiring_raises_on_inline_with_block(tmp_path: Path) -> None:
    """A step with ``with: prompt`` (inline value) cannot accept owned keys.

    Regression for review comment 2 on PR #207: previously the mutator
    silently returned ``was_modified=False``, the CLI printed ``wrote``,
    and a subsequent re-run falsely reported ``already wired``.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, _INLINE_WITH_TEMPLATE)
    with pytest.raises(LogfireWorkflowError) as exc:
        apply_logfire_wiring(
            workflow_path=workflow,
            secret_name="LOGFIRE_TOKEN",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="primary",
            force=False,
        )
    msg = str(exc.value)
    assert "with" in msg
    assert "no children" in msg or "cannot insert" in msg
    # And the workflow on disk is untouched.
    assert workflow.read_text(encoding="utf-8") == _INLINE_WITH_TEMPLATE


def test_apply_logfire_wiring_raises_on_empty_env_block(tmp_path: Path) -> None:
    """A step with ``env: {}`` (flow-style empty mapping) cannot accept owned keys."""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, _INLINE_ENV_TEMPLATE)
    with pytest.raises(LogfireWorkflowError) as exc:
        apply_logfire_wiring(
            workflow_path=workflow,
            secret_name="LOGFIRE_TOKEN",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="primary",
            force=False,
        )
    msg = str(exc.value)
    assert "env" in msg
    assert "no children" in msg or "cannot insert" in msg


def test_post_mutation_check_catches_inline_flow_with_block(tmp_path: Path) -> None:
    """A flow-style ``with: [...]`` cannot accept owned keys.

    Regression for review comment 3 on PR #207: previously the mutator's
    line-based view of a flow-style list (``with: [foo, bar]``) saw an
    inline value, returned ``was_modified=False``, the CLI printed
    ``wrote``, and the structural assertion (which runs *after* the
    mutation) would have raised on a fully-wired file -- but in the
    pre-fix code the assertion didn't exist. With the inline-block guard
    the mutator refuses loudly up front, and ``_assert_wired_semantics``
    is the second-line defence for any future case that slips past the
    guard.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, _FLOW_LIST_WITH_TEMPLATE)
    with pytest.raises(LogfireWorkflowError) as exc:
        apply_logfire_wiring(
            workflow_path=workflow,
            secret_name="LOGFIRE_TOKEN",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="primary",
            force=False,
        )
    assert "with" in str(exc.value)
    assert workflow.read_text(encoding="utf-8") == _FLOW_LIST_WITH_TEMPLATE


def test_post_mutation_check_is_scoped_to_selected_steps(tmp_path: Path) -> None:
    """The structural assertion only flags the *selected* steps.

    With ``--step mergecraft_codex`` only the Codex fallback step is
    targeted; the sibling Nous primary step remains unwired and must not
    trigger the assertion. This protects the legitimate "wire a single
    step out of N" use case.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, TWO_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="mergecraft_codex",
        force=False,
    )
    assert change.was_modified
    assert change.affected_steps == ["mergecraft_codex"]
    # The Nous step is untouched -- and crucially, no LogfireWorkflowError
    # raised even though it is unwired.
    new = change.new_text
    assert new.count('tracing: "true"') == 1


def test_logfire_disable_prints_completion_message(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``tracing logfire disable`` prints ``Logfire tracing disabled.``.

    Regression for review comment 1 on PR #207: the completion message
    was moved into ``unwire-workflow`` by accident; restore it here.
    We stub out the env / gh-secret clearing (not what this test covers)
    so the test runs offline.
    """
    from mergecraft.cli import tracing_logfire_cmd

    # Stub the .env writer to a no-op so we don't touch real disk config.
    monkeypatch.setattr(tracing_logfire_cmd, "_write_env_value", lambda *_a, **_kw: True)
    # Stub the gh secret delete to a no-op so the test does not need gh CLI.
    monkeypatch.setattr(tracing_logfire_cmd, "_delete_gh_secret", lambda **_kw: True)
    result = runner.invoke(
        app,
        ["tracing", "logfire", "disable"],
    )
    assert result.exit_code == 0
    assert "Logfire tracing disabled." in result.output


def test_logfire_unwire_workflow_does_not_print_disabled_message(
    tmp_path: Path,
) -> None:
    """``unwire-workflow`` must NOT print the ``disable`` completion message.

    It only strips workflow keys; the .env / secret clearing is the
    separate ``disable`` command. Pair with the regression above so the
    two surfaces stay disambiguated.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, ONE_STEP_TEMPLATE)
    runner.invoke(
        app,
        ["tracing", "logfire", "wire-workflow", "--workflow", str(workflow), "--apply"],
    )
    result = runner.invoke(
        app,
        ["tracing", "logfire", "unwire-workflow", "--workflow", str(workflow), "--apply"],
    )
    assert result.exit_code == 0
    assert "Logfire tracing disabled." not in result.output


# ---------------------------------------------------------------------------
# Phase 6 -- scoped `_strip_owned_keys` (block-scalar safety) + env indent
# ---------------------------------------------------------------------------
#
# Round-2 review surfaced two non-blocking items that were elevated by
# the second reviewer to blockers; both are fixed and pinned here.
#
# 1. ``_strip_owned_keys`` used to match owned-key-shaped lines at *any*
#    indent inside the step block, so a line like ``tracing: do-not-delete``
#    inside a ``prompt: |`` / ``run: |`` block scalar would be silently
#    removed. The parsed-state assertion cannot detect that data loss
#    because block-scalar content is opaque to the YAML loader.
# 2. ``_create_env_block`` emitted the new env child at ``with_indent + 4``
#    instead of the canonical ``+2``, producing inconsistent indentation
#    in the diff. Valid YAML, cosmetic, but inconsistent for a tool whose
#    premise is minimal canonical diffs.


_RUN_BLOCK_SCALAR_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: |
            tracing: do-not-delete-this-is-script-text
            tracing-to: also-do-not-delete
            logfire-token: still-do-not-delete
          timeout: 25m
        env:
          NOUS_API_KEY: ${{ secrets.NOUS_API_KEY }}
          MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}
"""


def test_unwire_workflow_preserves_block_scalar_content(tmp_path: Path) -> None:
    """``unwire-workflow`` must not delete owned-key-shaped lines inside a block scalar.

    Regression for the second round of review on PR #207: a previous
    implementation of ``_strip_owned_keys`` matched owned-key-shaped lines
    at any indent inside the step block, so it would silently delete
    script text inside ``prompt: |`` / ``run: |`` that happened to match
    the owned-key shape. The parsed-state assertion cannot detect that
    data loss (block-scalar content is opaque to the YAML loader), so the
    scoping has to happen in the mutator itself.

    Construct a step whose ``with.prompt:`` is a block scalar containing
    ``tracing:``, ``tracing-to:``, ``logfire-token:`` lines, plus an
    ``env.MERGECRAFT_TRACING_PROJECT:`` line at the canonical child indent.
    Run ``unwire-workflow`` -- the script text must survive intact; only
    the canonical ``MERGECRAFT_TRACING_PROJECT:`` line in ``env:`` may
    be stripped.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, _RUN_BLOCK_SCALAR_TEMPLATE)
    change = remove_logfire_wiring(
        workflow_path=workflow,
        step_selector="primary",
    )
    assert change.was_modified
    new = change.new_text
    # The block-scalar script content must survive verbatim.
    assert "tracing: do-not-delete-this-is-script-text" in new
    assert "tracing-to: also-do-not-delete" in new
    assert "logfire-token: still-do-not-delete" in new
    # The canonical env child must be stripped.
    assert "MERGECRAFT_TRACING_PROJECT:" not in new
    # The other env entries survive.
    assert "NOUS_API_KEY:" in new
    # The prompt block scalar remains in the parsed structure -- the
    # wiring keys are NOT inside the parsed ``with.prompt`` string value.
    parsed = yaml.safe_load(new)
    prompt = parsed["jobs"]["review"]["steps"][0]["with"]["prompt"]
    assert isinstance(prompt, str)
    assert "tracing: do-not-delete-this-is-script-text" in prompt


def test_apply_logfire_wiring_creates_env_block_at_canonical_indent(tmp_path: Path) -> None:
    """A newly-created ``env:`` block uses the canonical ``+2`` child indent.

    Regression for the second round of review on PR #207: a previous
    implementation emitted the new ``env:`` child at ``with_indent + 4``
    spaces (two deeper than the file's canonical env-children indent),
    producing an inconsistent diff. The fix lands the child at
    ``with_indent + 2`` -- the same indent that ``env:`` uses when it
    exists from the start.

    Build a step that has a ``with:`` block but no ``env:`` block;
    apply wiring; assert the generated ``MERGECRAFT_TRACING_PROJECT``
    line is at exactly two spaces deeper than the ``env:`` key.
    """
    workflow_text = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: x
"""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, workflow_text)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    new = change.new_text
    # Find the ``env:`` key line and the ``MERGECRAFT_TRACING_PROJECT``
    # child line; the child must be exactly two spaces deeper than ``env:``.
    env_lines = [ln for ln in new.splitlines() if ln.lstrip().startswith("env:")]
    child_lines = [
        ln for ln in new.splitlines() if ln.lstrip().startswith("MERGECRAFT_TRACING_PROJECT:")
    ]
    assert env_lines, "env: block was not created"
    assert child_lines, "MERGECRAFT_TRACING_PROJECT child was not created"
    env_indent = len(env_lines[0]) - len(env_lines[0].lstrip())
    child_indent = len(child_lines[0]) - len(child_lines[0].lstrip())
    assert child_indent - env_indent == 2, (
        f"env child indent is {child_indent - env_indent}, expected 2: "
        f"env={env_lines[0]!r} child={child_lines[0]!r}"
    )


# ---------------------------------------------------------------------------
# Phase 7 -- round-3 review blockers (gpt-5.6-sol)
# ---------------------------------------------------------------------------
#
# Three correctness gaps flagged on commit ``255fcd8``. Each is closed
# and pinned here.
#
# 1. ``_find_action_steps`` truncated a step block at any ``-`` line at
#    any indent -- including a Markdown bullet inside a ``prompt: |``
#    block scalar. The truncation cut the step short of the ``tracing``
#    / ``tracing-to`` / ``logfire-token`` keys, so unwire reported no
#    modification and exited 0 while the keys remained.
# 2. ``_strip_owned_keys`` stitched ``with:`` and ``env:`` ranges in
#    fixed order regardless of byte offset, duplicating/reordering
#    chunks when ``env:`` preceded ``with:``.
# 3. ``_step_identifier``'s ``step[{n}]`` fallback and
#    ``_assert_wired_semantics``'s ``job:{job}/step:{i}`` fallback used
#    different schemes, so a nameless action step mutated by the regex
#    view was rejected by the parsed-structure check.


_PROMPT_WITH_BULLET_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: |
            Steps:
            - first bullet
            - second bullet
            - third bullet
          timeout: 25m
        env:
          MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}
"""


def test_unwire_workflow_handles_block_scalar_with_bullets(tmp_path: Path) -> None:
    """unwire-workflow must not be fooled by ``- item`` inside ``prompt: |``.

    Regression for round-3 blocker 1: ``_find_action_steps`` previously
    truncated the action block at any ``-`` line at any indent, so a
    Markdown bullet inside ``prompt: |`` cut the step short of the
    ``tracing:`` / ``tracing-to:`` / ``logfire-token:`` / ``MERGECRAFT_*
    `` keys further down. The unwire path then reported ``was_modified=
    False`` and exited 0 while the keys remained -- a silent no-op.

    The fix bounds the forward terminator to ``-`` lines at the step's
    own list indent or shallower, so block-scalar content is never
    mistaken for a sibling step marker.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, _PROMPT_WITH_BULLET_TEMPLATE)
    # First wire the step (insert the four keys at the canonical indents).
    wire_change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    assert wire_change.was_modified
    workflow.write_text(wire_change.new_text, encoding="utf-8")
    # Now unwire -- this is the path the previous bug broke.
    unwire_change = remove_logfire_wiring(
        workflow_path=workflow,
        step_selector="primary",
    )
    assert unwire_change.was_modified, "unwire must actually strip the owned keys"
    new = unwire_change.new_text
    # All four owned keys are gone.
    assert 'tracing: "true"' not in new
    assert "tracing-to: logfire" not in new
    assert "logfire-token: ${{ secrets.LOGFIRE_TOKEN }}" not in new
    assert "MERGECRAFT_TRACING_PROJECT:" not in new
    # The block-scalar bullets survive.
    assert "- first bullet" in new
    assert "- second bullet" in new
    assert "- third bullet" in new


_ENV_BEFORE_WITH_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review
        id: mergecraft_primary
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        env:
          MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}
        with:
          prompt: hi
          tracing: "true"
          tracing-to: logfire
          logfire-token: ${{ secrets.LOGFIRE_TOKEN }}
"""


def test_unwire_workflow_handles_env_before_with(tmp_path: Path) -> None:
    """unwire-workflow must handle ``env:`` preceding ``with:`` in the step.

    Regression for round-3 blocker 2: ``_strip_owned_keys`` previously
    built ``owned_ranges`` as ``[with_block, env_block]`` in fixed
    order and stitched chunks in that order. When ``env:`` appeared
    before ``with:``, the later ``with:`` range's chunks got duplicated
    / reordered; the post-check then rejected the result and a
    wire->unwire round trip on such a workflow silently broke.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, _ENV_BEFORE_WITH_TEMPLATE)
    change = remove_logfire_wiring(
        workflow_path=workflow,
        step_selector="primary",
    )
    assert change.was_modified
    new = change.new_text
    # All four owned keys are gone.
    assert 'tracing: "true"' not in new
    assert "tracing-to: logfire" not in new
    assert "logfire-token: ${{ secrets.LOGFIRE_TOKEN }}" not in new
    assert "MERGECRAFT_TRACING_PROJECT:" not in new
    # The non-owned lines survive.
    assert "prompt: hi" in new
    # The result is still valid YAML with the expected shape.
    parsed = yaml.safe_load(new)
    step = parsed["jobs"]["review"]["steps"][0]
    assert step["with"]["prompt"] == "hi"
    # The env block may parse to None (empty mapping) or {} after the
    # last owned key is stripped; either way, MERGECRAFT_TRACING_PROJECT
    # must not be present.
    env = step["env"]
    if env is not None:
        assert "MERGECRAFT_TRACING_PROJECT" not in env
    # The file order is preserved: ``env:`` still precedes ``with:``.
    env_pos = new.index("env:")
    with_pos = new.index("with:")
    assert env_pos < with_pos


_NAMELESS_STEP_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - if: ${{ always() }}
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: hi
        env:
          MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}
"""


def test_apply_logfire_wiring_handles_nameless_action_step(tmp_path: Path) -> None:
    """A nameless action step (no ``id:``, no ``name:``) is wired without a fallback mismatch.

    Regression for round-3 blocker 3: ``_step_identifier`` returned
    ``step[N]`` (file-indexed among matched action steps) for a step
    with no ``id:`` and no ``name:``, but ``_assert_wired_semantics``
    looked for ``job:{job}/step:{i}`` (job-indexed among all job
    steps). The two schemes never matched, so a successful mutation
    was rejected as ``selected step(s) not present in parsed
    workflow``.

    The fix resolves each matched step to its parsed identifier once
    (``id:`` -> ``name:`` -> ``job:{job}/step:{i}``) and uses that as
    the single source of truth across the mutator and the post-check.
    Constructed with a step that has neither ``id:`` nor ``name:``
    (only ``if:``), forcing the fallback path on both sides.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, _NAMELESS_STEP_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    assert change.was_modified
    # The matched-step identifier is the parsed fallback (job-indexed),
    # not the regex fallback. The matched step is the second step in
    # the ``review`` job (index 1 in job-step coordinates; the first
    # step is ``actions/checkout@v5`` which is *not* an action step
    # we own).
    assert change.affected_steps == ["job:review/step:1"]
    parsed = yaml.safe_load(change.new_text)
    step = parsed["jobs"]["review"]["steps"][1]
    assert step["with"]["tracing"] == "true"
    assert step["with"]["tracing-to"] == "logfire"
    assert step["with"]["logfire-token"] == "${{ secrets.LOGFIRE_TOKEN }}"
    assert step["env"]["MERGECRAFT_TRACING_PROJECT"] == "${{ vars.LOGFIRE_PROJECT }}"


# ---------------------------------------------------------------------------
# Round-4 regression coverage
# ---------------------------------------------------------------------------

# Blocker 2 (security): ``\b`` and bare ``startswith`` also match the
# canonical action name as a prefix of a fork -- ``alexhawat/mergeCraft-fork``,
# ``alexhawat/mergecraft`` (lowercased), etc. The fix requires ``@``
# immediately after the action name in both the regex and the parsed
# ``startswith`` checks. A successful wire against a fork would
# happily inject ``${{ secrets.LOGFIRE_TOKEN }}`` into a different
# action.
_FORK_SIMILAR_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: forge
        uses: alexhawat/mergeCraft-fork@deadbeef # similar repo name
        with:
          prompt: hi
      - name: lowcased
        uses: alexhawat/mergecraft@f5b070bddce40099dab77778231cac3456a55157
        with:
          prompt: hi
"""


def test_apply_logfire_wiring_rejects_similar_fork_action_uses(tmp_path: Path) -> None:
    """Wiring refuses steps whose ``uses:`` only prefix-matches the canonical action.

    Regression for round-4 blocker 2: ``\b`` in the regex and bare
    ``startswith(_ACTION_USES)`` in the parsed-view checks also match
    ``alexhawat/mergeCraft-fork`` (a different repo / potential fork)
    and ``alexhawat/mergecraft`` (lowercased; GitHub treats it as a
    different owner). Wiring such a step would silently inject
    ``${{ secrets.LOGFIRE_TOKEN }}`` into an action we don't own.
    The fix requires ``@`` immediately after the action name in both
    checks; this test asserts that ``--step all`` (which would
    otherwise sweep every match) reports zero affected steps.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, _FORK_SIMILAR_TEMPLATE)
    # No real ``uses: alexhawat/mergeCraft@vN`` step exists in the file --
    # both selectors raise the same "no matching step" error they would
    # raise for any file with zero matching action steps. The fork and
    # lowercase variants never match the canonical-action regex.
    with pytest.raises(LogfireWorkflowError, match="no ``uses: alexhawat/mergeCraft`` step found"):
        apply_logfire_wiring(
            workflow_path=workflow,
            secret_name="LOGFIRE_TOKEN",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="all",
            force=False,
        )
    with pytest.raises(LogfireWorkflowError, match="no ``uses: alexhawat/mergeCraft`` step found"):
        apply_logfire_wiring(
            workflow_path=workflow,
            secret_name="LOGFIRE_TOKEN",
            project_var_name="LOGFIRE_PROJECT",
            step_selector="primary",
            force=False,
        )


# Blocker 1 (deepseek elevated): ``_strip_owned_keys`` and
# ``_create_env_block`` hardcoded the child indent as ``key_indent + 2``,
# while ``_insert_owned_keys_into_block`` derived it from the observed
# first child. On a workflow whose ``with:``/``env:`` children live at
# a non-canonical (e.g. +4) indent, the wire would insert at the
# dynamic +4, but the unwire would only scan at the hardcoded +2 --
# leaving the wired keys in place and exiting 0 with "had no Logfire
# wiring; no changes needed". The fix derives the child indent from
# the observed first child on the strip and create-env paths too, so
# wire -> unwire round trips are symmetric on such files.
_NON_CANONICAL_INDENT_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
            prompt: hi
        env:
            MERGECRAFT_X: keep_me
"""


def test_wire_unwire_round_trip_on_non_canonical_child_indent(tmp_path: Path) -> None:
    """Wire -> unwire is symmetric on workflows using a non-canonical child indent.

    Regression for round-4 blocker 1: the strip / create-env paths
    used a hardcoded ``key_indent + 2`` while the insert path derived
    the indent from the observed first child. On a 4-space-indented
    workflow the wire wrote the keys at ``+4`` but the unwire only
    scanned at ``+2``, so the keys remained while the CLI claimed
    success. With the fix both paths share the same dynamic derivation,
    and the round trip leaves the file byte-stable (apart from any
    owned keys it removed).
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, _NON_CANONICAL_INDENT_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    assert change.was_modified
    wired_text = change.new_text
    # The new env child lands at the workflow's own +12 indent (4-space
    # style under 8-space body), not the canonical +2 / +10.
    assert "            MERGECRAFT_TRACING_PROJECT: ${{ vars.LOGFIRE_PROJECT }}" in wired_text
    # The unrelated ``MERGECRAFT_X: keep_me`` survives untouched.
    assert "MERGECRAFT_X: keep_me" in wired_text
    # Persist the wire so the next call sees the modified file.
    workflow.write_text(wired_text, encoding="utf-8")
    # Now unwire.
    remove_change = remove_logfire_wiring(
        workflow_path=workflow,
        step_selector="primary",
    )
    # The unwire must actually remove the wired keys, not silently
    # leave them in place.
    assert remove_change.was_modified
    assert "MERGECRAFT_TRACING_PROJECT" not in remove_change.new_text
    # The unrelated ``MERGECRAFT_X: keep_me`` survives the unwire too,
    # and the with: keys are gone as well.
    parsed_after = yaml.safe_load(remove_change.new_text)
    step_after = parsed_after["jobs"]["review"]["steps"][0]
    assert "MERGECRAFT_TRACING_PROJECT" not in (step_after.get("env") or {})
    assert "MERGECRAFT_X" in step_after["env"]
    for key in OWNED_WITH_KEYS:
        assert key not in step_after["with"]


# Blocker 3 (data integrity): ``_find_mapping_block`` matched the first
# ``env:`` / ``tracing-to:`` line at *any* indent, so a literal ``env:``
# line inside a ``prompt: |`` block scalar was treated as the step's
# real ``env:`` mapping. The fix scopes the search to direct indents
# (``at_indent = step body indent``), and tightens ``_assert_wired_semantics``
# to require a parsed ``env:`` mapping (rather than silently accepting
# ``env: None``). The two cases below pin both halves.
_BLOCK_SCALAR_NESTED_ENV_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review
        uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157 # pre-0.0.1
        with:
          prompt: |
            env: this is just script text inside the prompt block scalar
            tracing-to: ditto
          logfire-token-typo: anything
        env:
          MERGECRAFT_X: keep_me
"""


def test_unwire_does_not_touch_block_scalar_nested_env_or_tracing_to(tmp_path: Path) -> None:
    """Unwire leaves literal ``env:`` / ``tracing-to:`` text inside ``prompt: |`` alone.

    Regression for round-4 blocker 3 (part 1): ``_find_mapping_block``
    matched the first ``env:`` line at any indent, including a line
    inside ``with.prompt: |``. The fix scopes the search to the
    step's body indent. A line like ``env: this is just script text``
    inside the block scalar must remain untouched by unwire.
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, _BLOCK_SCALAR_NESTED_ENV_TEMPLATE)
    # Wire first, so the owned keys land alongside the script text.
    wire_change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    assert wire_change.was_modified
    wired_text = wire_change.new_text
    # Script text survives the wire -- the line-based mutator must not
    # have hoisted or rewritten it.
    assert "env: this is just script text inside the prompt block scalar" in wired_text
    assert "tracing-to: ditto" in wired_text
    # Persist the wire so the next call sees the modified file.
    workflow.write_text(wired_text, encoding="utf-8")
    # Now unwire.
    remove_change = remove_logfire_wiring(
        workflow_path=workflow,
        step_selector="primary",
    )
    assert remove_change.was_modified
    unwired_text = remove_change.new_text
    # The script text still survives.
    assert "env: this is just script text inside the prompt block scalar" in unwired_text
    assert "tracing-to: ditto" in unwired_text
    # And the canonical env child is gone.
    assert "MERGECRAFT_TRACING_PROJECT" not in unwired_text
    # The unrelated ``MERGECRAFT_X: keep_me`` survives.
    assert "MERGECRAFT_X: keep_me" in unwired_text


def test_assert_wired_semantics_rejects_missing_parsed_env(tmp_path: Path) -> None:
    """A successful wire MUST leave a parsed ``env:`` mapping on the step.

    Regression for round-4 blocker 3 (part 2): the post-mutation
    assertion used to silently accept a missing parsed ``env:``
    (``step.get("env") is None``), which let a wire that lost the
    block-scalar ``env:`` to script-text redirection pass the check.
    The fix makes ``_assert_wired_semantics`` reject a step whose
    parsed ``env:`` is ``None`` -- a wire is required to leave one.

    This test reaches into the post-check helper directly because the
    block-scalar redirection above is hard to trigger from the public
    API now that the regex is scoped; the requirement itself
    (reject ``env is None``) is a parseable invariant worth pinning.
    """
    from mergecraft.cli.tracing_logfire_wf_yaml import (
        _assert_wired_semantics,
    )

    # A step whose parsed ``env:`` is None -- this is the condition the
    # post-check used to accept.
    bad_yaml = """\
jobs:
  review:
    steps:
      - uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157
        with:
          tracing: 'true'
          tracing-to: logfire
          logfire-token: x
"""
    with pytest.raises(LogfireWorkflowError, match="missing env:"):
        _assert_wired_semantics(bad_yaml, step_identifiers=["job:review/step:0"])

    # Sanity: a step that does have a parsed env passes.
    good_yaml = """\
jobs:
  review:
    steps:
      - uses: alexhawat/mergeCraft@f5b070bddce40099dab77778231cac3456a55157
        with:
          tracing: 'true'
          tracing-to: logfire
          logfire-token: x
        env:
          MERGECRAFT_TRACING_PROJECT: y
"""
    _assert_wired_semantics(good_yaml, step_identifiers=["job:review/step:0"])


# ---------------------------------------------------------------------------
# Round-5 regression tests -- support README Examples 1 and 6
# ---------------------------------------------------------------------------
# README Examples 1 (auto-review every PR) and 6 (Tracing with Logfire) both
# use the *inline* ``- uses: alexhawat/mergeCraft@pre-0.0.1`` step form on
# indented ``steps:`` lists, and Example 1 defines only ``env:`` on the step
# (every ``action.yml`` input is optional). Round 3 of the self-review
# raised these as blockers because the previous regex did not match the
# inline form and ``_do`` had a "the mergeCraft action requires with:"
# comment that was demonstrably wrong. These tests pin both fixes so a
# later refactor can't silently regress them.


# Example 1 (env-only) -- action step with only ``env:``, no ``with:``.
EXAMPLE_1_ENV_ONLY_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
    types: [opened, synchronize, ready_for_review]
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write
  issues: write
  id-token: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: alexhawat/mergeCraft@pre-0.0.1
        env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
"""


# Example 6 (Logfire tracing) -- inline form with both ``with:`` and ``env:``.
# Note: this template omits any pre-existing ``tracing`` / ``tracing-to`` /
# ``logfire-token`` keys so the wire path inserts cleanly without ``force``.
EXAMPLE_6_INLINE_FORM_TEMPLATE = """\
name: mergecraft
on:
  pull_request:
jobs:
  trace:
    runs-on: ubuntu-latest
    steps:
      - uses: alexhawat/mergeCraft@pre-0.0.1
        with:
          prompt: ${{ steps.prompt.outputs.text }}
          timeout: 25m
          model: nous/deepseek/deepseek-v4-flash
        env:
          LOGFIRE_TOKEN: ${{ secrets.LOGFIRE_TOKEN }}
"""


def test_apply_logfire_wiring_supports_inline_uses_form(tmp_path: Path) -> None:
    """Inline ``- uses: alexhawat/mergeCraft@X`` (README Example 6) wires cleanly.

    The previous regex ``^(?P<indent>[ \t]+)uses:`` required leading
    whitespace before ``uses:`` and rejected the inline form where
    ``-`` shares the line with ``uses:`` -- so exactly the workflows the
    README tells operators to write failed with
    "no ``uses: alexhawat/mergeCraft`` step found".
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, EXAMPLE_6_INLINE_FORM_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    assert change.was_modified
    new = change.new_text
    parsed = yaml.safe_load(new)
    step = parsed["jobs"]["trace"]["steps"][0]
    assert step["with"]["tracing"] == "true"
    assert step["with"]["tracing-to"] == "logfire"
    assert step["with"]["logfire-token"] == "${{ secrets.LOGFIRE_TOKEN }}"
    assert step["env"]["MERGECRAFT_TRACING_PROJECT"] == "${{ vars.LOGFIRE_PROJECT }}"
    # The existing env line is preserved alongside the newly-injected one.
    assert step["env"]["LOGFIRE_TOKEN"] == "${{ secrets.LOGFIRE_TOKEN }}"


def test_apply_logfire_wiring_creates_with_block_when_missing(tmp_path: Path) -> None:
    """A step with only ``env:`` (README Example 1) gets a synthesised ``with:``.

    Every ``action.yml`` input is ``required: false``, and Example 1's
    minimal step defines only ``env:`` on the action. The previous
    ``_do`` returned silently because the ``with:`` insert was a no-op
    *and* there was no existing ``with:`` to extend -- then
    ``_assert_wired_semantics`` rejected the result with
    "with: is None (not a mapping)".
    """
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, EXAMPLE_1_ENV_ONLY_TEMPLATE)
    change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="all",
        force=False,
    )
    assert change.was_modified
    new = change.new_text
    parsed = yaml.safe_load(new)
    # Find the mergeCraft step (skip the actions/checkout step above it).
    mergecraft_step = next(
        s
        for s in parsed["jobs"]["review"]["steps"]
        if str(s["uses"]).startswith("alexhawat/mergeCraft@")
    )
    assert mergecraft_step["with"]["tracing"] == "true"
    assert mergecraft_step["with"]["tracing-to"] == "logfire"
    assert mergecraft_step["with"]["logfire-token"] == "${{ secrets.LOGFIRE_TOKEN }}"
    # The pre-existing env line is preserved.
    assert (
        mergecraft_step["env"]["CLAUDE_CODE_OAUTH_TOKEN"]
        == "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"
    )
    assert mergecraft_step["env"]["MERGECRAFT_TRACING_PROJECT"] == "${{ vars.LOGFIRE_PROJECT }}"


def test_unwire_workflow_round_trip_on_inline_uses_form(tmp_path: Path) -> None:
    """Wire -> unwire round trip on the inline form leaves no owned keys behind."""
    workflow = tmp_path / "mergecraft.yml"
    _write_workflow(workflow, EXAMPLE_6_INLINE_FORM_TEMPLATE)
    wire_change = apply_logfire_wiring(
        workflow_path=workflow,
        secret_name="LOGFIRE_TOKEN",
        project_var_name="LOGFIRE_PROJECT",
        step_selector="primary",
        force=False,
    )
    _write_workflow(workflow, wire_change.new_text)
    remove_change = remove_logfire_wiring(
        workflow_path=workflow,
        step_selector="primary",
    )
    assert remove_change.was_modified
    parsed = yaml.safe_load(remove_change.new_text)
    mergecraft_step = next(
        s
        for s in parsed["jobs"]["trace"]["steps"]
        if str(s["uses"]).startswith("alexhawat/mergeCraft@")
    )
    # Owned ``with:`` keys removed.
    with_map = mergecraft_step.get("with") or {}
    for key in OWNED_WITH_KEYS:
        assert key not in with_map, f"{key} still present after unwire"
    # Owned env key removed; pre-existing LOGFIRE_TOKEN preserved.
    env_map = mergecraft_step.get("env") or {}
    assert "MERGECRAFT_TRACING_PROJECT" not in env_map
    assert env_map["LOGFIRE_TOKEN"] == "${{ secrets.LOGFIRE_TOKEN }}"
