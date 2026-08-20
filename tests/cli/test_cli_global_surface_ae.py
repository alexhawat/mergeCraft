"""Batch AE RED — global CLI surface (#342).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20-wave-plan.md``
Authoring wave: **W10** (Batch AE RED). Implementation: **W11** (#342 root callback).

Pins (D12 / D13):
- Global ``--format {table,json}`` (not ``--output``) inherited by subcommands.
- Every JSON payload carries ``schema_version``.
- ``--quiet`` / ``--verbose`` / ``--log-level`` / ``MERGECRAFT_LOG_LEVEL`` adjust Loguru.
- ``--color {auto,always,never}`` plus ``NO_COLOR`` (any non-empty), ``FORCE_COLOR``,
  and non-TTY behaviour.
- ``review`` is the documented command; ``diff-review`` stays hidden and emits one stderr
  deprecation line when invoked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_CHROME_ENV = {"TERM": "xterm-256color"}
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)

_EXPECTED_ISSUES = [
    {"id": "x-1", "path": "src/app.py", "start_line": 10, "end_line": 12, "severity": "high"}
]
_ACTUAL_FINDINGS = [
    {
        "path": "src/app.py",
        "start_line": 11,
        "end_line": 11,
        "severity": "Major",
        "message": "totally different wording",
    }
]


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _has_ansi(text: str) -> bool:
    return bool(_ANSI.search(text))


def _write_json(tmp_path: Path, name: str, rows: list[dict[str, object]]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _eval_score_argv(tmp_path: Path, *extra: str) -> list[str]:
    actual = _write_json(tmp_path, "actual.json", _ACTUAL_FINDINGS)
    expected = _write_json(tmp_path, "expected.json", _EXPECTED_ISSUES)
    return ["eval", "score", str(actual), str(expected), *extra]


def _review_dry_run_argv(tmp_path: Path, *, command: str = "review") -> list[str]:
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    return [command, "--diff", str(patch), "--dry-run"]


def test_root_help_lists_global_format_flag() -> None:
    """D12 — root callback exposes ``--format {table,json}``."""
    result = runner.invoke(app, ["--help"], env=_DUMB_ENV)
    help_text = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == 0, help_text
    assert "--format" in help_text
    assert "table" in help_text
    assert "json" in help_text


@pytest.mark.parametrize("flag", ["--quiet", "--verbose", "--log-level", "--color"])
def test_root_help_lists_global_verbosity_and_color_flags(flag: str) -> None:
    """Root callback documents global verbosity, log-level, and color switches."""
    result = runner.invoke(app, ["--help"], env=_DUMB_ENV)
    help_text = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == 0, help_text
    assert flag in help_text


def test_root_help_does_not_use_output_as_global_format_switch() -> None:
    """D12 — global format is ``--format``, not a root-level ``--output`` switch."""
    result = runner.invoke(app, ["--help"], env=_DUMB_ENV)
    help_text = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, help_text
    assert "--output" not in help_text


def test_global_format_json_inherited_by_eval_score(tmp_path: Path) -> None:
    """Root ``--format json`` applies to subcommands without repeating per-command flags."""
    result = runner.invoke(
        app,
        ["--format", "json", *_eval_score_argv(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, combined
    payload = json.loads(result.stdout)
    assert payload["recall"] == 1.0


@pytest.mark.parametrize(
    ("use_global_format", "use_legacy_json_flag"),
    [
        pytest.param(True, False, id="global-format"),
        pytest.param(False, True, id="legacy-json-flag"),
    ],
)
def test_json_payload_includes_schema_version(
    tmp_path: Path,
    use_global_format: bool,
    use_legacy_json_flag: bool,
) -> None:
    """D12 — every CLI JSON payload carries a non-empty ``schema_version``."""
    argv = _eval_score_argv(tmp_path)
    if use_global_format:
        argv = ["--format", "json", *argv]
    if use_legacy_json_flag:
        argv = [*argv, "--json"]
    result = runner.invoke(app, argv, env=_DUMB_ENV)
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, combined
    payload = json.loads(result.stdout)
    schema_version = payload.get("schema_version")
    assert isinstance(schema_version, str)
    assert schema_version.strip()


@pytest.mark.parametrize(
    ("env", "extra"),
    [
        pytest.param({"NO_COLOR": "1", **_CHROME_ENV}, [], id="no-color-1"),
        pytest.param({"NO_COLOR": "0", **_CHROME_ENV}, [], id="no-color-any-nonempty"),
        pytest.param(_CHROME_ENV, ["--color", "never"], id="color-never"),
    ],
)
def test_color_contract_suppresses_ansi_in_help(env: dict[str, str], extra: list[str]) -> None:
    """``NO_COLOR`` (any non-empty) and ``--color never`` emit zero ANSI escapes."""
    result = runner.invoke(app, [*extra, "--help"], env=env)
    combined = result.stdout + result.stderr
    assert result.exit_code == 0, _plain(combined)
    assert not _has_ansi(combined)


def test_non_tty_emits_zero_ansi_in_help() -> None:
    """Non-interactive stdout/stderr must not carry Rich ANSI even with a colour TERM."""
    result = runner.invoke(app, ["--help"], env=_CHROME_ENV)
    combined = result.stdout + result.stderr
    assert result.exit_code == 0, _plain(combined)
    assert not _has_ansi(combined)


def test_force_color_enables_ansi_on_dumb_tty() -> None:
    """``FORCE_COLOR`` (any non-empty) re-enables ANSI when the sink is otherwise dumb."""
    result = runner.invoke(
        app,
        ["--help"],
        env={"FORCE_COLOR": "1", "TERM": "dumb"},
    )
    combined = result.stdout + result.stderr
    assert result.exit_code == 0, _plain(combined)
    assert _has_ansi(combined)


def test_log_level_debug_shows_init_debug_message() -> None:
    """``--log-level DEBUG`` reconfigures Loguru before subcommands run."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            ["--log-level", "DEBUG", "init"],
            env=_DUMB_ENV,
        )
        stderr = _plain(result.stderr)
        assert result.exit_code == 0, stderr
        assert "init complete at" in stderr


