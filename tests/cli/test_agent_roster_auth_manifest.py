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
from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
from mergecraft.review.roster_auth import RosterSecretEmptyError, validate_roster_at_run_start

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


def test_validate_roster_at_run_start_auto_detects_empty_secrets(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    bootstrap_review_repo(tmp_path, monkeypatch, workflow_body=WORKFLOW_INDEXED_STEP)
    slug = register_nous_model(tmp_path, _invoke)
    assign = _invoke("agent", "assign-model", "reviewer", "p0", slug)
    assert assign.exit_code == CLI_SUCCESS_EXIT_CODE, assign.stdout + assign.stderr
    monkeypatch.delenv("LLM_PROVIDER_1_API_KEY", raising=False)
    snapshot = capture_repo_settings_snapshot(root=tmp_path)
    with pytest.raises(RosterSecretEmptyError, match="NOUS_API_KEY"):
        validate_roster_at_run_start(snapshot=snapshot)


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


# --- Review finding (PR #566): auth-kind-aware credential requirements -------

_WORKFLOW_OAUTH_STEP = """\
name: mergecraft
on:
  pull_request_target:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review (oauth)
        uses: alexhawat/mergeCraft@pre-0.0.1
        with:
          model: anthropic/claude-sonnet-4-5
        env:
          LLM_PROVIDER_1: anthropic
          LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
"""

_WORKFLOW_DEVICE_CODE_STEP = """\
name: mergecraft
on:
  pull_request_target:
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - name: mergeCraft PR review (device code)
        uses: alexhawat/mergeCraft@pre-0.0.1
        with:
          model: openai/gpt-codex
        env:
          LLM_PROVIDER_1: openai
          LLM_PROVIDER_1_CODEX_AUTH_JSON: ${{ secrets.CODEX_AUTH_JSON }}
"""


def _settings_with_entry(*, label: str, auth_kind: str, harness: str, slug: str):
    from mergecraft.config.settings import RepoSettings

    return RepoSettings.model_validate(
        {
            "providers": [
                {"label": label, "harness": harness, "envIndex": 1, "authKind": auth_kind}
            ],
            "agents": {"reviewer": {"modelChain": [slug]}},
        }
    )


@pytest.mark.parametrize(
    ("label", "auth_kind", "harness", "slug", "workflow", "env_key"),
    [
        (
            "anthropic",
            "oauth",
            "claude",
            "anthropic/claude-sonnet-4-5",
            _WORKFLOW_OAUTH_STEP,
            "LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN",
        ),
        (
            "openai",
            "device_code",
            "codex",
            "openai/gpt-codex",
            _WORKFLOW_DEVICE_CODE_STEP,
            "LLM_PROVIDER_1_CODEX_AUTH_JSON",
        ),
    ],
    ids=["oauth", "device_code"],
)
def test_non_api_key_credential_satisfies_the_roster_check(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    label: str,
    auth_kind: str,
    harness: str,
    slug: str,
    workflow: str,
    env_key: str,
) -> None:
    """An oauth / device-code credential is a credential (PR #566 review finding).

    The check required ``LLM_PROVIDER_<N>_API_KEY`` for every registered
    provider, but ``default_auth_kind_for_label`` gives Anthropic ``oauth`` and
    OpenAI/Codex ``device_code``, whose credentials arrive under different
    suffixes. A repo that followed the documented ``mergecraft provider auth``
    quick-start was correctly configured and still failed closed at run start.
    """
    from mergecraft.review.roster_auth import _empty_secrets_for_roster

    workflow_path = scaffold_workflow_file(tmp_path, workflow)
    settings = _settings_with_entry(label=label, auth_kind=auth_kind, harness=harness, slug=slug)
    monkeypatch.delenv("LLM_PROVIDER_1_API_KEY", raising=False)
    monkeypatch.setenv(env_key, "token-value")

    empty = _empty_secrets_for_roster(
        settings=settings,
        workflow_path=workflow_path,
        roster_slugs=(slug,),
        wired=frozenset({label}),
    )
    assert empty == (), f"{auth_kind} credential in {env_key} must satisfy the roster check"


def test_missing_oauth_credential_names_the_wired_secret(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """With no alternative present it still fails closed, naming the bound secret."""
    from mergecraft.review.roster_auth import _empty_secrets_for_roster

    workflow_path = scaffold_workflow_file(tmp_path, _WORKFLOW_OAUTH_STEP)
    settings = _settings_with_entry(
        label="anthropic", auth_kind="oauth", harness="claude", slug="anthropic/claude-sonnet-4-5"
    )
    monkeypatch.delenv("LLM_PROVIDER_1_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    empty = _empty_secrets_for_roster(
        settings=settings,
        workflow_path=workflow_path,
        roster_slugs=("anthropic/claude-sonnet-4-5",),
        wired=frozenset({"anthropic"}),
    )
    assert empty == ("CLAUDE_CODE_OAUTH_TOKEN",)
