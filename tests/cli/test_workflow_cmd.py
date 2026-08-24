"""RED tests for ``mergecraft workflow`` authoring CLI (#484 / BG).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-b-provider-registry-wave-plan.md``
BG — test-creator. Pins the ``workflow`` namespace (not ``gha``), surgical
``with:``/``env:`` mutation, ``--dry-run`` diff, byte-stable comments, harness
validation parity with local ``provider`` commands, missing-secret reporting, and
ordinary CLI failures outside GitHub Actions.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from tests.cli.support_provider_registry import (
    CUSTOM_BASE_URL,
    NOUS_BASE_URL,
    NOUS_TENCENT_HY3,
    WORKFLOW_DEFAULT_RELATIVE_PATH,
    WORKFLOW_ONE_STEP_TEMPLATE,
    WORKFLOW_TWO_STEP_TEMPLATE,
    assert_only_owned_workflow_keys_changed,
    format_model_slug,
    indexed_custom_provider_api_key,
    indexed_custom_provider_base_url,
    indexed_env_key,
    read_config,
    require_workflow_cmd_symbols,
    scaffold_mergecraft_home,
    scaffold_workflow_file,
    stub_mergecraft_env,
    workflow_text,
    write_agents_model_chain,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _invoke(*argv: str, env: dict[str, str] | None = None) -> object:
    merged = dict(_DUMB_ENV)
    if env:
        merged.update(env)
    return runner.invoke(app, list(argv), env=merged)


def _setup_repo(tmp_path: Path, monkeypatch: MonkeyPatch, *, workflow_body: str) -> Path:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    stub_mergecraft_env(monkeypatch, tmp_path)
    return scaffold_workflow_file(tmp_path, workflow_body)


def _register_nous_provider(tmp_path: Path) -> None:
    add = _invoke(
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
    )
    assert add.exit_code == CLI_SUCCESS_EXIT_CODE, add.stdout + add.stderr
    model = _invoke("model", "add", "--provider", "nous", NOUS_TENCENT_HY3)
    assert model.exit_code == CLI_SUCCESS_EXIT_CODE, model.stdout + model.stderr


# ---------------------------------------------------------------------------
# Namespace: ``workflow`` authoring vs ``gha`` runtime (D9)
# ---------------------------------------------------------------------------


def test_workflow_namespace_registered_on_root_app() -> None:
    result = _invoke("workflow", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "provider" in output
    assert "model" in output


def test_gha_namespace_does_not_expose_workflow_authoring_verbs() -> None:
    result = _invoke("gha", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "workflow provider" not in output
    assert "setmodel" not in output


def test_workflow_help_lists_provider_model_agents_and_list_verbs() -> None:
    require_workflow_cmd_symbols()
    result = _invoke("workflow", "--help")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    for verb in ("provider", "model", "agents", "list"):
        assert verb in output, f"expected workflow subcommand group {verb!r} in help"


def test_workflow_provider_harnesses_lists_supported_values_from_code() -> None:
    result = _invoke("workflow", "provider", "harnesses")
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    for harness in ("codex", "claude", "opencode", "gemini", "cursor"):
        assert harness in output, f"expected harness {harness!r} in output"


# ---------------------------------------------------------------------------
# ``--dry-run`` default — diff without write (#484)
# ---------------------------------------------------------------------------


def test_workflow_provider_add_default_dry_run_shows_diff_without_writing(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    before = workflow.read_text(encoding="utf-8")

    result = _invoke(
        "workflow",
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
        "--workflow",
        str(workflow),
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert workflow.read_text(encoding="utf-8") == before
    assert indexed_custom_provider_base_url(1) in output or "diff" in output.lower()
    assert indexed_custom_provider_api_key(1) in output or "secrets" in output.lower()


def test_workflow_provider_add_apply_writes_owned_env_keys(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    before = workflow.read_text(encoding="utf-8")

    result = _invoke(
        "workflow",
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
        "--workflow",
        str(workflow),
        "--apply",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    after = workflow.read_text(encoding="utf-8")
    assert after != before
    assert indexed_custom_provider_base_url(1) in after
    assert indexed_custom_provider_api_key(1) in after
    assert NOUS_BASE_URL in after
    assert "${{ secrets." in after
    assert "=== PRESERVE: header comment block" in after
    assert "timeout-minutes: 65" in after
    assert_only_owned_workflow_keys_changed(before, after)


def test_workflow_model_add_updates_with_model_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    _register_nous_provider(tmp_path)
    before = workflow.read_text(encoding="utf-8")

    result = _invoke(
        "workflow",
        "model",
        "add",
        "--provider",
        "nous",
        NOUS_TENCENT_HY3,
        "--workflow",
        str(workflow),
        "--apply",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    after = workflow.read_text(encoding="utf-8")
    assert format_model_slug("nous", NOUS_TENCENT_HY3) in after
    parsed = yaml.safe_load(after)
    step = parsed["jobs"]["review"]["steps"][0]
    assert step["with"]["model"] == format_model_slug("nous", NOUS_TENCENT_HY3)
    assert_only_owned_workflow_keys_changed(before, after)


def test_workflow_agents_setmodel_updates_primary_step_model(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_TWO_STEP_TEMPLATE)
    _register_nous_provider(tmp_path)
    write_agents_model_chain(tmp_path, "reviewer", [format_model_slug("nous", NOUS_TENCENT_HY3)])
    before = workflow.read_text(encoding="utf-8")

    result = _invoke(
        "workflow",
        "agents",
        "setmodel",
        "--agent",
        "reviewer",
        "--provider",
        "nous",
        "--model",
        NOUS_TENCENT_HY3,
        "--workflow",
        str(workflow),
        "--step",
        "mergecraft_nous",
        "--apply",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    after = workflow.read_text(encoding="utf-8")
    parsed = yaml.safe_load(after)
    primary = next(
        step for step in parsed["jobs"]["review"]["steps"] if step.get("id") == "mergecraft_nous"
    )
    assert primary["with"]["model"] == format_model_slug("nous", NOUS_TENCENT_HY3)
    assert_only_owned_workflow_keys_changed(before, after)


def test_workflow_model_prioritize_reorders_fallback_steps(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_TWO_STEP_TEMPLATE)
    _register_nous_provider(tmp_path)
    acme_add = _invoke(
        "provider",
        "add",
        "--label",
        "acme",
        "--url",
        CUSTOM_BASE_URL,
        "--harness",
        "opencode",
    )
    assert acme_add.exit_code == CLI_SUCCESS_EXIT_CODE, acme_add.stdout + acme_add.stderr
    acme_model = _invoke("model", "add", "--provider", "acme", "gateway-model-1")
    assert acme_model.exit_code == CLI_SUCCESS_EXIT_CODE, acme_model.stdout + acme_model.stderr
    wire_acme = _invoke(
        "workflow",
        "model",
        "add",
        "--provider",
        "acme",
        "gateway-model-1",
        "--step",
        "mergecraft_codex",
        "--workflow",
        str(workflow),
        "--apply",
    )
    assert wire_acme.exit_code == CLI_SUCCESS_EXIT_CODE, wire_acme.stdout + wire_acme.stderr
    before = workflow.read_text(encoding="utf-8")

    result = _invoke(
        "workflow",
        "model",
        "prioritize",
        "--provider",
        "acme",
        "--model",
        "gateway-model-1",
        "--before",
        "nous/tencent/hy3",
        "--workflow",
        str(workflow),
        "--apply",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    after = workflow.read_text(encoding="utf-8")
    parsed = yaml.safe_load(after)
    models = [step["with"]["model"] for step in parsed["jobs"]["review"]["steps"] if "with" in step]
    assert models.index("acme/gateway-model-1") < models.index("nous/tencent/hy3")
    assert_only_owned_workflow_keys_changed(before, after)


WORKFLOW_THREE_STEP_TEMPLATE = """\
name: mergecraft
on:
  pull_request_target:
