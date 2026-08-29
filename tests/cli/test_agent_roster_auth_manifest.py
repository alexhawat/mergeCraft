"""W1.7 — auth manifest & fail-closed wiring (wave plan 11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.cli.support_agent_roster import (
    WORKFLOW_GATED_STEP,
    WORKFLOW_INDEXED_STEP,
    bootstrap_review_repo,
    plain_cli_output,
    register_nous_model,
    require_parse_auth_manifest,
    require_roster_auth_validation,
    scaffold_workflow_file,
)
from tests.cli.support_provider_registry import (
    WORKFLOW_ONE_STEP_TEMPLATE,
    assert_only_owned_workflow_keys_changed,
    workflow_text,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _invoke(*argv: str, env: dict[str, str] | None = None) -> object:
    merged = dict(_DUMB_ENV)
    if env:
        merged.update(env)
    return runner.invoke(app, list(argv), env=merged)


def test_parse_auth_manifest_reads_indexed_llm_provider_env(tmp_path: Path) -> None:
    workflow_path = scaffold_workflow_file(tmp_path, WORKFLOW_INDEXED_STEP)
    parse_auth_manifest = require_parse_auth_manifest()
    labels = parse_auth_manifest(workflow_path)
    assert "nous" in labels


def test_parse_auth_manifest_counts_secret_gated_step(tmp_path: Path) -> None:
    workflow_path = scaffold_workflow_file(tmp_path, WORKFLOW_GATED_STEP)
    parse_auth_manifest = require_parse_auth_manifest()
    labels = parse_auth_manifest(workflow_path)
    assert "openai" in labels


def test_agent_assign_model_bails_on_unwired_provider(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    bootstrap_review_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    slug = register_nous_model(tmp_path, _invoke)
    result = _invoke("agent", "assign-model", "reviewer", "p0", slug)
    assert result.exit_code != 0
    output = plain_cli_output(result.stdout + result.stderr).lower()
    assert "nous" in output
    assert "workflow" in output or "mergecraft.yml" in output or "provider" in output


def test_agent_assign_model_allow_unwired_permits_with_warning(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    bootstrap_review_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    slug = register_nous_model(tmp_path, _invoke)
    result = _invoke("agent", "assign-model", "reviewer", "p0", slug, "--allow-unwired")
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    output = plain_cli_output(result.stdout + result.stderr).lower()
    assert "warn" in output or "unwired" in output


def test_agent_local_accepts_unwired_provider(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    bootstrap_review_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    slug = register_nous_model(tmp_path, _invoke)
    result = _invoke("agent-local", "assign-model", "reviewer", "p0", slug)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr


def test_run_start_validation_fails_closed_on_unwired_provider(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    bootstrap_review_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    slug = register_nous_model(tmp_path, _invoke)
    assign = _invoke("agent", "assign-model", "reviewer", "p0", slug, "--allow-unwired")
    assert assign.exit_code == CLI_SUCCESS_EXIT_CODE, assign.stdout + assign.stderr
    validate = require_roster_auth_validation()
    with pytest.raises(Exception, match=r"unwired|credential step|mergecraft\.yml|nous"):
        validate(repo_root=tmp_path, workflow_path=tmp_path / ".github/workflows/mergecraft.yml")


def test_unwired_provider_and_empty_secret_messages_differ(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    bootstrap_review_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_INDEXED_STEP)
    validate = require_roster_auth_validation()
    unwired_exc: Exception | None = None
    empty_exc: Exception | None = None
    try:
        validate(
            repo_root=tmp_path,
            workflow_path=tmp_path / ".github/workflows/mergecraft.yml",
            roster_slugs=("acme/not-wired",),
        )
    except Exception as exc:
        unwired_exc = exc
    try:
        validate(
            repo_root=tmp_path,
            workflow_path=tmp_path / ".github/workflows/mergecraft.yml",
            roster_slugs=("nous/tencent/hy3",),
            empty_secrets=("NOUS_API_KEY",),
        )
    except Exception as exc:
        empty_exc = exc
    assert unwired_exc is not None
    assert empty_exc is not None
    assert str(unwired_exc).lower() != str(empty_exc).lower()
    assert "credential step" in str(unwired_exc).lower() or "unwired" in str(unwired_exc).lower()
    assert "empty" in str(empty_exc).lower() or "secret" in str(empty_exc).lower()


def test_workflow_sync_check_exits_nonzero_and_writes_nothing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    bootstrap_review_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    slug = register_nous_model(tmp_path, _invoke)
    assign = _invoke("agent", "assign-model", "reviewer", "p0", slug, "--allow-unwired")
    assert assign.exit_code == CLI_SUCCESS_EXIT_CODE, assign.stdout + assign.stderr
    before = workflow_text(tmp_path)
    result = _invoke("workflow", "sync", "--check")
    assert result.exit_code != 0
    assert workflow_text(tmp_path) == before


def test_workflow_sync_apply_adds_missing_step_with_owned_keys_only(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    bootstrap_review_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_ONE_STEP_TEMPLATE)
    slug = register_nous_model(tmp_path, _invoke)
    assign = _invoke("agent", "assign-model", "reviewer", "p0", slug, "--allow-unwired")
    assert assign.exit_code == CLI_SUCCESS_EXIT_CODE, assign.stdout + assign.stderr
    before = workflow_text(tmp_path)
    result = _invoke("workflow", "sync", "--apply")
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    after = workflow_text(tmp_path)
    assert after != before
    assert_only_owned_workflow_keys_changed(before, after)
    assert "nous" in after.lower() or "LLM_PROVIDER" in after
