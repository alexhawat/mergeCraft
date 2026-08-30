"""W1.2 — trajectory attribution stamps and advisory-only run health."""

from __future__ import annotations

import pytest

from mergecraft.agents.gates import decide_approval
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.trajectory_audit import TRAJECTORY_CHECKS, audit_trajectory
from tests.evidence.test_trajectory import _audit, _call, _record
from tests.review_record.conftest import require_symbol

_TRAJECTORY_FIXTURES: dict[str, dict[str, object]] = {
    "changed-unread-file": {
        "files_read": ["src/other.py"],
        "files_modified": ["src/app.py"],
    },
    "ignored-tool-error": {
        "tool_calls": [
            _call(1, "run_static_checks", intent="verify", ok=False, error="boom"),
            _call(2, "create_pull_request_review", intent="complete"),
        ],
        "files_read": [],
        "files_modified": [],
    },
    "no-post-edit-verification": {
        "tool_calls": [
            _call(1, "shell", intent="verify", command="pytest -q", outcome_ok=True),
            _call(2, "shell", intent="modify", command="apply patch", paths=["src/app.py"]),
            _call(3, "create_pull_request_review", intent="complete"),
        ],
    },
    "repeated-tool-loop": {
        "tool_calls": [
            _call(index, "run_static_checks", intent="verify", signature="run_static_checks:loop")
            for index in range(1, 4)
        ]
        + [_call(4, "create_pull_request_review", intent="complete")],
    },
    "unresolved-failure": {
        "tool_calls": [
            _call(
                1,
                "run_static_checks",
                intent="verify",
                ok=True,
                outcome_ok=False,
                command="pytest -q",
                signature="run_static_checks:pytest",
            ),
            _call(2, "create_pull_request_review", intent="complete"),
        ],
        "files_read": [],
        "files_modified": [],
    },
    "suspicious-broad-edit": {
        "files_modified": [f"src/file_{index}.py" for index in range(30)],
    },
    "stale-assumption-after-failure": {
        "tool_calls": [
            _call(
                1,
                "shell",
                intent="verify",
                ok=False,
                error="boom",
                signature="shell:pytest",
                command="pytest -q",
            ),
            _call(
                2,
                "shell",
                intent="verify",
                ok=False,
                error="boom",
                signature="shell:pytest",
                command="pytest -q",
            ),
            _call(3, "create_pull_request_review", intent="complete"),
        ],
    },
    "missing-completion-signal": {
        "tool_calls": [_call(1, "shell", intent="read", command="ls")],
        "completion_claims": [],
    },
}


@pytest.mark.parametrize("check", TRAJECTORY_CHECKS, ids=lambda check: check.rule_id)
def test_every_trajectory_check_stamps_scope_source_and_introduced_by_pr(
    check: object,
) -> None:
    overrides = _TRAJECTORY_FIXTURES[check.rule_id]  # type: ignore[attr-defined]
    findings = audit_trajectory(_record(**overrides))
    matched = [finding for finding in findings if finding.rule_id == check.rule_id]  # type: ignore[attr-defined]
    assert matched, f"{check.rule_id} did not fire"  # type: ignore[attr-defined]
    for finding in matched:
        assert finding.scope == "run"
        assert finding.source == "trajectory"
        assert finding.introduced_by_pr == "false"


def test_trajectory_only_run_produces_approval_success() -> None:
    findings = _audit(_record(completion_claims=[], tool_calls=_record().tool_calls[:1]))
    assert findings, "fixture must emit at least one trajectory finding"
    packet = build_packet(
        change_id="acme/demo#546",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/example.py"],
        findings=findings,
        deterministic_checks=[],
        self_assessment={"would_approve": False, "sha": "abc123"},
    )
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "success"


def test_unresolved_failure_critical_does_not_block() -> None:
    blocking = require_symbol(
        __import__("mergecraft.agents.gates", fromlist=["blocking_findings"]),
        "blocking_findings",
    )
    findings = _audit(
        _record(
            tool_calls=[
                _call(
                    1,
                    "run_static_checks",
                    intent="verify",
                    ok=True,
                    outcome_ok=False,
                    command="pytest -q",
                    signature="run_static_checks:pytest",
                ),
                _call(2, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
        )
    )
    critical = [finding for finding in findings if finding.rule_id == "unresolved-failure"]
    assert critical
    assert critical[0].severity == "Critical"
    assert blocking(critical) == []
