"""Provider credentials are collected only after a fixed destination is checked."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import typer

from mergecraft.cli import auth_cmd, provider_cmd

ENTRY = {"label": "example", "envIndex": 1, "authKind": "api_key"}


@pytest.mark.parametrize("admin", [False, None, True])
def test_provider_auth_preflight_before_collection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, admin: bool | None
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(auth_cmd, "_get_gh_token", lambda: "unused")
    monkeypatch.setattr(auth_cmd, "_parse_git_remote", lambda **kw: ("owner", "target"))

    def run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs["cwd"] == tmp_path
        calls.append(argv[-1])
        value = '{"permissions":{"admin":' + str(admin).lower().replace("none", "null") + "}}"
        if argv[-1].endswith("public-key"):
            value = '{"key_id":"id","key":"public"}'
        return subprocess.CompletedProcess(argv, 0, value)

    monkeypatch.setattr(auth_cmd.subprocess, "run", run)
    monkeypatch.setattr(provider_cmd, "_cancelable_getpass", lambda _: calls.append("prompt"))
    if admin:
        provider_cmd.run_provider_auth(ENTRY, "github", cwd=tmp_path)
        assert calls == [
            "repos/owner/target",
            "repos/owner/target/actions/secrets/public-key",
            "prompt",
        ]
    else:
        with pytest.raises(typer.Exit):
            provider_cmd.run_provider_auth(ENTRY, "github", cwd=tmp_path)
        assert calls == ["repos/owner/target"]


def test_provider_auth_preflight_unknown_access_never_prompts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(auth_cmd, "_get_gh_token", lambda: "unused")
    monkeypatch.setattr(auth_cmd, "_parse_git_remote", lambda **kw: ("someone", "upstream"))

    def fail(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired("gh", 30)

    monkeypatch.setattr(auth_cmd.subprocess, "run", fail)
    monkeypatch.setattr(
        provider_cmd, "_cancelable_getpass", lambda _: pytest.fail("collected credential")
    )
    with pytest.raises(typer.Exit):
        provider_cmd.run_provider_auth(ENTRY, "both", cwd=tmp_path)
    assert not (tmp_path / ".env").exists()


def test_provider_auth_local_preflight_never_calls_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.setattr(auth_cmd, "_get_gh_token", lambda: pytest.fail("GitHub accessed"))
    seen: list[auth_cmd.AuthTarget] = []

    def persist(*args: Any, **kwargs: Any) -> None:
        seen.append(kwargs["target"])

    monkeypatch.setattr(provider_cmd, "_persist_indexed_credentials", persist)
    provider_cmd.run_provider_auth(ENTRY, "local", cwd=tmp_path, credential_map={"API_KEY": "fake"})
    assert seen == [auth_cmd.AuthTarget(local=True, github=None, env_path=tmp_path / ".env")]


def test_provider_auth_target_cwd_controls_git_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caller = tmp_path / "caller"
    target = tmp_path / "target"
    for directory, owner in [(caller, "upstream"), (target, "adopter")]:
        directory.mkdir()
        subprocess.run(["git", "init", str(directory)], check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(directory),
                "remote",
                "add",
                "origin",
                f"https://github.com/{owner}/project.git",
            ],
            check=True,
        )
    monkeypatch.chdir(caller)
    assert auth_cmd._parse_git_remote(cwd=target) == ("adopter", "project")


@pytest.mark.parametrize("body", ["[]", '{"permissions": null}', '{"permissions": []}', "invalid"])
def test_provider_auth_malformed_permissions_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str
) -> None:
    monkeypatch.setattr(auth_cmd, "_get_gh_token", lambda: "unused")
    monkeypatch.setattr(auth_cmd, "_parse_git_remote", lambda **kw: ("owner", "target"))
    monkeypatch.setattr(
        auth_cmd.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, body)
    )
    monkeypatch.setattr(
        provider_cmd,
        "_validate_api_key_for_label",
        lambda *a: pytest.fail("validated before preflight"),
    )
    with pytest.raises(typer.Exit):
        provider_cmd.run_provider_auth(ENTRY, "github", cwd=tmp_path, api_key="fake-key")


def test_provider_auth_both_reports_github_failure_after_local_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = auth_cmd.AuthTarget(
        local=True, github=auth_cmd.GitHubSecretTarget("owner/target"), env_path=tmp_path / ".env"
    )
    monkeypatch.setattr("mergecraft.cli.roster_seed.seed_reviewer_p0_after_auth", lambda **kw: None)
    monkeypatch.setattr(auth_cmd, "_set_gh_secret", lambda **kw: False)
    provider_cmd._persist_indexed_credentials(
        ENTRY, "both", {"API_KEY": "fake-key"}, cwd=tmp_path, target=target
    )
    assert "LLM_PROVIDER_1_API_KEY" in (tmp_path / ".env").read_text()
    assert "gh secret set failed" in capsys.readouterr().err


def test_provider_auth_persistence_uses_captured_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = auth_cmd.AuthTarget(local=False, github=auth_cmd.GitHubSecretTarget("approved/target"))
    monkeypatch.setattr(auth_cmd, "_resolve_auth_target", lambda *a, **kw: target)
    monkeypatch.setattr(provider_cmd, "_cancelable_getpass", lambda _: "fake-key")
    monkeypatch.setattr(provider_cmd, "_validate_api_key_for_label", lambda *a: True)
    monkeypatch.setattr("mergecraft.cli.roster_seed.seed_reviewer_p0_after_auth", lambda **kw: None)
    writes: list[str] = []

    def save(**kwargs: Any) -> bool:
        writes.append(kwargs["repo_slug"])
        return True

    monkeypatch.setattr(auth_cmd, "_set_gh_secret", save)
    provider_cmd.run_provider_auth(ENTRY, "github", cwd=tmp_path)
    assert writes == ["approved/target"]
