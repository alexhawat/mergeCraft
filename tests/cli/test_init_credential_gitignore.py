"""``init`` keeps local credentials out of Git, and writers refuse a tracked ``.env`` (#1296).

The documented flow is ``mergecraft init`` → ``provider auth --scope local`` →
commit and push. ``init`` therefore has to ignore ``.env`` and
``.mergecraft/config.local.yaml`` before the first ``git add .``, and the
shared ``.env`` writer must refuse a file Git already tracks: once a ``.env``
is committed, an ignore rule no longer protects it.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
import typer
from dotenv import dotenv_values
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.auth_cmd import _write_env_value

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

_CREDENTIAL_PATHS = (".env", ".mergecraft/config.local.yaml")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)


def _init_git_repo(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "init@test.local")
    _git(repo, "config", "user.name", "Init Test")
    (repo / "README.md").write_text("scaffold\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "init")


def _flat(text: str) -> str:
    """Undo console line wrapping so assertions see the message as one line."""
    return " ".join(text.split())


def _gitignore_lines(repo: Path) -> list[str]:
    return (repo / ".gitignore").read_text(encoding="utf-8").splitlines()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    return tmp_path


@pytest.mark.parametrize("rel", _CREDENTIAL_PATHS)
def test_credential_files_are_ignored_after_init(repo: Path, rel: str) -> None:
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert _git(repo, "check-ignore", "-q", rel).returncode == 0, (
        f"{rel} must be ignored after `mergecraft init`"
    )


def test_init_gitignore_entries_are_idempotent(repo: Path) -> None:
    for _ in range(2):
        result = runner.invoke(app, ["init", "--force"])
        assert result.exit_code == 0, result.output
    lines = _gitignore_lines(repo)
    for rel in _CREDENTIAL_PATHS:
        assert lines.count(rel) == 1, f"{rel} must appear exactly once: {lines}"


def test_similar_existing_entry_does_not_count_as_env(repo: Path) -> None:
    """``.envrc`` / ``!.env.example`` contain ``.env`` as text but do not ignore it."""
    (repo / ".gitignore").write_text(".envrc\n!.env.example\n", encoding="utf-8")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert ".env" in _gitignore_lines(repo)
    assert _git(repo, "check-ignore", "-q", ".env").returncode == 0


def test_init_warns_when_env_is_already_tracked(repo: Path) -> None:
    (repo / ".env").write_text("SOME_KEY=1\n", encoding="utf-8")
    _git(repo, "add", ".env")
    _git(repo, "commit", "-q", "-m", "track env")
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    output = _flat(result.output)
    assert "tracked by Git" in output
    assert "git rm --cached .env" in output


def test_writer_refuses_a_tracked_env(repo: Path) -> None:
    env_path = repo / ".env"
    env_path.write_text("OTHER=1\n", encoding="utf-8")
    _git(repo, "add", ".env")
    _git(repo, "commit", "-q", "-m", "track env")

    with pytest.raises(typer.Exit) as excinfo:
        _write_env_value(env_path, "ANTHROPIC_API_KEY", "sk-test-value")

    assert excinfo.value.exit_code != 0
    assert env_path.read_text(encoding="utf-8") == "OTHER=1\n", "a refused write must not land"


def test_cli_local_scope_refuses_a_tracked_env(repo: Path) -> None:
    """The refusal reaches the operator through a real ``--scope local`` command."""
    env_path = repo / ".env"
    env_path.write_text("OTHER=1\n", encoding="utf-8")
    _git(repo, "add", ".env")
    _git(repo, "commit", "-q", "-m", "track env")

    result = runner.invoke(app, ["tracing", "logfire", "disable", "--scope", "local"])

    assert result.exit_code != 0, result.output
    assert "refusing to write" in _flat(result.output)
    assert "tracked by Git" in _flat(result.output)
    assert env_path.read_text(encoding="utf-8") == "OTHER=1\n"


def test_writer_accepts_an_untracked_env_in_a_repo(repo: Path) -> None:
    env_path = repo / ".env"
    env_path.write_text("OTHER=1\n", encoding="utf-8")
    assert _write_env_value(env_path, "ANTHROPIC_API_KEY", "sk-test-value") is True
    assert dotenv_values(env_path)["ANTHROPIC_API_KEY"] == "sk-test-value"


def test_writer_creates_a_new_env_in_a_repo(repo: Path) -> None:
    env_path = repo / ".env"
    assert _write_env_value(env_path, "ANTHROPIC_API_KEY", "sk-test-value") is True
    assert dotenv_values(env_path)["ANTHROPIC_API_KEY"] == "sk-test-value"