jobs:
  review:
    name: mergecraft review
    runs-on: ubuntu-latest
    timeout-minutes: 65
    steps:
      - name: mergeCraft PR review (Nous primary)
        id: mergecraft_nous
        uses: alexhawat/mergeCraft@5b9ded9ff3a27090f5c6d3cf722b2452596360bd # pre-0.0.1
        with:
          prompt: ${{ steps.prompt.outputs.text }}
          timeout: ${{ env.MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES }}m
          model: nous/tencent/hy3
        env:
          MERGECRAFT_CUSTOM_PROVIDER_BASE_URL: https://inference-api.nousresearch.com/v1
          MERGECRAFT_CUSTOM_PROVIDER_API_KEY: ${{ secrets.NOUS_API_KEY }}

      - name: mergeCraft PR review (middle)
        id: mergecraft_middle
        uses: alexhawat/mergeCraft@5b9ded9ff3a27090f5c6d3cf722b2452596360bd # pre-0.0.1
        with:
          prompt: ${{ steps.prompt.outputs.text }}
          timeout: ${{ env.MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES }}m
          model: openai/gpt-5.3-codex
        env:
          CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}

      - name: mergeCraft PR review (Codex fallback)
        id: mergecraft_codex
        uses: alexhawat/mergeCraft@5b9ded9ff3a27090f5c6d3cf722b2452596360bd # pre-0.0.1
        with:
          prompt: ${{ steps.prompt.outputs.text }}
          timeout: ${{ env.MERGECRAFT_REVIEW_ATTEMPT_TIMEOUT_MINUTES }}m
          model: acme/gateway-model-1
        env:
          MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_2: https://custom.example.test/v1
          LLM_PROVIDER_2_API_KEY: ${{ secrets.LLM_PROVIDER_2_API_KEY }}
