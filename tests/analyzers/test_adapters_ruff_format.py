"""#268 — the ruff-format finding must cite the file that would reformat.

``_run_ruff_format_check`` (``analyzers/adapters.py:85-148``) runs
``ruff format --check`` over every scoped file in one invocation. Attribution
must follow the files ruff actually names: emitting a single finding hard-coded
to ``scoped_files[0]`` points the reviewer at a file that is already clean
whenever the unformatted file is not the first one.

These cases pin the **attribution contract**, not an implementation strategy.
The stub below decides its verdict from the file paths in ``plan.argv``, so it
answers correctly whether the adapter parses the ``Would reformat:`` lines of a
single combined invocation or runs ``ruff format --check`` once per file. It
emits paths in both absolute and repo-relative form (real ruff does both,
depending on how the path was passed) so neither strategy may assume one.

The final section pins the *other* exit: a non-zero exit carrying no parseable
``Would reformat:`` line at all — a genuine tool failure — where the adapter
falls back to ``scoped_files[0]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers import adapters
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import AnalyzerOutcome

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

FIRST = "pkg/a.py"
SECOND = "pkg/b.py"


def _repo(tmp_path: Path, *rel_paths: str) -> Path:
    repo_root = tmp_path / "repo"
    for rel in rel_paths:
        target = repo_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x  =  1\n", encoding="utf-8")
    return repo_root.resolve()


def _stub_run_plan(*, repo_root: Path, would_reformat: list[str], emit_absolute: bool) -> Any:
    """Answer like ``ruff format --check`` for whichever files this call passed."""

    def _run_plan(plan: AnalyzerPlan, *, sandbox_context: object = None) -> AnalyzerOutcome:
        _ = sandbox_context
        targets = [
            rel
            for rel in would_reformat
            if str((repo_root / rel).resolve()) in plan.argv or rel in plan.argv
        ]
        if not targets:
            return AnalyzerOutcome(
                name=plan.manifest_id,
                command="ruff format --check",
                status="passed",
                output="",
                exit_code=0,
            )
        shown = [str((repo_root / rel).resolve()) if emit_absolute else rel for rel in targets]
        listed = "\n".join(f"Would reformat: {path}" for path in shown)
        plural = "s" if len(targets) != 1 else ""
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command="ruff format --check",
            status="failed",
            output=f"{listed}\n{len(targets)} file{plural} would be reformatted\n",
            exit_code=1,
        )

    return _run_plan


def _format_findings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    repo_root: Path,
    scoped_files: list[str],
    would_reformat: list[str],
    emit_absolute: bool = False,
) -> list[Finding]:
    monkeypatch.setattr(
        adapters,
        "run_plan",
        _stub_run_plan(
            repo_root=repo_root,
            would_reformat=would_reformat,
            emit_absolute=emit_absolute,
        ),
    )
    plan = AnalyzerPlan(manifest_id="ruff", mode="repo-native", argv=("ruff", "check"))
    findings: list[Finding] = adapters._run_ruff_format_check(
        plan,
        manifest=get_manifest("ruff"),
        repo_root=repo_root,
        scoped_files=scoped_files,
        tier="trusted",
        sandbox_context=None,
    )
    return findings


def _paths(findings: list[Finding]) -> list[str]:
    """Findings are repo-relative by the time they leave the adapter.

    Asserted raw rather than re-normalised through the adapter's own helper, so
    an implementation that leaked absolute paths would fail here.
    """
    return sorted(f.path for f in findings)


# --------------------------------------------------------------------------- #
# The bug — multi-file attribution
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("emit_absolute", [False, True])
def test_only_the_second_file_reformatting_cites_the_second_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, emit_absolute: bool
) -> None:
    repo_root = _repo(tmp_path, FIRST, SECOND)
    findings = _format_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        would_reformat=[SECOND],
        emit_absolute=emit_absolute,
    )
    assert _paths(findings) == [SECOND]


@pytest.mark.parametrize("emit_absolute", [False, True])
def test_both_files_reformatting_yield_one_finding_each(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, emit_absolute: bool
) -> None:
    repo_root = _repo(tmp_path, FIRST, SECOND)
    findings = _format_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        would_reformat=[FIRST, SECOND],
        emit_absolute=emit_absolute,
    )
    assert _paths(findings) == [FIRST, SECOND]


@pytest.mark.parametrize("emit_absolute", [False, True])
def test_third_file_reformatting_is_not_attributed_to_the_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, emit_absolute: bool
) -> None:
    third = "pkg/c.py"
    repo_root = _repo(tmp_path, FIRST, SECOND, third)
    findings = _format_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND, third],
        would_reformat=[third],
        emit_absolute=emit_absolute,
    )
    assert _paths(findings) == [third]


# --------------------------------------------------------------------------- #
# Regression guards — shapes that already work must keep working
# --------------------------------------------------------------------------- #


def test_first_of_two_files_reformatting_cites_the_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The one multi-file case the hard-coded index got right by luck."""
    repo_root = _repo(tmp_path, FIRST, SECOND)
    findings = _format_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        would_reformat=[FIRST],
    )
    assert _paths(findings) == [FIRST]


