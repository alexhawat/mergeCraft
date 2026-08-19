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

import shutil
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


# --------------------------------------------------------------------------- #
# The ruff 0.16 diagnostic renderer
#
# ruff 0.16 stopped emitting ``Would reformat: <path>`` and routes
# ``format --check`` through the shared diagnostic renderer instead:
#
#     unformatted: File would be reformatted
#      --> pkg/b.py:1:6
#       |
#       - x  =  1
#     1 + x = 1
#       |
#
#     1 file would be reformatted
#
# The manifest pins 0.15.12 but declares ``runtime: repo-native``, so the
# reviewed repo's own ruff decides the format. Both spellings must parse.
#
# Attribution must follow the ``unformatted:`` header, **not** every ``-->``
# line: ``format --check`` also renders ``invalid-syntax:`` diagnostics with the
# same arrow, and those are tool failures, not unformatted files.
# --------------------------------------------------------------------------- #


def _diagnostic_block(path: str, *, rule: str, message: str) -> str:
    return f"{rule}: {message}\n --> {path}:1:6\n  |\n  - x  =  1\n1 + x = 1\n  |\n"


def _unformatted_block(path: str) -> str:
    return _diagnostic_block(path, rule="unformatted", message="File would be reformatted")


def _stub_diagnostic_run_plan(
    *, repo_root: Path, would_reformat: list[str], emit_absolute: bool
) -> Any:
    """Answer like ruff >= 0.16 ``format --check`` for whichever files this call passed."""

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
        blocks = "\n".join(_unformatted_block(path) for path in shown)
        plural = "s" if len(targets) != 1 else ""
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command="ruff format --check",
            status="failed",
            output=f"{blocks}\n{len(targets)} file{plural} would be reformatted\n",
            exit_code=1,
        )

    return _run_plan


@pytest.mark.parametrize("emit_absolute", [False, True])
def test_diagnostic_renderer_attributes_the_named_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, emit_absolute: bool
) -> None:
    """ruff >= 0.16 output must attribute to the file the arrow names."""
    repo_root = _repo(tmp_path, FIRST, SECOND)
    monkeypatch.setattr(
        adapters,
        "run_plan",
        _stub_diagnostic_run_plan(
            repo_root=repo_root,
            would_reformat=[SECOND],
            emit_absolute=emit_absolute,
        ),
    )
    plan = AnalyzerPlan(manifest_id="ruff", mode="repo-native", argv=("ruff", "check"))
    findings: list[Finding] = adapters._run_ruff_format_check(
        plan,
        manifest=get_manifest("ruff"),
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        tier="trusted",
        sandbox_context=None,
    )
    assert _paths(findings) == [SECOND]
    assert "ruff format" in findings[0].message


def test_diagnostic_renderer_attributes_every_named_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = _repo(tmp_path, FIRST, SECOND)
    monkeypatch.setattr(
        adapters,
        "run_plan",
        _stub_diagnostic_run_plan(
            repo_root=repo_root,
            would_reformat=[FIRST, SECOND],
            emit_absolute=False,
        ),
    )
    plan = AnalyzerPlan(manifest_id="ruff", mode="repo-native", argv=("ruff", "check"))
    findings: list[Finding] = adapters._run_ruff_format_check(
        plan,
        manifest=get_manifest("ruff"),
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        tier="trusted",
        sandbox_context=None,
    )
    assert _paths(findings) == [FIRST, SECOND]


def test_invalid_syntax_diagnostic_is_not_read_as_unformatted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``invalid-syntax:`` uses the same arrow but is a failure, not a reformat.

    Attributing it as "would be reformatted" would tell the reviewer to run
    ``ruff format`` on a file that ruff cannot even parse.
    """
    repo_root = _repo(tmp_path, FIRST, SECOND)
    findings = _failing_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        output=_diagnostic_block(SECOND, rule="invalid-syntax", message="Expected a parameter"),
    )
    assert _paths(findings) == [FIRST]
    assert "no parseable output" in findings[0].message


def test_mixed_diagnostics_attribute_only_the_unformatted_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One unformatted file plus one unparseable file — only the former is cited."""
    repo_root = _repo(tmp_path, FIRST, SECOND)
    findings = _failing_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        output=(
            f"{_unformatted_block(SECOND)}\n"
            f"{_diagnostic_block(FIRST, rule='invalid-syntax', message='Expected a parameter')}"
            "\n1 file would be reformatted\n"
        ),
    )
    assert _paths(findings) == [SECOND]