"""


def test_workflow_model_prioritize_targets_step_with_requested_model(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Three-step chains must swap with the step that holds the promoted model."""
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_THREE_STEP_TEMPLATE)
    _register_nous_provider(tmp_path)
    acme_add = _invoke(
        "provider",
        "add",
        "--label",
        "acme",
        "--url",
        CUSTOM_BASE_URL,
        "--harness",
        "opencode",
    )
    assert acme_add.exit_code == CLI_SUCCESS_EXIT_CODE, acme_add.stdout + acme_add.stderr
    acme_model = _invoke("model", "add", "--provider", "acme", "gateway-model-1")
    assert acme_model.exit_code == CLI_SUCCESS_EXIT_CODE, acme_model.stdout + acme_model.stderr
    before = workflow.read_text(encoding="utf-8")

    result = _invoke(
        "workflow",
        "model",
        "prioritize",
        "--provider",
        "acme",
        "--model",
        "gateway-model-1",
        "--before",
        "nous/tencent/hy3",
        "--workflow",
        str(workflow),
        "--apply",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    after = workflow.read_text(encoding="utf-8")
    parsed = yaml.safe_load(after)
    steps = parsed["jobs"]["review"]["steps"]
    models = [step["with"]["model"] for step in steps if "with" in step]
    middle = next(step for step in steps if step.get("id") == "mergecraft_middle")
    assert middle["with"]["model"] == "openai/gpt-5.3-codex"
    assert models.index("acme/gateway-model-1") < models.index("nous/tencent/hy3")
    assert_only_owned_workflow_keys_changed(before, after)


def test_workflow_list_shows_provider_model_state(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_TWO_STEP_TEMPLATE)
    _register_nous_provider(tmp_path)

    result = _invoke("workflow", "list", "--workflow", str(workflow))
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "nous" in output
    assert "tencent/hy3" in output or "tencent" in output
    assert indexed_custom_provider_api_key(1) in output or "api_key" in output


# ---------------------------------------------------------------------------
# Validation, refusal, and operator guidance
# ---------------------------------------------------------------------------


def test_workflow_provider_add_rejects_unknown_harness(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    before = workflow_text(tmp_path)

    result = _invoke(
        "workflow",
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "not-a-real-harness",
        "--workflow",
        str(workflow),
    )
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "harness" in output
    assert workflow_text(tmp_path) == before


def test_workflow_provider_add_reports_missing_github_secrets(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)

    result = _invoke(
        "workflow",
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
        "--workflow",
        str(workflow),
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert indexed_env_key(1, "API_KEY") in output or "LLM_PROVIDER_1_API_KEY" in output
    assert "secret" in output.lower()


def test_workflow_mutate_refuses_when_no_mergecraft_step(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    body = """\
name: ci-only
on: push
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
"""
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=body)

    result = _invoke(
        "workflow",
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
        "--workflow",
        str(workflow),
    )
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "mergecraft" in output or "uses:" in output


def test_workflow_failure_is_ordinary_cli_error_not_action_annotation(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)

    result = _invoke(
        "workflow",
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        "not-a-url",
        "--harness",
        "opencode",
        "--workflow",
        str(workflow),
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, output
    assert "::error::" not in output


def test_workflow_runs_without_github_actions_env(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.delenv("GITHUB_STATE", raising=False)

    result = _invoke(
        "workflow",
        "list",
        "--workflow",
        str(workflow),
        env={"GITHUB_ACTIONS": "", "GITHUB_OUTPUT": "", "GITHUB_STATE": ""},
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "::error::" not in output


def test_workflow_default_path_targets_mergecraft_yml(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    result = _invoke("workflow", "list", "--help")
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert WORKFLOW_DEFAULT_RELATIVE_PATH in output


def test_workflow_mutated_repo_passes_action_yml_hygiene_check(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    apply = _invoke(
        "workflow",
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
        "--workflow",
        str(workflow),
        "--apply",
    )
    assert apply.exit_code == CLI_SUCCESS_EXIT_CODE, apply.stdout + apply.stderr

    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "check_action_yml_hygiene.py")],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# PR #498 review — --cwd scoping and existing-provider --url overrides
# ---------------------------------------------------------------------------


def test_relative_workflow_path_resolves_against_cwd_option(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """A relative --workflow follows --cwd, not the process working directory."""
    target = tmp_path / "target-repo"
    caller = tmp_path / "caller-repo"
    scaffold_mergecraft_home(target)
    scaffold_workflow_file(target, WORKFLOW_ONE_STEP_TEMPLATE)
    decoy = scaffold_workflow_file(caller, WORKFLOW_ONE_STEP_TEMPLATE)
    decoy_before = decoy.read_text(encoding="utf-8")

    # Deliberately do not chdir into the target: the caller sits elsewhere.
    monkeypatch.chdir(caller)
    stub_mergecraft_env(monkeypatch, target)

    result = _invoke(
        "workflow",
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        NOUS_BASE_URL,
        "--harness",
        "opencode",
        "--cwd",
        str(target),
        "--workflow",
        WORKFLOW_DEFAULT_RELATIVE_PATH,
        "--apply",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output

    assert decoy.read_text(encoding="utf-8") == decoy_before, (
        "a relative --workflow must not rewrite the caller's own workflow"
    )
    written = (target / WORKFLOW_DEFAULT_RELATIVE_PATH).read_text(encoding="utf-8")
    assert written != WORKFLOW_ONE_STEP_TEMPLATE, (
        "the --cwd repo's workflow should be the one wired"
    )


def test_existing_provider_url_override_is_applied_and_persisted(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """--url on an already-registered provider replaces the stored endpoint."""
    workflow = _setup_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    _register_nous_provider(tmp_path)

    result = _invoke(
        "workflow",
        "provider",
        "add",
        "--label",
        "nous",
        "--url",
        CUSTOM_BASE_URL,
        "--workflow",
        str(workflow),
        "--apply",
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output

    entries = read_config(tmp_path).get("providers", [])
    stored = next(entry for entry in entries if entry["label"] == "nous")
    assert stored["url"] == CUSTOM_BASE_URL, (
        f"the validated --url override must replace the stored endpoint; got {stored['url']!r}"
    )
    assert NOUS_BASE_URL not in workflow_text(workflow), (
        "the workflow must not stay wired to the superseded endpoint"
    )
