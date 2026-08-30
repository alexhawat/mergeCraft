"""W1.3 — ``mergecraft provider status`` roster view (wave 16, green after W4)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from tests.cli.support_provider_registry import stub_mergecraft_env
from tests.cli.support_provider_status import (
    CHAIN_REVIEWER_CONFIG,
    WORKFLOW_UNWIRED_STEP,
    assert_no_secret_material,
    bootstrap_status_repo,
    parse_status_json,
    plain_cli_output,
    register_chain_providers,
    require_status_json_schema,
    snapshot_paths,
    two_reviewer_config,
    validate_status_payload,
    write_config,
    write_provider_entry,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
W4_XFAIL = pytest.mark.xfail(reason="green after W4: provider status roster view", strict=True)


def _invoke(*argv: str, env: dict[str, str] | None = None) -> Any:
    merged = dict(_DUMB_ENV)
    if env:
        merged.update(env)
    return runner.invoke(app, list(argv), env=merged)


def _require_status_subcommand() -> None:
    result = _invoke("provider", "--help")
    output = plain_cli_output(result.stdout + result.stderr).lower()
    if result.exit_code != CLI_SUCCESS_EXIT_CODE or "status" not in output:
        pytest.fail("mergecraft provider status is not registered yet")


@W4_XFAIL
def test_provider_status_renders_every_reviewer_slot_and_provider(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _require_status_subcommand()
    bootstrap_status_repo(tmp_path, monkeypatch, config_body=CHAIN_REVIEWER_CONFIG)
    register_chain_providers(tmp_path, _invoke)

    result = _invoke("provider", "status", "--cwd", str(tmp_path))
    output = plain_cli_output(result.stdout + result.stderr)

    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    for token in ("reviewer", "reviewer2", "p0", "p1", "anthropic", "openai"):
        assert token in output.lower(), f"expected {token!r} in status output"


@W4_XFAIL
def test_provider_status_missing_credential_reports_env_var_not_value(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _require_status_subcommand()
    bootstrap_status_repo(tmp_path, monkeypatch)
    register_chain_providers(tmp_path, _invoke)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER_1_API_KEY", raising=False)

    result = _invoke("provider", "status", "--cwd", str(tmp_path))
    output = plain_cli_output(result.stdout + result.stderr)

    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "not available" in output.lower() or "unavailable" in output.lower()
    assert "ANTHROPIC_API_KEY" in output or "LLM_PROVIDER" in output
    assert_no_secret_material(output, secrets=("super-secret-value",))


@W4_XFAIL
def test_provider_status_unwired_is_distinct_from_missing_credential(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _require_status_subcommand()
    bootstrap_status_repo(
        tmp_path,
        monkeypatch,
        config_body=two_reviewer_config(),
        workflow_body=WORKFLOW_UNWIRED_STEP,
    )
    write_provider_entry(tmp_path, label="nous", env_index=3)

    result = _invoke("provider", "status", "--cwd", str(tmp_path))
    output = plain_cli_output(result.stdout + result.stderr).lower()

    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "not wired" in output
    assert "not available" in output or "unavailable" in output
    missing_label = "not available" if "not available" in output else "unavailable"
    assert missing_label != "not wired"


@W4_XFAIL
def test_provider_status_renders_dispatch_level_and_after_ordering(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _require_status_subcommand()
    bootstrap_status_repo(tmp_path, monkeypatch, config_body=CHAIN_REVIEWER_CONFIG)
    register_chain_providers(tmp_path, _invoke)

    result = _invoke("provider", "status", "--json", "--cwd", str(tmp_path))
    payload = parse_status_json(result.stdout)
    validate_status_payload(payload)

    levels = {row.get("dispatchLevel") for row in payload["reviewers"]}
    assert len(levels) >= 2, "after: reviewer2 must render on a later dispatch level"
    after_agents = [row.get("after") for row in payload["reviewers"] if row.get("after")]
    assert after_agents, "after: ordering must be visible in JSON"


@W4_XFAIL
def test_provider_status_disabled_provider_renders_disabled(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _require_status_subcommand()
    bootstrap_status_repo(tmp_path, monkeypatch)
    register_chain_providers(tmp_path, _invoke)
    disable = _invoke(
        "provider", "disable", "anthropic", "--scope", "local", "--cwd", str(tmp_path)
    )
    assert disable.exit_code == CLI_SUCCESS_EXIT_CODE, disable.stdout + disable.stderr

    result = _invoke("provider", "status", "--cwd", str(tmp_path))
    output = plain_cli_output(result.stdout + result.stderr).lower()

    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "disabled" in output
    assert "anthropic" in output


@W4_XFAIL
def test_provider_status_github_without_token_is_unknown_exit_zero(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _require_status_subcommand()
    bootstrap_status_repo(tmp_path, monkeypatch)
    register_chain_providers(tmp_path, _invoke)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    result = _invoke("provider", "status", "--github", "--cwd", str(tmp_path))
    output = plain_cli_output(result.stdout + result.stderr).lower()

    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "unknown" in output
    assert "token" in output or "gh_token" in output or "github_token" in output


@W4_XFAIL
def test_provider_status_github_with_token_reports_secret_presence(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _require_status_subcommand()
    bootstrap_status_repo(tmp_path, monkeypatch)
    register_chain_providers(tmp_path, _invoke)

    present: set[str] = set()

    def _list_secrets(repo_slug: str) -> list[str]:
        assert repo_slug
        return sorted(present)

    def _probe(repo_slug: str, name: str) -> bool:
        assert repo_slug
        return name in present

    monkeypatch.setattr(
        "mergecraft.cli.provider_status.list_repo_secrets",
        _list_secrets,
        raising=False,
    )
    monkeypatch.setattr(
        "mergecraft.cli.provider_status.secret_is_present",
        _probe,
        raising=False,
    )
    present.update({"ANTHROPIC_API_KEY", "OPENAI_API_KEY"})
    monkeypatch.setenv("GH_TOKEN", "test-token")

    result = _invoke(
        "provider",
        "status",
        "--github",
        "--json",
        "--cwd",
        str(tmp_path),
        env={"GH_TOKEN": "test-token"},
    )
    payload = parse_status_json(result.stdout)
    github = payload.get("github") or {}
    secrets = github.get("secrets") or github.get("remoteSecrets") or []
    assert isinstance(secrets, (list, dict))
    rendered = json.dumps(secrets).lower()
    assert "anthropic_api_key" in rendered
    assert "present" in rendered or "true" in rendered
    assert_no_secret_material(result.stdout, secrets=("test-token",))


@W4_XFAIL
def test_provider_status_json_matches_documented_schema(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _require_status_subcommand()
    bootstrap_status_repo(tmp_path, monkeypatch, config_body=CHAIN_REVIEWER_CONFIG)
    register_chain_providers(tmp_path, _invoke)
    schema = require_status_json_schema()

    result = _invoke("provider", "status", "--json", "--cwd", str(tmp_path))
    payload = parse_status_json(result.stdout)
    validate_status_payload(payload)
    assert schema["version"] == payload["schemaVersion"]


@W4_XFAIL
def test_provider_status_cwd_selects_config_workflow_and_registry_targets(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _require_status_subcommand()
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    bootstrap_status_repo(repo_a, monkeypatch, config_body=CHAIN_REVIEWER_CONFIG)
    write_config(repo_b, two_reviewer_config())
    stub_mergecraft_env(monkeypatch, repo_b)
    monkeypatch.chdir(tmp_path)

    result = _invoke("provider", "status", "--json", "--cwd", str(repo_b))
    payload = parse_status_json(result.stdout)

    reviewer_ids = {row.get("agentId") or row.get("agent_id") for row in payload["reviewers"]}
    assert "reviewer2" in reviewer_ids
    assert all(
        "reviewer2" not in str(slot.get("model", "")) for slot in payload["reviewers"][0]["slots"]
    )


@W4_XFAIL
def test_provider_status_is_read_only(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _require_status_subcommand()
    bootstrap_status_repo(tmp_path, monkeypatch)
    register_chain_providers(tmp_path, _invoke)
    before = snapshot_paths(tmp_path)

    result = _invoke(
        "provider",
        "status",
        "--github",
        "--json",
        "--cwd",
        str(tmp_path),
        env={"GH_TOKEN": "read-only-token"},
    )

    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.stdout + result.stderr
    after = snapshot_paths(tmp_path)
    assert before == after, "status must not mutate config, env, or workflow files"
