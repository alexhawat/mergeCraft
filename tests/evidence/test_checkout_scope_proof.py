"""Old reads/verifications remain auditable but cannot attest the next checkout."""

from __future__ import annotations

from pathlib import Path

from mergecraft.evidence.coverage import _read_evidence
from mergecraft.evidence.trajectory import build_trajectory_record, record_tool_call
from mergecraft.evidence.trajectory_audit import audit_trajectory
from mergecraft.mcp.checkout_state import invalidate_checkout_review_state
from mergecraft.mcp.tool_state import AnalyzerRunState, primary_repo_state
from mergecraft.mcp.verdict import diff_coverage_nudge_for_state, terminal_tool_was_attempted
from mergecraft.mcp.verification import _deterministic_checks_ran
from tests.evidence.test_diff_coverage_nudge import _DIFF
from tests.support.tool_context import make_tool_context


def test_new_scope_requires_fresh_reads_checks_and_completion(tmp_path: Path) -> None:
    ctx = make_tool_context(tmp_path, trust_tier="trusted")
    state = ctx.tool_state
    state.analyzer_run = AnalyzerRunState(ran=True)
    state.static_checks_ran = True
    state.static_checks = [{"name": "old-check", "exitCode": 0}]
    for tool, args in (
        ("shell", {"command": "cat src/app.py src/other.py"}),
        ("run_analyzers", {}),
        ("run_static_checks", {}),
        ("submit_review_verdict", {"verdict": "approve", "summary": "old", "findings": []}),
    ):
        record_tool_call(state, tool=tool, arguments=args, ok=True, outcome_ok=True)
    record_tool_call(
        state,
        tool="shell",
        arguments={"command": "false"},
        ok=False,
        outcome_ok=False,
        error="earlier command failed",
        failure_class="unknown",
    )
    old_calls = list(state.tool_calls)
    assert terminal_tool_was_attempted(state)
    assert _deterministic_checks_ran(ctx) == ["run_analyzers", "run_static_checks"]

    invalidate_checkout_review_state(state)
    diff_path = tmp_path / "new.diff"
    diff_path.write_text(_DIFF)
    primary_repo_state(state).diff_path = str(diff_path)
    state.coverage.authoritative_diff = _DIFF
    assert _read_evidence(state, _DIFF) == (False, {})
    assert not terminal_tool_was_attempted(state)
    assert _deterministic_checks_ran(ctx) == []
    record_tool_call(
        state, tool="shell", arguments={"command": "cat src/app.py"}, ok=True, outcome_ok=True
    )
    assert diff_coverage_nudge_for_state(state) is not None

    full = build_trajectory_record(state, files_modified=["src/app.py", "src/other.py"])
    current = build_trajectory_record(
        state, files_modified=["src/app.py", "src/other.py"], current_scope_only=True
    )
    assert full.tool_calls[: len(old_calls)] == old_calls
    assert "src/other.py" in full.files_read
    assert "src/other.py" not in current.files_read
    assert full.completion_claims
    assert not current.completion_claims
    findings = audit_trajectory(
        full, scope_record=current, diff_text=_DIFF, diff_path=str(diff_path)
    )
    rules = {finding.rule_id for finding in findings}
    assert {
        "changed-unread-file",
        "missing-completion-signal",
        "no-post-edit-verification",
        "ignored-tool-error",
    } <= rules
    assert any(f.rule_id == "changed-unread-file" and "src/other.py" in f.message for f in findings)

    record_tool_call(
        state, tool="shell", arguments={"command": "cat src/other.py"}, ok=True, outcome_ok=True
    )
    record_tool_call(state, tool="run_static_checks", arguments={}, ok=True, outcome_ok=True)
    record_tool_call(state, tool="submit_review_verdict", arguments={}, ok=True, outcome_ok=True)
    current = build_trajectory_record(
        state, files_modified=["src/app.py", "src/other.py"], current_scope_only=True
    )
    full = build_trajectory_record(state, files_modified=["src/app.py", "src/other.py"])
    remaining = {f.rule_id for f in audit_trajectory(full, scope_record=current, diff_text=_DIFF)}
    assert (
        not {"changed-unread-file", "missing-completion-signal", "no-post-edit-verification"}
        & remaining
    )
    assert "ignored-tool-error" in remaining
