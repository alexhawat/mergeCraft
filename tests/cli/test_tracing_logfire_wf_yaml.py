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
