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
    for key in OWNED_ENV_KEYS:
        assert f"{key}:" in new, f"missing {key} after wiring"
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
