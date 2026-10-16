"""A changed-but-unread file is an advisory run-health row, not a blocker (#885).

The auditor emitted one ``Major`` run-health finding per changed file the run
never read. Major is a blocking severity everywhere else in the review record,
so a long diff drowned the genuinely change-scoped reasons in per-file process
noise and a reader saw "run health" where they needed to see what was wrong with
the change. The real coverage question — did the reviewer read every hunk — is a
per-hunk gate; the per-file finding stays in the record as an advisory note.
"""

from __future__ import annotations

from typing import Any

from mergecraft.agents.gates import BLOCKING_SEVERITIES, blocking_findings, decide_approval
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.trajectory import ToolCallRecord, TrajectoryRecord
from mergecraft.evidence.trajectory_audit import TRAJECTORY_CHECKS, audit_trajectory


def _record(**overrides: Any) -> TrajectoryRecord:
    base: dict[str, Any] = {
        "sources": ["mcp-tool-calls"],
        "tool_calls": [
            ToolCallRecord(
                sequence=1,
                tool="shell",
                signature="shell:1",
                intent="read",
                ok=True,
                command="cat src/other.py",
                paths=["src/other.py"],
            ),
            ToolCallRecord(
                sequence=2,
                tool="shell",
                signature="shell:2",
                intent="verify",
                ok=True,
                outcome_ok=True,
                command="pytest -q",
            ),
            ToolCallRecord(
                sequence=3,
                tool="create_pull_request_review",
                signature="create_pull_request_review:3",
                intent="complete",
                ok=True,
            ),
        ],
        "files_read": ["src/other.py"],
        "files_modified": ["src/other.py", "src/unread_a.py", "src/unread_b.py"],
        "commands_run": ["cat src/other.py", "pytest -q"],
        "tests_run": ["pytest -q"],
        "completion_claims": ["create_pull_request_review"],
        "read_coverage": True,
    }
    base.update(overrides)
    return TrajectoryRecord(**base)


def _unread_findings() -> list[Any]:
    return [f for f in audit_trajectory(_record()) if f.rule_id == "changed-unread-file"]


def test_the_check_is_declared_with_a_non_blocking_severity() -> None:
    check = next(c for c in TRAJECTORY_CHECKS if c.rule_id == "changed-unread-file")
    assert check.severity not in BLOCKING_SEVERITIES, check.severity


def test_every_unread_file_is_still_listed() -> None:
    findings = _unread_findings()
    assert [f.path for f in findings] == ["src/unread_a.py", "src/unread_b.py"]
    for finding in findings:
        assert "was modified but never read during this run" in finding.message
        assert finding.scope == "run"


def test_no_unread_file_finding_carries_a_blocking_severity() -> None:
    for finding in _unread_findings():
        assert finding.severity not in BLOCKING_SEVERITIES, finding.severity


def test_the_unread_findings_do_not_block_the_approval_decision() -> None:
    findings = _unread_findings()
    assert blocking_findings(findings) == []

    packet = build_packet(
        change_id="acme/demo#1",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/unread_a.py", "src/unread_b.py"],
        findings=findings,
        deterministic_checks=[],
        self_assessment={"would_approve": True, "sha": "cafe"},
    )
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")

    assert decision.verdict == "success"
    assert packet.run_health is not None
    assert {f.rule_id for f in packet.run_health.findings} == {"changed-unread-file"}


def test_other_trajectory_checks_keep_their_severity() -> None:
    """Only the per-file check is demoted; the others still flag process failures."""
    severities = {c.rule_id: c.severity for c in TRAJECTORY_CHECKS}
    assert severities["unresolved-failure"] == "Critical"
    assert severities["no-post-edit-verification"] == "Major"
    assert severities["ignored-tool-error"] == "Major"
    assert severities["stale-assumption-after-failure"] == "Major"
