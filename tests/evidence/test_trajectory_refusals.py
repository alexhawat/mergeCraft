"""#1073 — the trajectory auditor reads ``failure_class="refused"`` rows honestly.

A refused call never ran: it has no outcome to resolve, it is not an edit that
needs verification, and its cause can never move between identical retries.
The auditor surfaces the refusal once (Trivial, naming the guard's redirect)
and lets ``repeated-tool-loop`` own the banging-on-the-guard pattern, instead
of manufacturing Major findings from a non-event.
"""

from __future__ import annotations

from typing import Any

from mergecraft.evidence.trajectory import (
    ToolCallRecord,
    TrajectoryRecord,
    build_trajectory_record,
    record_tool_call,
)
from mergecraft.evidence.trajectory_audit import audit_trajectory
from mergecraft.mcp.tool_state import init_tool_state

_REFUSAL = (
    "invalid git subcommand: 'merge-base' — not available through this tool (read-only allowlist)"
)


def _refused_call(sequence: int, *, signature: str = "git:merge-base") -> ToolCallRecord:
    return ToolCallRecord(
        sequence=sequence,
        tool="git",
        signature=signature,
        intent="modify",
        ok=False,
        error=_REFUSAL,
        failure_class="refused",
    )


def _rule_ids(findings: list[Any]) -> set[str]:
    return {finding.rule_id for finding in findings}


def test_a_refused_call_surfaces_once_as_a_trivial_guard_finding() -> None:
    record = TrajectoryRecord(
        tool_calls=[_refused_call(1)],
        completion_claims=["create_pull_request_review"],
    )

    findings = audit_trajectory(record)

    guard = [f for f in findings if f.rule_id == "ignored-tool-error"]
    assert len(guard) == 1
    assert guard[0].severity == "Trivial"
    assert "read-only allowlist" in guard[0].message, "the finding names the redirect"
    # A refusal is not a failure of the thing the tool runs.
    assert "unresolved-failure" not in _rule_ids(findings)
    assert "stale-assumption-after-failure" not in _rule_ids(findings)


def test_two_distinct_refusals_still_produce_one_guard_finding() -> None:
    record = TrajectoryRecord(
        tool_calls=[
            _refused_call(1),
            ToolCallRecord(
                sequence=2,
                tool="shell",
                signature="shell:git-status",
                intent="verify",
                ok=False,
                error="git commands are not allowed in the shell tool",
                failure_class="refused",
            ),
        ],
        completion_claims=["create_pull_request_review"],
    )

    findings = audit_trajectory(record)

    guard = [f for f in findings if f.rule_id == "ignored-tool-error"]
    assert len(guard) == 1, "one roll-up, not one finding per refusal"


def test_an_identically_retried_refusal_is_not_a_stale_assumption() -> None:
    """The error already named the redirect; the loop check owns the pattern."""
    record = TrajectoryRecord(
        tool_calls=[_refused_call(1), _refused_call(2)],
        completion_claims=["create_pull_request_review"],
    )

    findings = audit_trajectory(record)

    assert "stale-assumption-after-failure" not in _rule_ids(findings)
    # The final, never-corrected refusal is still named once — Trivial, with the
    # guard's redirect in the message. Two calls stay under the loop threshold.
    guard = [f for f in findings if f.rule_id == "ignored-tool-error"]
    assert len(guard) == 1
    assert guard[0].severity == "Trivial"
    assert "repeated-tool-loop" not in _rule_ids(findings)


def test_a_refusal_loop_fires_repeated_tool_loop() -> None:
    """#1073's run-health hint: banging on the same guard is visible."""
    record = TrajectoryRecord(
        tool_calls=[_refused_call(1), _refused_call(2), _refused_call(3)],
        completion_claims=["create_pull_request_review"],
    )

    findings = audit_trajectory(record)

    assert "repeated-tool-loop" in _rule_ids(findings)


def test_a_refused_modify_intent_call_is_not_an_edit_that_needs_verification() -> None:
    """The refused call never ran, so it must not move the last-edit marker."""
    record = TrajectoryRecord(
        tool_calls=[
            ToolCallRecord(
                sequence=1,
                tool="shell",
                signature="shell:apply",
                intent="modify",
                ok=True,
                command="apply patch",
                paths=["src/app.py"],
            ),
            ToolCallRecord(
                sequence=2,
                tool="shell",
                signature="shell:pytest",
                intent="verify",
                ok=True,
                command="pytest -q",
            ),
            _refused_call(3),
        ],
        files_read=["src/app.py"],
        files_modified=["src/app.py"],
        read_coverage=True,
        completion_claims=["create_pull_request_review"],
    )

    findings = audit_trajectory(record)

    assert "no-post-edit-verification" not in _rule_ids(findings)


def test_recorded_refusals_stay_out_of_failures_observed() -> None:
    """``failures_observed`` is for outcomes of work that ran; a refusal never ran."""
    state = init_tool_state(owner="acme", name="demo", dir="/repo")

    record_tool_call(
        state,
        tool="git",
        arguments={"command": "merge-base HEAD main"},
        ok=False,
        error=_REFUSAL,
        failure_class="refused",
    )
    record = build_trajectory_record(state)

    row = record.tool_calls[0]
    assert row.ok is False
    assert row.failure_class == "refused"
    assert row.outcome_ok is None
    assert record.failures_observed == []
    assert record.unresolved_errors == []


def test_the_explicit_refused_stamp_survives_model_validation() -> None:
    """The ``ToolCallRecord`` validator must not re-derive over a typed stamp."""
    row = ToolCallRecord(
        sequence=1,
        tool="git",
        signature="git:x",
        intent="other",
        ok=False,
        error=_REFUSAL,
        failure_class="refused",
    )

    assert row.failure_class == "refused"
    assert ToolCallRecord.model_validate(row.model_dump(mode="json")).failure_class == "refused"


def test_merge_base_is_classified_as_a_read_not_an_edit() -> None:
    """#1077 — merge-base only reads the commit graph, so it must not arm verification.

    ``_GIT_READ_SUBCOMMANDS`` drives ``_no_post_edit_verification``: a
    ``merge-base`` call classified as ``modify`` would push ``last_edit``
    forward and emit a false ``no-post-edit-verification`` Major.
    """
    from mergecraft.evidence.trajectory import _command_intent

    assert _command_intent("git", "merge-base HEAD main") == "read"
    assert _command_intent("git", "merge-base --is-ancestor HEAD origin/main") == "read"
