"""Legacy ``mergecraft auth <provider>`` anchors its registry at the checkout root (#1557).

``auth`` has no ``--cwd``: its ``.env`` target comes from the git root of the
process working directory. The provider registry it reads must come from the
same root, or a run from a subdirectory silently writes the flat legacy secret
and never wires the generated workflow.

Contract: ``persist_legacy_indexed_auth(label, scope, credential_map, target=None)``
reads the registry from the same directory the credential is written to, and its
confirmation names the indexed key it wrote.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

import pytest
from tests.support.cli_text import compact_cli_text
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.provider_cmd import persist_legacy_indexed_auth

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_PLACEHOLDER_TOKEN = "sk-ant-oat01-placeholder-token"
_INDEXED_KEY = "LLM_PROVIDER_1_CLAUDE_CODE_OAUTH_TOKEN"
_FLAT_KEY = "CLAUDE_CODE_OAUTH_TOKEN"


def _bare_checkout(tmp_path: Path, monkeypatch: MonkeyPatch) -> tuple[Path, Path]:
    """Create a git checkout with no registered providers; return ``(root, subdir)``."""
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    root = tmp_path / "bare"
    (root / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root.resolve(), root / "sub"


def _checkout(tmp_path: Path, monkeypatch: MonkeyPatch) -> tuple[Path, Path]:
    """Create a git checkout with one registered ``claude`` provider.

    Returns ``(root, subdir)``. ``MERGECRAFT_ENV`` / ``MERGECRAFT_CONFIG`` are
    cleared so both the registry and the ``.env`` resolve through the checkout.
    """
    monkeypatch.delenv("MERGECRAFT_ENV", raising=False)
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    root = tmp_path / "repo"
    (root / "sub").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)

    added = runner.invoke(
        app,
        [
            "provider",
            "add",
            "--label",
            "claude",
            "--harness",
            "claude",
            "--url",
            "https://api.anthropic.com",
            "--cwd",
            str(root),
        ],
        env=_DUMB_ENV,
    )
    assert added.exit_code == 0, added.stdout + added.stderr
    return root.resolve(), root / "sub"


def _env_pairs(root: Path) -> dict[str, str]:
    from tests.cli.support_provider_registry import read_env_file

    return read_env_file(root)


def _stub_token_prompt(monkeypatch: MonkeyPatch) -> None:
    """Answer the legacy ``auth claude`` getpass prompt with a placeholder token."""
    monkeypatch.setattr(
        "mergecraft.cli.auth_cmd.getpass.getpass",
        lambda _prompt="": _PLACEHOLDER_TOKEN,
    )


def test_indexed_path_from_the_repository_root(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Guard: the indexed path was always taken from the checkout root."""
    root, _sub = _checkout(tmp_path, monkeypatch)
    monkeypatch.chdir(root)

    persisted = persist_legacy_indexed_auth(
        "claude", "local", {"API_KEY": _PLACEHOLDER_TOKEN}, target=None
    )

    assert persisted is True
    env = _env_pairs(root)
    assert _INDEXED_KEY in env, sorted(env)
    assert env[_INDEXED_KEY] == _PLACEHOLDER_TOKEN
    assert _FLAT_KEY not in env


def test_unregistered_label_falls_back_to_the_flat_secret(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Guard: an unregistered label keeps the flat legacy secret, unchanged."""
    root, _sub = _bare_checkout(tmp_path, monkeypatch)
    monkeypatch.chdir(root)
    _stub_token_prompt(monkeypatch)

    persisted = persist_legacy_indexed_auth(
        "not-registered", "local", {"API_KEY": _PLACEHOLDER_TOKEN}, target=None
    )
    assert persisted is False

    result = runner.invoke(app, ["auth", "claude", "--scope", "local"], env=_DUMB_ENV)
    assert result.exit_code == 0, result.stdout + result.stderr
    env = _env_pairs(root)
    assert env[_FLAT_KEY] == _PLACEHOLDER_TOKEN
    assert not any(key.startswith("LLM_PROVIDER_") for key in env)


@pytest.mark.xfail(reason="green after W2", strict=True)
def test_indexed_path_is_taken_from_a_subdirectory(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Bug: the registry lookup must use the git root, not the literal cwd."""
    root, sub = _checkout(tmp_path, monkeypatch)
    monkeypatch.chdir(sub)

    persisted = persist_legacy_indexed_auth(
        "claude", "local", {"API_KEY": _PLACEHOLDER_TOKEN}, target=None
    )

    assert persisted is True
    env = _env_pairs(root)
    assert _INDEXED_KEY in env, sorted(env)
    assert env[_INDEXED_KEY] == _PLACEHOLDER_TOKEN
    assert _FLAT_KEY not in env


@pytest.mark.xfail(reason="green after W2", strict=True)
def test_legacy_auth_command_from_a_subdirectory_writes_the_indexed_key(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Bug: ``mergecraft auth claude`` behaves the same from any directory."""
    root, sub = _checkout(tmp_path, monkeypatch)
    monkeypatch.chdir(sub)
    _stub_token_prompt(monkeypatch)

    result = runner.invoke(app, ["auth", "claude", "--scope", "local"], env=_DUMB_ENV)

    output = compact_cli_text(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    env = _env_pairs(root)
    assert _INDEXED_KEY in env, sorted(env)
    assert env[_INDEXED_KEY] == _PLACEHOLDER_TOKEN
    assert _FLAT_KEY not in env


@pytest.mark.xfail(reason="green after W2", strict=True)
def test_confirmation_names_the_key_written(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Bug: the confirmation lists the indexed key, not the bare suffix."""
    root, _sub = _checkout(tmp_path, monkeypatch)
    monkeypatch.chdir(root)
    _stub_token_prompt(monkeypatch)

    result = runner.invoke(app, ["auth", "claude", "--scope", "local"], env=_DUMB_ENV)

    output = compact_cli_text(_ANSI.sub("", result.stdout + result.stderr))
    assert result.exit_code == 0, output
    assert _INDEXED_KEY in output
    assert "LLM_PROVIDER_1, CLAUDE_CODE_OAUTH_TOKEN" not in output
