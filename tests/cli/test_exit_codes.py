"""CC1 — CLI exit codes for review outcomes (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Pins the closed ``RunOutcome`` taxonomy → distinct process exit codes on the
``review`` / ``diff-review`` verbs. Authoring wave: **CC1.1** (RED).
Implementation: **CC1.2**.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from tests.analyzers.support import import_module as import_analyzer_module
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.offline_review import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _run_outcome_mod() -> Any:
    return import_analyzer_module("mergecraft.run_outcome")


def _exit_code_for_outcome() -> Any:
    mod = _run_outcome_mod()
    fn = getattr(mod, "exit_code_for_outcome", None)
    if fn is None:
        pytest.fail("exit_code_for_outcome not defined in mergecraft.run_outcome")
    return fn


def _run_outcome_exit_table() -> dict[RunOutcome, int]:
    mod = _run_outcome_mod()
    table = getattr(mod, "RUN_OUTCOME_EXIT_CODE", None)
    if table is None:
        pytest.fail("RUN_OUTCOME_EXIT_CODE not defined in mergecraft.run_outcome")
    return table


def _minor_finding_dict() -> dict[str, object]:
    finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="analyzer",
        introduced_by_pr="unknown",
    )
    return finding.model_dump()


def _blocker_finding_dict() -> dict[str, object]:
    finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="mergecraft",
        rule_id="SEC-001",
        category="Security & Privacy",
        severity="Critical",
        confidence="certain",
        message="hard blocker",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="unknown",
    )
    return finding.model_dump()


def _patch_offline_review(
    monkeypatch: pytest.MonkeyPatch,
    *,
    outcome: RunOutcome,
    findings: list[dict[str, object]] | None = None,
    success: bool = True,
    error: str | None = None,
) -> None:
    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        materialization_path = kwargs.get("diff_file")
        diff_path = str(materialization_path) if materialization_path else None
        structured = json.dumps({"findings": findings or []}) if findings else None
        return OfflineReviewResult(
            success=success and outcome is RunOutcome.passed,
            output="# Review\n\nDone.",
            structured_output=structured,
            diff_path=diff_path,
            outcome=outcome,
            error=error,
        )

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )


def _invoke_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    return runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path)],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )


def test_clean_review_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean review (``passed``, no findings) exits 0."""
    _patch_offline_review(monkeypatch, outcome=RunOutcome.passed, findings=[])
    result = _invoke_review(tmp_path, monkeypatch)
    assert result.exit_code == 0, _plain(result.stdout + result.stderr)


def test_findings_exit_code_distinct_from_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-blocking findings yield an exit code distinct from a clean pass."""
    _patch_offline_review(
        monkeypatch,
        outcome=RunOutcome.passed,
        findings=[_minor_finding_dict()],
    )
    result = _invoke_review(tmp_path, monkeypatch)
    clean_code = _exit_code_for_outcome()(RunOutcome.passed)
    assert result.exit_code != clean_code, _plain(result.stdout + result.stderr)
    assert result.exit_code == _exit_code_for_outcome()(RunOutcome.failed)


def test_blocked_exit_code_distinct_from_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blocking severities yield an exit code distinct from non-blocking findings."""
    _patch_offline_review(
        monkeypatch,
        outcome=RunOutcome.failed,
        findings=[_blocker_finding_dict()],
        success=False,
        error="blocking findings",
    )
    result = _invoke_review(tmp_path, monkeypatch)
    findings_only = _exit_code_for_outcome()(RunOutcome.failed, blocked=False)
    blocked = _exit_code_for_outcome()(RunOutcome.failed, blocked=True)
    assert blocked != findings_only
    assert result.exit_code == blocked, _plain(result.stdout + result.stderr)


def test_inconclusive_exit_code_distinct(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``RunOutcome.inconclusive`` maps to a distinct exit code."""
    _patch_offline_review(
        monkeypatch,
        outcome=RunOutcome.inconclusive,
        success=False,
        error="no verdict",
    )
    result = _invoke_review(tmp_path, monkeypatch)
    code = _exit_code_for_outcome()(RunOutcome.inconclusive)
    assert code != _exit_code_for_outcome()(RunOutcome.passed)
    assert result.exit_code == code, _plain(result.stdout + result.stderr)


def test_config_error_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``RunOutcome.configuration_error`` maps to a distinct exit code."""
    _patch_offline_review(
        monkeypatch,
        outcome=RunOutcome.configuration_error,
        success=False,
        error="bad config",
    )
    result = _invoke_review(tmp_path, monkeypatch)
    assert result.exit_code == _exit_code_for_outcome()(RunOutcome.configuration_error)


def test_infra_error_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``RunOutcome.infra_error`` maps to a distinct exit code."""
    _patch_offline_review(
        monkeypatch,
        outcome=RunOutcome.infra_error,
        success=False,
        error="infra blew up",
    )
    result = _invoke_review(tmp_path, monkeypatch)
    assert result.exit_code == _exit_code_for_outcome()(RunOutcome.infra_error)


def test_timeout_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``RunOutcome.timed_out`` maps to a distinct exit code."""
    _patch_offline_review(
        monkeypatch,
        outcome=RunOutcome.timed_out,
        success=False,
        error="timed out",
    )
    result = _invoke_review(tmp_path, monkeypatch)
    assert result.exit_code == _exit_code_for_outcome()(RunOutcome.timed_out)


def test_every_run_outcome_has_exactly_one_exit_code() -> None:
    """Total mapping pin — each ``RunOutcome`` has one distinct exit code."""
    table = _run_outcome_exit_table()
    assert set(table) == set(RunOutcome)
    values = list(table.values())
    assert len(values) == len(set(values))
