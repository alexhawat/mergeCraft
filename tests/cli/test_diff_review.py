"""Tests for offline diff materialization and ``mergecraft diff-review``."""

from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.offline_review import build_offline_review_prompt
from mergecraft.utils.offline_diff import materialize_diff, summarize_diff

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip Rich/ANSI markup so option names like ``--base`` match literally."""
    return _ANSI.sub("", text)


def test_cli_diff_review_help() -> None:
    result = runner.invoke(app, ["diff-review", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    assert result.exit_code == 0
    out = _plain(result.stdout)
    assert "offline" in out.lower() or "diff" in out.lower()
    assert "--base" in out
    assert "--dry-run" in out


def test_cli_review_help_includes_examples() -> None:
    result = runner.invoke(app, ["review", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    assert result.exit_code == 0
    out = _plain(result.stdout)
    assert "No flags are required" in out
    assert "mergecraft review --dry-run" in out
    assert "mergecraft review --base origin/main" in out
    assert "mergecraft review --cwd ../feature-wt --base origin/main" in out
    assert "mergecraft review --head HEAD --base origin/pre-0.0.1" in out
    assert "mergecraft review --repo owner/repo --head pull/42/head --base main" in out
    assert "gh pr checkout 42" in out
    assert "gh pr diff 42 > /tmp/pr-42.diff" in out
    assert "mergecraft review --diff /tmp/pr-42.diff" in out
    assert "--head" in out
    assert "pull/42/head" in out


def test_cli_help_lists_review() -> None:
    result = runner.invoke(app, ["--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    assert result.exit_code == 0
    out = _plain(result.stdout)
    assert "review" in out
    assert "diff-review" not in out


def test_summarize_diff_lists_paths() -> None:
    text = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
        "diff --git a/bar.py b/bar.py\n"
        "--- a/bar.py\n"
        "+++ b/bar.py\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )
    summary = summarize_diff(text)
    assert "2 file" in summary
    assert "foo.py" in summary
    assert "bar.py" in summary


def test_materialize_diff_from_file(tmp_path: Path) -> None:
    patch = tmp_path / "in.diff"
    patch.write_text("diff --git a/a b/a\n+hello\n", encoding="utf-8")
    out = tmp_path / "out"
    result = materialize_diff(cwd=tmp_path, out_dir=out, diff_file=patch)
    assert result.path.is_file()
    assert result.empty is False
    assert result.base_ref is None
    assert "hello" in result.path.read_text(encoding="utf-8")


def test_materialize_empty_diff_file(tmp_path: Path) -> None:
    patch = tmp_path / "empty.diff"
    patch.write_text("", encoding="utf-8")
    result = materialize_diff(cwd=tmp_path, out_dir=tmp_path / "o", diff_file=patch)
    assert result.empty is True


def test_build_offline_review_prompt_forbids_github_tools(tmp_path: Path) -> None:
    diff_path = tmp_path / "review.diff"
    diff_path.write_text("diff --git a/x b/x\n+1\n", encoding="utf-8")
    prompt = build_offline_review_prompt(diff_path=diff_path, base_ref="origin/main")
    assert "create_pull_request_review" in prompt
    assert "select_mode" in prompt
    assert str(diff_path) in prompt
    assert "origin/main" in prompt


def test_cli_diff_review_dry_run_with_patch(tmp_path: Path) -> None:
    patch = tmp_path / "change.diff"
    patch.write_text(
        "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["diff-review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    out = _plain(result.stdout + result.stderr)
    assert "offline" in out.lower()
    assert "Review" in out
    assert "demo.py" in out


def test_cli_diff_review_empty_patch(tmp_path: Path) -> None:
    patch = tmp_path / "empty.diff"
    patch.write_text("\n", encoding="utf-8")
    result = runner.invoke(
        app,
        ["diff-review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "empty" in _plain(result.stdout + result.stderr).lower()