def test_quiet_suppresses_loguru_info_on_review_dry_run(tmp_path: Path) -> None:
    """``--quiet`` lowers Loguru verbosity for subcommand log lines."""
    result = runner.invoke(
        app,
        ["--quiet", *_review_dry_run_argv(tmp_path)],
        env={**_DUMB_ENV, "LOG_LEVEL": "INFO"},
    )
    stderr = _plain(result.stderr)
    assert result.exit_code == 0, stderr
    assert "» diff path:" not in stderr


def test_verbose_shows_loguru_debug_on_init() -> None:
    """``--verbose`` enables DEBUG Loguru records for subcommands."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            ["--verbose", "init"],
            env=_DUMB_ENV,
        )
        stderr = _plain(result.stderr)
        assert result.exit_code == 0, stderr
        assert "init complete at" in stderr


def test_mergecraft_log_level_env_overrides_default_quietness() -> None:
    """``MERGECRAFT_LOG_LEVEL`` is honoured by the root callback."""
    with runner.isolated_filesystem():
        result = runner.invoke(
            app,
            ["init"],
            env={**_DUMB_ENV, "MERGECRAFT_LOG_LEVEL": "DEBUG"},
        )
        stderr = _plain(result.stderr)
        assert result.exit_code == 0, stderr
        assert "init complete at" in stderr


def test_diff_review_hidden_alias_emits_one_stderr_deprecation_line(
    tmp_path: Path,
) -> None:
    """D13 — hidden ``diff-review`` prints exactly one stderr deprecation line per invocation."""
    result = runner.invoke(
        app,
        _review_dry_run_argv(tmp_path, command="diff-review"),
        env=_DUMB_ENV,
    )
    stderr = _plain(result.stderr)
    assert result.exit_code == 0, stderr
    deprecation_lines = [
        line
        for line in stderr.splitlines()
        if "deprecated" in line.lower() and "diff-review" in line.lower()
    ]
    assert len(deprecation_lines) == 1, stderr


def test_review_is_documented_and_diff_review_hidden_in_root_help() -> None:
    """D13 — ``review`` is visible in root help; ``diff-review`` stays hidden."""
    result = runner.invoke(app, ["--help"], env=_DUMB_ENV)
    help_text = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == 0, help_text
    assert "review" in help_text
    assert "diff-review" not in help_text
