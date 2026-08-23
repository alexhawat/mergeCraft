"""CF #473 RED — ``mergecraft update`` and commit in ``--version`` (D7).

Pins:
- ``update`` shells to ``uv tool install --reinstall``; default ref ``main``.
- ``--branch`` accepts branch, tag, or SHA.
- ``--version`` / ``version`` show ``0.1.0a1 (abc1234)`` when commit known;
  omit parentheses when unknown.
- JSON ``commit`` field is additive on ``version --format json``.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import pytest
from tests.cli.support_update_version import (
    DEFAULT_UPDATE_REF,
    require_version_callable,
    update_cmd_module,
    uv_install_spec,
)
from typer.testing import CliRunner

from mergecraft import __version__
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_SAMPLE_COMMIT = "abc1234567890abcdef1234567890abcdef123456"
_SHORT_COMMIT = "abc1234"


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _set_build_commit(monkeypatch: MonkeyPatch, commit: str | None) -> None:
    """Pin the installed build commit for version display helpers."""
    monkeypatch.setattr("mergecraft.__commit__", commit, raising=False)


@pytest.mark.xfail(reason="green after CF", strict=False)
def test_update_help_documents_uv_reinstall() -> None:
    """Happy — ``update --help`` documents the self-update command."""
    result = runner.invoke(app, ["update", "--help"], env=_DUMB_ENV)
    output = _plain(result.stdout)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    lowered = output.lower()
    assert "update" in lowered
    assert "uv" in lowered
    assert "reinstall" in lowered or "install" in lowered


@pytest.mark.xfail(reason="green after CF", strict=False)
def test_update_default_shells_to_uv_tool_install_on_main(
    monkeypatch: MonkeyPatch,
) -> None:
    """Happy — default ``update`` runs ``uv tool install --reinstall`` at ``main``."""
    recorded: list[list[str]] = []

    def _fake_run(argv: list[str], **kwargs: Any) -> Any:
        recorded.append(list(argv))
        return None

    monkeypatch.setattr(update_cmd_module().subprocess, "run", _fake_run)

    result = runner.invoke(app, ["update"], env=_DUMB_ENV)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.output

    assert recorded, "update must invoke subprocess.run"
    cmd = recorded[0]
    assert cmd[0] == "uv"
    assert "tool" in cmd
    assert "install" in cmd
    assert "--reinstall" in cmd
    assert uv_install_spec(DEFAULT_UPDATE_REF) in cmd


@pytest.mark.parametrize(
    "ref",
    [
        "feature/cli-update",
        "pre-0.0.1",
        "e0a48d9f",
    ],
)
@pytest.mark.xfail(reason="green after CF", strict=False)
def test_update_branch_option_accepts_branch_tag_or_sha(
    monkeypatch: MonkeyPatch,
    ref: str,
) -> None:
    """Edge — ``--branch`` accepts branch names, tags, and short SHAs."""
    recorded: list[list[str]] = []

    def _fake_run(argv: list[str], **kwargs: Any) -> Any:
        recorded.append(list(argv))
        return None

    monkeypatch.setattr(update_cmd_module().subprocess, "run", _fake_run)

    result = runner.invoke(app, ["update", "--branch", ref], env=_DUMB_ENV)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.output
    cmd = recorded[0]
    assert uv_install_spec(ref) in cmd


@pytest.mark.xfail(reason="green after CF", strict=False)
def test_format_version_display_includes_short_commit_when_known() -> None:
    """Unit — version helper renders ``<version> (<short-sha>)`` when commit known."""
    format_display = require_version_callable("format_version_display")
    rendered = format_display(__version__, _SAMPLE_COMMIT)
    assert rendered == f"{__version__} ({_SHORT_COMMIT})"


@pytest.mark.xfail(reason="green after CF", strict=False)
def test_format_version_display_omits_paren_commit_when_unknown() -> None:
    """Unit — version helper omits parentheses when build commit is unknown."""
    format_display = require_version_callable("format_version_display")
    rendered = format_display(__version__, None)
    assert rendered == __version__
    assert "(" not in rendered


@pytest.mark.xfail(reason="green after CF", strict=False)
def test_version_flag_includes_commit_when_known(monkeypatch: MonkeyPatch) -> None:
    """Happy — ``mergecraft --version`` includes short commit when available."""
    _set_build_commit(monkeypatch, _SAMPLE_COMMIT)
    result = runner.invoke(app, ["--version"], env=_DUMB_ENV)
    output = _plain(result.stdout).strip()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert output == f"{__version__} ({_SHORT_COMMIT})"


@pytest.mark.xfail(reason="green after CF", strict=False)
def test_version_command_includes_commit_when_known(monkeypatch: MonkeyPatch) -> None:
    """Happy — ``mergecraft version`` includes short commit when available."""
    _set_build_commit(monkeypatch, _SAMPLE_COMMIT)
    result = runner.invoke(app, ["version"], env=_DUMB_ENV)
    output = _plain(result.stdout).strip()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert output == f"{__version__} ({_SHORT_COMMIT})"


def test_version_flag_omits_paren_commit_when_unknown(monkeypatch: MonkeyPatch) -> None:
    """Edge — ``--version`` omits parentheses when build commit is unknown."""
    _set_build_commit(monkeypatch, None)
    result = runner.invoke(app, ["--version"], env=_DUMB_ENV)
    output = _plain(result.stdout).strip()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert output == __version__
    assert "(" not in output


@pytest.mark.xfail(reason="green after CF", strict=False)
def test_version_json_includes_additive_commit_field(monkeypatch: MonkeyPatch) -> None:
    """Functional — ``version --format json`` adds ``commit`` without breaking ``version``."""
    _set_build_commit(monkeypatch, _SAMPLE_COMMIT)
    result = runner.invoke(
        app,
        ["version", "--format", "json"],
        env=_DUMB_ENV,
    )
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.output
    payload = json.loads(result.stdout)
    assert payload["version"] == __version__
    assert payload["commit"] == _SHORT_COMMIT
    assert "schema_version" in payload


@pytest.mark.xfail(reason="green after CF", strict=False)
def test_version_json_commit_null_when_unknown(monkeypatch: MonkeyPatch) -> None:
    """Edge — JSON ``commit`` is null (additive) when build commit is unknown."""
    _set_build_commit(monkeypatch, None)
    result = runner.invoke(
        app,
        ["version", "--format", "json"],
        env=_DUMB_ENV,
    )
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, result.output
    payload = json.loads(result.stdout)
    assert payload["version"] == __version__
    assert payload["commit"] is None


@pytest.mark.xfail(reason="green after CF", strict=False)
def test_update_run_uses_check_true(monkeypatch: MonkeyPatch) -> None:
    """Error — ``update`` propagates ``uv`` failures (``check=True`` contract)."""

    def _boom(argv: list[str], **kwargs: Any) -> None:
        raise OSError("uv missing")

    monkeypatch.setattr(update_cmd_module().subprocess, "run", _boom)

    result = runner.invoke(app, ["update"], env=_DUMB_ENV)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE
    combined = _plain(result.stdout + result.stderr).lower()
    assert "uv" in combined or "missing" in combined or "error" in combined