def test_ansi_coloured_diagnostic_output_still_parses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ruff colours its renderer whenever ``FORCE_COLOR`` is set in the env.

    ``build_analyzer_env`` inherits the host environment, so the analyzer
    subprocess sees whatever the CI runner exported. A parser that matched raw
    text would silently stop finding anything on a colour-forcing runner.
    """
    repo_root = _repo(tmp_path, FIRST, SECOND)
    coloured = (
        "\x1b[1m\x1b[91munformatted:\x1b[0m\x1b[1m File would be reformatted\x1b[0m\n"
        f" \x1b[1m\x1b[94m--> \x1b[0m{SECOND}:1:6\n"
        "\x1b[1m\x1b[94m \x1b[0m \x1b[1m\x1b[94m|\x1b[0m\n"
    )
    findings = _failing_findings(
        monkeypatch,
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        output=coloured,
    )
    assert _paths(findings) == [SECOND]


# --------------------------------------------------------------------------- #
# L8 — an analyzer that never ran is a skip, never a finding
#
# ``run_analyzers`` (``mcp/analyzers.py``) is explicit: "unavailable means the
# tool did not run here" and must be reported as skipped, "never as a finding."
# The main analyzer path honours that; the format sub-run must too.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", ["unavailable", "declared-but-cannot-run"])
def test_format_sub_run_that_did_not_run_reports_no_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str
) -> None:
    """A sandbox refusal or a ruff too old for ``format --check`` is a skip."""
    repo_root = _repo(tmp_path, FIRST, SECOND)

    def _run_plan(plan: AnalyzerPlan, *, sandbox_context: object = None) -> AnalyzerOutcome:
        _ = sandbox_context
        return AnalyzerOutcome(
            name=plan.manifest_id,
            command="ruff format --check",
            status=status,  # type: ignore[arg-type]
            output="not installed in this environment",
            exit_code=None,
        )

    monkeypatch.setattr(adapters, "run_plan", _run_plan)
    plan = AnalyzerPlan(manifest_id="ruff", mode="repo-native", argv=("ruff", "check"))
    findings: list[Finding] = adapters._run_ruff_format_check(
        plan,
        manifest=get_manifest("ruff"),
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        tier="trusted",
        sandbox_context=None,
    )
    assert findings == []


# --------------------------------------------------------------------------- #
# The real tool contract
#
# Every case above fabricates ruff's output, which is exactly how the 0.16
# renderer change went unnoticed. This case runs the repo's own ruff so the
# parser is pinned against the binary rather than against a string literal.
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not on PATH")
def test_real_ruff_format_check_attributes_the_unformatted_file(tmp_path: Path) -> None:
    """Run the real binary: only the unformatted file may be cited."""
    repo_root = (tmp_path / "repo").resolve()
    (repo_root / "pkg").mkdir(parents=True)
    (repo_root / FIRST).write_text("x = 1\n", encoding="utf-8")
    (repo_root / SECOND).write_text('y = {  "a":1,\n  "b" : 2}\n', encoding="utf-8")

    binary = shutil.which("ruff")
    assert binary is not None
    plan = AnalyzerPlan(manifest_id="ruff", mode="repo-native", argv=(binary, "check"))
    findings: list[Finding] = adapters._run_ruff_format_check(
        plan,
        manifest=get_manifest("ruff"),
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        tier="trusted",
        sandbox_context=None,
    )
    assert _paths(findings) == [SECOND]
    assert findings[0].message == "File would be reformatted by ruff format"


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not on PATH")
def test_real_ruff_format_check_on_formatted_files_reports_nothing(tmp_path: Path) -> None:
    repo_root = (tmp_path / "repo").resolve()
    (repo_root / "pkg").mkdir(parents=True)
    (repo_root / FIRST).write_text("x = 1\n", encoding="utf-8")
    (repo_root / SECOND).write_text("y = 2\n", encoding="utf-8")

    binary = shutil.which("ruff")
    assert binary is not None
    plan = AnalyzerPlan(manifest_id="ruff", mode="repo-native", argv=(binary, "check"))
    findings: list[Finding] = adapters._run_ruff_format_check(
        plan,
        manifest=get_manifest("ruff"),
        repo_root=repo_root,
        scoped_files=[FIRST, SECOND],
        tier="trusted",
        sandbox_context=None,
    )
    assert findings == []
