"""Legacy aliases share pre-collection permission checks and immutable targets."""

from __future__ import annotations

import getpass
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.cli.support_provider_registry import scaffold_mergecraft_home, write_provider_entry
from typer.testing import CliRunner

from mergecraft.cli import auth_cmd
from mergecraft.cli.app import app


def configure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registered: bool, label: str = "nous"
) -> None:
    scaffold_mergecraft_home(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    if registered:
        write_provider_entry(tmp_path, label=label, env_index=1, auth_kind="api_key")
    monkeypatch.setattr("mergecraft.cli.roster_seed.seed_reviewer_p0_after_auth", lambda **kw: None)


@pytest.mark.parametrize(
    "command", ["claude", "codex", "gemini", "cursor", "nous", "tokenhub", "minimax", "logfire"]
)
@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("scope", ["github", "both"])
@pytest.mark.parametrize(
    "failure", ["denied_admin", "unknown_admin", "denied_key", "malformed_key", "api_timeout"]
)
def test_legacy_auth_preflight_blocks_before_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    registered: bool,
    scope: str,
    failure: str,
) -> None:
    configure(tmp_path, monkeypatch, registered, command)
    monkeypatch.setattr(auth_cmd, "_get_gh_token", lambda: "unused")
    monkeypatch.setattr(auth_cmd, "_parse_git_remote", lambda **kw: ("upstream", "project"))
    monkeypatch.setattr(
        getpass, "getpass", lambda *a, **kw: pytest.fail("credential prompt before preflight")
    )
    monkeypatch.setattr(
        auth_cmd.typer,
        "prompt",
        lambda *a, **kw: pytest.fail("interactive prompt before preflight"),
    )

    def request(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert argv[:2] == ["gh", "api"], "device login started before preflight"
        if failure == "api_timeout":
            raise subprocess.TimeoutExpired(argv, 30)
        if argv[-1].endswith("public-key"):
            if failure == "denied_key":
                raise subprocess.CalledProcessError(1, argv, stderr="HTTP 403")
            body = "{}" if failure == "malformed_key" else '{"key_id":"id","key":"public"}'
        else:
            body = '{"permissions":{"admin":true}}'
            if failure == "denied_admin":
                body = '{"permissions":{"admin":false,"push":true}}'
            elif failure == "unknown_admin":
                body = '{"permissions":{"push":true}}'
        return subprocess.CompletedProcess(argv, 0, body)

    monkeypatch.setattr(auth_cmd.subprocess, "run", request)
    result = CliRunner().invoke(app, ["auth", command, "--scope", scope])
    assert result.exit_code != 0
    assert "cannot verify access to Actions secrets" in result.output
    assert not (tmp_path / ".env").exists()


@pytest.mark.parametrize("registered", [False, True])
def test_legacy_auth_success_reuses_preflight_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registered: bool
) -> None:
    configure(tmp_path, monkeypatch, registered)
    monkeypatch.setattr(auth_cmd, "_get_gh_token", lambda: "unused")
    monkeypatch.setattr(auth_cmd, "_parse_git_remote", lambda **kw: ("approved", "project"))
    calls: list[str] = []

    def request(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv[-1])
        body = (
            '{"key_id":"id","key":"public"}'
            if argv[-1].endswith("public-key")
            else '{"permissions":{"admin":true}}'
        )
        return subprocess.CompletedProcess(argv, 0, body)

    monkeypatch.setattr(auth_cmd.subprocess, "run", request)

    def collect(*args: Any, **kwargs: Any) -> str:
        assert calls == [
            "repos/approved/project",
            "repos/approved/project/actions/secrets/public-key",
        ]
        monkeypatch.setattr(
            auth_cmd,
            "_parse_git_remote",
            lambda **kw: pytest.fail("destination resolved again after collection"),
        )
        return "fake-key"

    monkeypatch.setattr(getpass, "getpass", collect)
    monkeypatch.setattr(auth_cmd, "_validate_nous_api_key", lambda key: True)
    writes: list[dict[str, str]] = []

    def save(**kwargs: str) -> bool:
        writes.append(kwargs)
        return True

    monkeypatch.setattr(auth_cmd, "_set_gh_secret", save)
    result = CliRunner().invoke(app, ["auth", "nous", "--scope", "github"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 2
    assert len(writes) == 1
    assert writes[0]["repo_slug"] == "approved/project"
    assert writes[0]["name"] == ("LLM_PROVIDER_1_API_KEY" if registered else "NOUS_API_KEY")


@pytest.mark.parametrize("registered", [False, True])
def test_legacy_auth_local_never_uses_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, registered: bool
) -> None:
    configure(tmp_path, monkeypatch, registered)
    monkeypatch.setattr(auth_cmd, "_get_gh_token", lambda: pytest.fail("GitHub accessed"))
    monkeypatch.setattr(
        auth_cmd,
        "_verify_github_secret_access",
        lambda *a, **kw: pytest.fail("GitHub preflight for local scope"),
    )
    monkeypatch.setattr(getpass, "getpass", lambda *a, **kw: "fake-key")
    monkeypatch.setattr(auth_cmd, "_validate_nous_api_key", lambda key: True)
    result = CliRunner().invoke(app, ["auth", "nous", "--scope", "local"])
    assert result.exit_code == 0, result.output
    expected = "LLM_PROVIDER_1_API_KEY" if registered else "NOUS_API_KEY"
    assert expected in (tmp_path / ".env").read_text()
