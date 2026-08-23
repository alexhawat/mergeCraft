"""CB #451 RED — ``mergecraft review --output-format hunk`` (D3).

Pins stdout-only Hunk JSON piping, structured-findings wiring, and stderr warnings
for dropped file-level findings. No subprocess / Hunk dependency.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from tests.analyzers.support import import_module as import_analyzer_module
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.offline_review import OfflineReviewResult

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n"
    "--- a/demo.py\n"
    "+++ b/demo.py\n"
    "@@ -0,0 +1,3 @@\n"
    "+import os\n"
    "+print(os.getcwd())\n"
    "+# tail\n"
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _line_finding_dict(**overrides: object) -> dict[str, object]:
    finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import os",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="analyzer",
        introduced_by_pr="unknown",
        **overrides,
    )
    return finding.model_dump()


def _file_level_finding_dict(**overrides: object) -> dict[str, object]:
    return _line_finding_dict(start_line=None, end_line=None, path="README.md", **overrides)


def _review_argv(tmp_path: Path, *extra: str) -> list[str]:
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    return ["review", "--diff", str(patch), "--cwd", str(tmp_path), *extra]


def _install_fake_review(
    monkeypatch: pytest.MonkeyPatch,
    *,
    findings: list[dict[str, object]],
) -> None:
    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        materialization_path = kwargs.get("diff_file")
        diff_path = str(materialization_path) if materialization_path else None
        payload = json.dumps({"findings": findings})
        json_path = kwargs.get("json_path")
        if json_path is not None:
            await asyncio.to_thread(Path(str(json_path)).write_text, payload, encoding="utf-8")
        return OfflineReviewResult(
            success=True,
            output="# Review\n\nWith findings.",
            structured_output=payload,
            diff_path=diff_path,
        )

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )


@pytest.mark.xfail(reason="green after CB", strict=False)
def test_hunk_output_format_writes_json_to_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3 — Hunk payload is emitted on stdout for shell piping."""
    _install_fake_review(monkeypatch, findings=[_line_finding_dict()])
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--output-format", "hunk"),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    payload = json.loads(result.stdout)
    assert isinstance(payload.get("comments"), list)
    assert payload["comments"], combined
    assert payload["comments"][0]["filePath"] == "demo.py"


@pytest.mark.xfail(reason="green after CB", strict=False)
def test_hunk_output_format_does_not_require_output_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D3 — unlike sarif/jsonl, hunk format is stdout-only (no ``--output`` requirement)."""
    _install_fake_review(monkeypatch, findings=[_line_finding_dict()])
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--output-format", "hunk"),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    assert "--output is required" not in combined.lower()
    assert json.loads(result.stdout)["comments"]


@pytest.mark.xfail(reason="green after CB", strict=False)
def test_hunk_output_format_warns_about_dropped_file_level_on_stderr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default drop mode surfaces a counted warning on stderr, not stdout."""
    _install_fake_review(
        monkeypatch,
        findings=[_file_level_finding_dict(), _line_finding_dict()],
    )
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--output-format", "hunk"),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    payload = json.loads(result.stdout)
    assert len(payload["comments"]) == 1
    stderr = _plain(result.stderr)
    assert "file-level" in stderr.casefold()
    assert "not exportable" in stderr.casefold()
    assert re.search(r"\b1\b", stderr)


@pytest.mark.xfail(reason="green after CB", strict=False)
def test_hunk_output_format_requests_structured_findings_from_run_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--output-format hunk`` threads ``json_path`` so agent findings are available."""
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> OfflineReviewResult:
        captured["kwargs"] = kwargs
        finding = _line_finding_dict()
        payload = json.dumps({"findings": [finding]})
        json_path = kwargs.get("json_path")
        if json_path is not None:
            await asyncio.to_thread(Path(str(json_path)).write_text, payload, encoding="utf-8")
        return OfflineReviewResult(
            success=True,
            output="# Review\n\nWith findings.",
            structured_output=payload,
            diff_path=str(kwargs.get("diff_file")) if kwargs.get("diff_file") else None,
        )

    monkeypatch.setattr("mergecraft.cli.diff_review_cmd.run_offline_diff_review", _capture_run)
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--output-format", "hunk"),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    sent_json_path = captured["kwargs"].get("json_path")  # type: ignore[union-attr]
    assert sent_json_path is not None, (
        f"--output-format hunk must request structured findings; got json_path={sent_json_path!r}"
    )


@pytest.mark.xfail(reason="green after CB", strict=False)
def test_hunk_file_findings_first_changed_line_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opt-in ``--hunk-file-findings first-changed-line`` exports file-level rows."""
    _install_fake_review(monkeypatch, findings=[_file_level_finding_dict(path="demo.py")])
    result = runner.invoke(
        app,
        _review_argv(
            tmp_path,
            "--output-format",
            "hunk",
            "--hunk-file-findings",
            "first-changed-line",
        ),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    comment = json.loads(result.stdout)["comments"][0]
    assert comment["filePath"] == "demo.py"
    assert comment["newLine"] == 1
    assert str(comment["summary"]).startswith("[file-level]")


@pytest.mark.xfail(reason="green after CB", strict=False)
def test_review_help_lists_hunk_output_format() -> None:
    """CLI surface documents the hunk exporter."""
    result = runner.invoke(app, ["review", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    assert result.exit_code == 0
    help_text = _plain(result.stdout)
    assert "hunk" in help_text.casefold()
