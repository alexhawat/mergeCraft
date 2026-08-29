"""W1.5 — multi-reviewer execution (wave plan 11, green after W6)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.cli.support_agent_roster import (
    W6_XFAIL,
    import_reviewer_merge,
    two_reviewer_config,
    write_config,
)

from mergecraft.agents.harness_render import default_subagent_selection
from mergecraft.agents.registry import load_registry
from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _finding(
    *, path: str, body: str, line: int | None, severity: str = "critical"
) -> dict[str, Any]:
    row: dict[str, Any] = {"path": path, "body": body, "severity": severity}
    if line is not None:
        row["line"] = line
    return row


def _load_registry(tmp_path: Path) -> object:
    settings = load_repo_settings(root=tmp_path)
    return load_registry(settings=settings, repo_root=tmp_path)


@W6_XFAIL
def test_default_subagent_selection_returns_every_reviewer_plus_verifier(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    write_config(tmp_path, two_reviewer_config())
    monkeypatch.chdir(tmp_path)
    registry = _load_registry(tmp_path)
    selection = default_subagent_selection(registry, recall_pass=False)
    assert "mergecraft-reviewer" in selection
    assert "reviewer2" in selection
    assert "mergecraft-verifier" in selection
    reviewer_ids = [item for item in selection if "reviewer" in item]
    assert len(reviewer_ids) >= 2


@W6_XFAIL
def test_merge_dedupes_identical_path_body_line() -> None:
    mod = import_reviewer_merge()
    left = [_finding(path="a.py", body="bug", line=10)]
    right = [_finding(path="a.py", body="bug", line=10)]
    merged = mod.merge_reviewer_findings([("reviewer", left), ("reviewer2", right)])
    keys = {(row["path"], row["body"], row.get("line")) for row in merged}
    assert len(keys) == 1


@W6_XFAIL
def test_merge_preserves_critical_findings_at_different_lines() -> None:
    mod = import_reviewer_merge()
    left = [_finding(path="a.py", body="bug one", line=10)]
    right = [_finding(path="a.py", body="bug two", line=20)]
    merged = mod.merge_reviewer_findings([("reviewer", left), ("reviewer2", right)])
    lines = {row.get("line") for row in merged}
    assert lines == {10, 20}


@W6_XFAIL
def test_merged_findings_yield_one_verdict_and_one_terminal_submission() -> None:
    mod = import_reviewer_merge()
    findings = mod.merge_reviewer_findings(
        [
            ("reviewer", [_finding(path="a.py", body="warn", line=1, severity="warning")]),
            ("reviewer2", [_finding(path="b.py", body="crit", line=2, severity="critical")]),
        ]
    )
    verdict = mod.verdict_from_merged_findings(findings)
    assert verdict in {"request_changes", "comment", "approve"}
    submissions = mod.terminal_submission_count_from_review_runs(
        [
            mod.ReviewerRun(agent_id="mergecraft-reviewer", findings=findings[:1], error=None),
            mod.ReviewerRun(agent_id="reviewer2", findings=findings[1:], error=None),
        ]
    )
    assert submissions == 1


@W6_XFAIL
def test_critical_from_reviewer2_blocks_when_reviewer_approves() -> None:
    mod = import_reviewer_merge()
    findings = mod.merge_reviewer_findings(
        [
            ("reviewer", []),
            ("reviewer2", [_finding(path="a.py", body="critical issue", line=5)]),
        ]
    )
    verdict = mod.verdict_from_merged_findings(findings)
    assert verdict == "request_changes"


@W6_XFAIL
def test_one_reviewer_failing_does_not_void_other_findings() -> None:
    mod = import_reviewer_merge()
    surviving = [_finding(path="a.py", body="still here", line=3)]
    merged = mod.merge_reviewer_findings(
        [
            ("reviewer", surviving),
            ("reviewer2", []),
        ],
        errors={"reviewer2": "quota exceeded"},
    )
    assert len(merged) == 1
    assert merged[0]["body"] == "still here"
    summary = mod.format_reviewer_degradation_summary(errors={"reviewer2": "quota exceeded"})
    assert "reviewer2" in summary.lower()
