"""Recall merge into analyzer run state (RC10, D1)."""

from __future__ import annotations

from mergecraft.analyzers.budget import DEFERRED_SECTION_HEADING
from mergecraft.mcp.convergence_runtime import merge_recall_findings_into_analyzer_run
from mergecraft.mcp.tool_state import AnalyzerRunState


def test_merge_recall_preserves_analyzer_overflow_in_deferred_section() -> None:
    """Recall merge must re-render deferred HTML from all deferred rows, not recall-only."""
    overflow_path = "src/overflow.py"
    overflow_body = "Analyzer overflow finding."
    recall_path = "src/recall.py"
    recall_body = "Novel recall finding."

    analyzer_run = AnalyzerRunState(
        ran=True,
        deferred_findings=[
            {
                "path": overflow_path,
                "line": 9,
                "body": overflow_body,
                "severity": "Major",
            }
        ],
        deferred_section=(
            f"{DEFERRED_SECTION_HEADING}\n\n"
            "<details><summary>Non-blocking deferred findings</summary>\n\n"
            f"**Major** `{overflow_path}:9` — {overflow_body}\n\n"
            "</details>"
        ),
    )

    merge_recall_findings_into_analyzer_run(
        analyzer_run,
        draft=[{"path": "src/draft.py", "line": 1, "body": "Already drafted."}],
        recalled=[{"path": recall_path, "line": 12, "body": recall_body, "severity": "Major"}],
    )

    assert analyzer_run.deferred_section is not None
    assert overflow_body in analyzer_run.deferred_section
    assert recall_body in analyzer_run.deferred_section
    assert len(analyzer_run.deferred_findings) == 2


def test_merge_recall_skips_findings_already_in_deferred() -> None:
    """Recall must not duplicate analyzer overflow rows already in deferred_findings."""
    overflow_path = "src/overflow.py"
    overflow_body = "Analyzer overflow finding."

    analyzer_run = AnalyzerRunState(
        ran=True,
        deferred_findings=[
            {
                "path": overflow_path,
                "line": 9,
                "body": overflow_body,
                "severity": "Major",
            }
        ],
    )

    merge_recall_findings_into_analyzer_run(
        analyzer_run,
        draft=[{"path": "src/draft.py", "line": 1, "body": "Already drafted."}],
        recalled=[{"path": overflow_path, "line": 9, "body": overflow_body, "severity": "Major"}],
    )

    assert len(analyzer_run.deferred_findings) == 1
    assert analyzer_run.deferred_findings[0]["body"] == overflow_body