def test_single_file_run_still_reports_that_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = _repo(tmp_path, SECOND)
    findings = _format_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[SECOND],
        would_reformat=[SECOND],
    )
    assert _paths(findings) == [SECOND]


def test_clean_run_reports_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = _repo(tmp_path, FIRST, SECOND)
    findings = _format_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        would_reformat=[],
    )
    assert findings == []


def test_no_scoped_files_reports_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    repo_root = _repo(tmp_path)
    repo_root.mkdir(parents=True, exist_ok=True)
    findings = _format_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[],
        would_reformat=[],
    )
    assert findings == []


def test_format_finding_metadata_is_stable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Attribution moved; the catalog-facing shape stays put (D19)."""
    repo_root = _repo(tmp_path, SECOND)
    findings = _format_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[SECOND],
        would_reformat=[SECOND],
    )
    assert len(findings) == 1
    finding = findings[0]
    assert finding.tool == "ruff"
    assert finding.rule_id == "format"
    assert finding.start_line == 1
    assert finding.end_line == 1
    assert "ruff format" in finding.message


# --------------------------------------------------------------------------- #
# Tool failure — the unparseable-output fallback
#
# A non-zero exit carrying no ``Would reformat:`` line at all means ruff itself
# failed (bad config, syntax error, unexpected output format), not that a file
# is unformatted. The adapter reports one finding at ``scoped_files[0]`` rather
# than returning nothing, so a broken analyzer cannot read as a clean bill of
# health.
#
# ``scoped_files[0]`` is the exact misattribution #268 exists to fix, so the
# reachability guard below is load-bearing: this arm may be entered **only**
# when no ``Would reformat:`` line parses. A refactor that regressed #268 by
# routing parseable output back through the fallback fails
# ``test_fallback_is_unreachable_while_would_reformat_lines_parse``.
# --------------------------------------------------------------------------- #

RUFF_INVOCATION_ERROR = (
    f"error: Failed to parse {FIRST}:1:1: Expected an expression\nerror: Failed to format 1 file\n"
)


def _stub_failing_run_plan(output: str) -> Any:
    """Answer every invocation with a non-zero exit and fixed output."""

    def _run_plan(plan: AnalyzerPlan, *, sandbox_context: object = None) -> AnalyzerOutcome:
        _ = sandbox_context
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command="ruff format --check",
            status="failed",
            output=output,
            exit_code=2,
        )

    return _run_plan


def _failing_findings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    repo_root: Path,
    scoped_files: list[str],
    output: str,
) -> list[Finding]:
    monkeypatch.setattr(adapters, "run_plan", _stub_failing_run_plan(output))
    plan = AnalyzerPlan(manifest_id="ruff", mode="repo-native", argv=("ruff", "check"))
    findings: list[Finding] = adapters._run_ruff_format_check(
        plan,
        manifest=get_manifest("ruff"),
        repo_root=repo_root,
        scoped_files=scoped_files,
        tier="trusted",
        sandbox_context=None,
    )
    return findings


@pytest.mark.parametrize(
    "output",
    [
        pytest.param(RUFF_INVOCATION_ERROR, id="invocation-error"),
        pytest.param("", id="no-output"),
        pytest.param("2 files would be reformatted\n", id="summary-line-only"),
    ],
)
def test_tool_failure_without_parseable_output_reports_the_first_scoped_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, output: str
) -> None:
    """False positive beats false silence when ruff itself fails."""
    repo_root = _repo(tmp_path, FIRST, SECOND)
    findings = _failing_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        output=output,
    )
    assert _paths(findings) == [FIRST]


def test_fallback_is_unreachable_while_would_reformat_lines_parse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Tool-failure noise around a parseable line must not reach the fallback.

    The failure output names ``pkg/a.py`` in its error text and exits 2, yet a
    single ``Would reformat:`` line names ``pkg/b.py``. Attribution follows the
    parsed line, so #268 cannot regress through the fallback arm.
    """
    repo_root = _repo(tmp_path, FIRST, SECOND)
    findings = _failing_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        output=f"{RUFF_INVOCATION_ERROR}Would reformat: {SECOND}\n",
    )
    assert _paths(findings) == [SECOND]


def test_tool_failure_with_no_scoped_files_reports_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """There is no first file to fall back to — the arm must not index into it."""
    repo_root = _repo(tmp_path)
    repo_root.mkdir(parents=True, exist_ok=True)
    findings = _failing_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[],
        output=RUFF_INVOCATION_ERROR,
    )
    assert findings == []


def test_tool_failure_fallback_reports_exactly_one_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One failure signal, not one per scoped file — three files, one finding."""
    third = "pkg/c.py"
    repo_root = _repo(tmp_path, FIRST, SECOND, third)
    findings = _failing_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND, third],
        output=RUFF_INVOCATION_ERROR,
    )
    assert len(findings) == 1
