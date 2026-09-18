"""TTY interactive sessions for bare mergeCraft commands."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import typer
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.cli.interactive import (
    ReviewWizardChoice,
    command_was_invoked_bare,
    is_interactive_session,
    prompt_choice,
    run_review_wizard,
)
from mergecraft.offline_review import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_FORCE = {
    "NO_COLOR": "1",
    "TERM": "dumb",
    "MERGECRAFT_FORCE_INTERACTIVE": "1",
    "CI": "",
}


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def test_is_interactive_session_respects_ci_and_overrides() -> None:
    assert is_interactive_session(env={"CI": "true"}, stdin=_Tty()) is False
    assert is_interactive_session(env={"MERGECRAFT_NONINTERACTIVE": "1"}, stdin=_Tty()) is False
    assert (
        is_interactive_session(env={"MERGECRAFT_FORCE_INTERACTIVE": "1"}, stdin=_NotTty()) is True
    )
    assert is_interactive_session(env={}, stdin=_Tty()) is True
    assert is_interactive_session(env={}, stdin=_NotTty()) is False


class _Tty:
    def isatty(self) -> bool:
        return True


class _NotTty:
    def isatty(self) -> bool:
        return False


def test_bare_mergecraft_without_tty_prints_help() -> None:
    result = runner.invoke(app, [], env={"NO_COLOR": "1", "TERM": "dumb", "CI": "1"})
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert "review" in output
    assert "interactive session" not in output.lower()


def test_bare_mergecraft_interactive_lists_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mergecraft.cli.interactive.is_interactive_session", lambda: True)
    monkeypatch.setattr(
        "mergecraft.cli.interactive.typer.prompt",
        lambda *_a, **_kw: "0",
    )
    result = runner.invoke(app, [], env=_FORCE)
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "interactive session" in output
    assert "review" in output
    assert "canceled" in output


def test_provider_without_tty_prints_help() -> None:
    result = runner.invoke(app, ["provider"], env={"NO_COLOR": "1", "TERM": "dumb", "CI": "1"})
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == 0, output
    assert "list" in output
    assert "auth" in output
    assert "interactive session" not in output


def test_provider_interactive_can_run_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mergecraft.cli.interactive.is_interactive_session", lambda: True)

    def _choose(title: str, options: list[tuple[str, str]], default_index: int = 1) -> int:
        names = [label for label, _detail in options]
        assert "list" in names
        return names.index("list") + 1

    monkeypatch.setattr("mergecraft.cli.interactive.prompt_choice", _choose)
    result = runner.invoke(app, ["provider"], env=_FORCE)
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "no providers" in output or "label" in output or output == ""


def test_analyzers_run_prompts_for_missing_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mergecraft.cli.interactive.is_interactive_session", lambda: True)
    prompted: list[str] = []

    def _prompt(message: str, **kwargs: Any) -> str:
        prompted.append(str(message))
        return "ruff"

    monkeypatch.setattr("mergecraft.cli.interactive.typer.prompt", _prompt)
    result = runner.invoke(app, ["analyzers", "run"], env=_FORCE)
    output = _plain(result.stdout + result.stderr).lower()
    assert prompted, output
    assert "missing argument" not in output
    assert "unknown analyzer" in output or "no changed files" in output or result.exit_code != 0


def test_review_help_mentions_interactive_tty() -> None:
    result = runner.invoke(app, ["review", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    output = " ".join(_plain(result.stdout).split())
    assert result.exit_code == 0
    assert "No flags are required" in output
    assert "interactive" in output
    assert "session" in output


def test_review_skips_wizard_when_flag_passed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wizard_called = {"value": False}

    def _wizard() -> ReviewWizardChoice:
        wizard_called["value"] = True
        return ReviewWizardChoice(dry_run=True)

    monkeypatch.setattr("mergecraft.cli.interactive.run_review_wizard", _wizard)
    monkeypatch.setattr("mergecraft.cli.interactive.is_interactive_session", lambda: True)
    patch = tmp_path / "change.diff"
    patch.write_text(
        "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n",
        encoding="utf-8",
    )

    async def _fake_run(**kwargs: object) -> OfflineReviewResult:
        return OfflineReviewResult(success=True, output="ok", outcome=RunOutcome.passed)

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        _fake_run,
    )
    result = runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env=_FORCE,
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert wizard_called["value"] is False


def test_review_wizard_sets_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    patch = tmp_path / "change.diff"
    patch.write_text(
        "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("mergecraft.cli.interactive.is_interactive_session", lambda: True)
    monkeypatch.setattr("mergecraft.cli.interactive.command_was_invoked_bare", lambda _ctx: True)
    monkeypatch.setattr(
        "mergecraft.cli.interactive.run_review_wizard",
        lambda: ReviewWizardChoice(dry_run=True, diff=patch),
    )

    async def _fake_run(**kwargs: object) -> OfflineReviewResult:
        seen.update(kwargs)
        return OfflineReviewResult(success=True, output="prompt", outcome=RunOutcome.passed)

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        _fake_run,
    )
    result = runner.invoke(app, ["review"], env=_FORCE)
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    assert seen.get("dry_run") is True
    assert seen.get("diff_file") == patch


def test_run_review_wizard_collects_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["1", "1", "2", "1", ""])

    def _prompt(message: str, **kwargs: Any) -> str:
        return next(answers)

    monkeypatch.setattr("mergecraft.cli.interactive.typer.prompt", _prompt)
    monkeypatch.setattr("mergecraft.cli.interactive.typer.confirm", lambda *_a, **_kw: True)
    choice = run_review_wizard()
    assert choice.dry_run is True
    assert choice.repo is None
    assert choice.diff is None
    assert choice.agent_mode is False


def test_prompt_choice_cancels_on_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mergecraft.cli.interactive.typer.prompt", lambda *_a, **_kw: "0")
    with pytest.raises(typer.Exit) as exited:
        prompt_choice("Title", (("one", "detail"),))
    assert exited.value.exit_code == CLI_SUCCESS_EXIT_CODE


def test_config_set_writes_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["config", "set", "models", "anthropic/claude-sonnet,openai/gpt-5.3-codex"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    written = (tmp_path / ".mergecraft" / "config.yaml").read_text(encoding="utf-8")
    assert "anthropic/claude-sonnet" in written
    assert "openai/gpt-5.3-codex" in written


def test_config_set_rejects_unknown_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["config", "set", "not.a.key", "true"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code != 0, output
    assert "unsupported" in output


def test_command_was_invoked_bare_uses_parameter_source() -> None:
    class _Param:
        name = "dry_run"

    class _Cmd:
        def __init__(self) -> None:
            self.params = [_Param()]

    class _Ctx:
        command = _Cmd()

        def get_parameter_source(self, name: str) -> Any:
            return None

    assert command_was_invoked_bare(_Ctx()) is True  # type: ignore[arg-type]
