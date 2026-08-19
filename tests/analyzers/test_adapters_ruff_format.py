"""#268 — the ruff-format finding must cite the file that would reformat.

``_run_ruff_format_check`` (``analyzers/adapters.py:85-119``) runs
``ruff format --check`` over every scoped file in one invocation, then, on a
non-zero exit, emits a single finding hard-coded to ``scoped_files[0]``. With
two scoped files where only the second is unformatted, the reviewer is pointed
at a file that is already clean.

These cases pin the **attribution contract**, not an implementation strategy.
The stub below decides its verdict from the file paths in ``plan.argv``, so it
answers correctly whether W13 parses the ``Would reformat:`` lines of the single
combined invocation or falls back to one ``ruff format --check`` run per file.
It emits paths in both absolute and repo-relative form (real ruff does both,
depending on how the path was passed) so neither W13 strategy may assume one.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers import adapters
from mergecraft.analyzers.parsers._common import resolve_repo_relative_path
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


def _paths(findings: list[Finding], *, repo_root: Path) -> list[str]:
    """Findings are repo-relative by the time they leave the adapter."""
    return sorted(resolve_repo_relative_path(f.path, repo_root=repo_root) for f in findings)


# --------------------------------------------------------------------------- #
# The bug — multi-file attribution
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("emit_absolute", [False, True])
@pytest.mark.xfail(
    reason="green after W13: ruff-format finding is hard-coded to scoped_files[0] (#268)",
    strict=False,
)
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
    assert _paths(findings, repo_root=repo_root) == [SECOND]


@pytest.mark.parametrize("emit_absolute", [False, True])
@pytest.mark.xfail(
    reason="green after W13: one finding per reformatting file (#268, W13.1)",
    strict=False,
)
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
    assert _paths(findings, repo_root=repo_root) == [FIRST, SECOND]


@pytest.mark.parametrize("emit_absolute", [False, True])
@pytest.mark.xfail(
    reason="green after W13: a clean middle file must not absorb the finding (#268)",
    strict=False,
)
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
    assert _paths(findings, repo_root=repo_root) == [third]


# --------------------------------------------------------------------------- #
# Regression guards — shapes that already work must keep working
# --------------------------------------------------------------------------- #


def test_first_of_two_files_reformatting_cites_the_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The one multi-file case today gets right — W13 must not lose it."""
    repo_root = _repo(tmp_path, FIRST, SECOND)
    findings = _format_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        would_reformat=[FIRST],
    )
    assert _paths(findings, repo_root=repo_root) == [FIRST]


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
    assert _paths(findings, repo_root=repo_root) == [SECOND]


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
    """W13 changes attribution only — the catalog-facing shape stays put (D19)."""
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
