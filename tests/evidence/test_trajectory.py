"""RED suite for the trajectory record (#43) and the trajectory auditor (#49).

WC-T of the merge-evidence wave plan. Every case here is written against the
contract W7/W8 must satisfy, not against an implementation:

* **WC-T.1** — one case per named check, each firing on a crafted record.
* **WC-T.2** — a high-severity trajectory finding reaches the packet but stays
  advisory (plan 12 D2): run-scoped findings never block auto-merge.
* **WC-T.3** — the record builds from MCP tool-call state alone (D8): no
  external trace, no tracing sink, no #56.
* **WC-T.4** — an attached external trace is enrichment; the same record
  audits identically without it.
* **WC-T.5** — the auditor is pure.

The eight checks are deliberately given *distinguishable* triggers so that
disabling any one of them fails cases no other check covers. A suite where
three checks all fire on "something went wrong" proves only that one of them
works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from mergecraft.evidence.trajectory import ToolCallRecord, TrajectoryRecord


# ── record construction helpers ───────────────────────────────────────────────


def _call(
    sequence: int,
    tool: str,
    *,
    intent: str = "other",
    ok: bool = True,
    outcome_ok: bool | None = None,
    error: str | None = None,
    command: str | None = None,
    paths: list[str] | None = None,
    signature: str | None = None,
) -> ToolCallRecord:
    from mergecraft.evidence.trajectory import ToolCallRecord

    return ToolCallRecord(
        sequence=sequence,
        tool=tool,
        signature=signature or f"{tool}:{sequence}",
        intent=intent,
        ok=ok,
        outcome_ok=outcome_ok,
        error=error,
        command=command,
        paths=paths or [],
    )


def _record(**overrides: Any) -> TrajectoryRecord:
    """A clean, complete trajectory that fires no check by default.

    Every positive case below is this record plus exactly one mutation, so a
    failing case names the check it broke rather than "something is off".
    """
    from mergecraft.evidence.trajectory import TrajectoryRecord

    base: dict[str, Any] = {
        "sources": ["mcp-tool-calls"],
        "tool_calls": [
            _call(1, "checkout_pr", intent="read", paths=["src/app.py"]),
            _call(2, "shell", intent="read", command="cat src/app.py", paths=["src/app.py"]),
            _call(3, "shell", intent="modify", command="apply patch", paths=["src/app.py"]),
            _call(4, "shell", intent="verify", command="pytest -q", outcome_ok=True),
            _call(5, "create_pull_request_review", intent="complete"),
        ],
        "files_read": ["src/app.py"],
        "files_modified": ["src/app.py"],
        "commands_run": ["cat src/app.py", "apply patch", "pytest -q"],
        "tests_run": ["pytest -q"],
        "failures_observed": [],
        "fixes_after_failures": 0,
        "retries": 0,
        "unresolved_errors": [],
        "completion_claims": ["create_pull_request_review"],
        "read_coverage": True,
        "external_trace": None,
    }
    base.update(overrides)
    return TrajectoryRecord(**base)


def _rule_ids(findings: list[Any]) -> set[str]:
    return {finding.rule_id for finding in findings}


def _audit(record: TrajectoryRecord) -> list[Any]:
    from mergecraft.evidence.trajectory_audit import audit_trajectory

    return audit_trajectory(record)


# ── WC-T.1 — one case per check ───────────────────────────────────────────────


def test_clean_trajectory_fires_nothing() -> None:
    """The control. Without it every positive case below could be vacuous."""
    assert _audit(_record()) == []


def test_changed_unread_file_fires() -> None:
    """A file was edited that the run never read (#49 read-before-edit)."""
    findings = _audit(
        _record(
            files_read=["src/other.py"],
            files_modified=["src/app.py", "src/other.py"],
        )
    )
    assert "changed-unread-file" in _rule_ids(findings)
    offender = next(f for f in findings if f.rule_id == "changed-unread-file")
    assert offender.path == "src/app.py", "the finding must name the unread file"


def test_changed_unread_file_is_suppressed_without_read_coverage() -> None:
    """No read signal at all means *unknown*, not *unread*.

    Native `Read` calls are invisible to the MCP layer, so a record with zero
    observed reads carries no evidence either way. Firing there would flag
    every run of an agent whose file reads mergeCraft does not mediate — a
    check that fires on every run is noise, not a gate.
    """
    findings = _audit(
        _record(
            files_read=[],
            read_coverage=False,
            files_modified=["src/app.py"],
        )
    )
    assert "changed-unread-file" not in _rule_ids(findings)


def test_ignored_tool_error_fires() -> None:
    """A tool errored and the run never called that tool again."""
    findings = _audit(
        _record(
            tool_calls=[
                _call(1, "run_static_checks", intent="verify", ok=False, error="boom"),
                _call(2, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
        )
    )
    assert "ignored-tool-error" in _rule_ids(findings)


def test_ignored_tool_error_does_not_fire_when_the_tool_was_retried() -> None:
    """Retrying the failed tool is the sane response — that is not the defect."""
    findings = _audit(
        _record(
            tool_calls=[
                _call(1, "run_static_checks", intent="verify", ok=False, error="boom"),
                _call(2, "shell", intent="read", command="cat pyproject.toml"),
                _call(3, "run_static_checks", intent="verify", ok=True, outcome_ok=True),
                _call(4, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
        )
    )
    assert "ignored-tool-error" not in _rule_ids(findings)


def test_no_post_edit_verification_fires() -> None:
    """Files were edited and nothing verifying ran afterwards."""
    findings = _audit(
        _record(
            tool_calls=[
                _call(1, "shell", intent="verify", command="pytest -q", outcome_ok=True),
                _call(2, "shell", intent="modify", command="apply patch", paths=["src/app.py"]),
                _call(3, "create_pull_request_review", intent="complete"),
            ],
            tests_run=["pytest -q"],
        )
    )
    assert "no-post-edit-verification" in _rule_ids(findings), (
        "a verification that ran *before* the last edit does not verify it"
    )


def test_repeated_tool_loop_fires() -> None:
    """The same call, with the same arguments, three times over."""
    findings = _audit(
        _record(
            tool_calls=[
                _call(index, "shell", intent="read", command="ls", signature="shell:ls")
                for index in range(1, 4)
            ]
            + [_call(4, "create_pull_request_review", intent="complete")],
            files_read=[],
            files_modified=[],
            retries=2,
        )
    )
    assert "repeated-tool-loop" in _rule_ids(findings)


def test_repeated_tool_loop_does_not_fire_below_the_threshold() -> None:
    """Two identical calls is a retry; the check is about a *loop*."""
    findings = _audit(
        _record(
            tool_calls=[
                _call(index, "shell", intent="read", command="ls", signature="shell:ls")
                for index in range(1, 3)
            ]
            + [_call(3, "create_pull_request_review", intent="complete")],
            files_read=[],
            files_modified=[],
            retries=1,
        )
    )
    assert "repeated-tool-loop" not in _rule_ids(findings)


def test_unresolved_failure_fires() -> None:
    """A command reported failure and no later run of it ever passed.

    Distinct from `ignored-tool-error`: the tool call *succeeded*; what failed
    is the thing it ran.
    """
    findings = _audit(
        _record(
            tool_calls=[
                _call(1, "shell", intent="verify", command="pytest -q", outcome_ok=False),
                _call(2, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
            failures_observed=["pytest -q"],
            unresolved_errors=["pytest -q"],
        )
    )
    assert "unresolved-failure" in _rule_ids(findings)


def test_suspicious_broad_edit_fires() -> None:
    """One run touching an implausible number of files."""
    wide = [f"src/module_{index}.py" for index in range(40)]
    findings = _audit(_record(files_read=wide, files_modified=wide))
    assert "suspicious-broad-edit" in _rule_ids(findings)


def test_stale_assumption_after_failure_fires() -> None:
    """A failed call retried byte-identically with nothing read in between."""
    findings = _audit(
        _record(
            tool_calls=[
                _call(
                    1,
                    "shell",
                    intent="verify",
                    command="pytest -q",
                    ok=False,
                    error="boom",
                    signature="shell:pytest",
                ),
                _call(
                    2,
                    "shell",
                    intent="verify",
                    command="pytest -q",
                    ok=False,
                    error="boom",
                    signature="shell:pytest",
                ),
                _call(3, "create_pull_request_review", intent="complete"),
            ],
            files_read=[],
            files_modified=[],
        )
    )
    assert "stale-assumption-after-failure" in _rule_ids(findings)


def test_stale_assumption_does_not_fire_when_something_was_read_in_between() -> None:
    """Re-running after actually looking at something is normal debugging."""
    findings = _audit(
        _record(
            tool_calls=[
                _call(
                    1,
                    "shell",
                    intent="verify",
                    command="pytest -q",
                    ok=False,
                    error="boom",
                    signature="shell:pytest",
                ),
                _call(2, "shell", intent="read", command="cat log.txt", paths=["log.txt"]),
                _call(
                    3,
                    "shell",
                    intent="verify",
                    command="pytest -q",
                    ok=False,
                    error="boom",
                    signature="shell:pytest",
                ),
                _call(4, "create_pull_request_review", intent="complete"),
            ],
            files_read=["log.txt"],
            files_modified=[],
        )
    )
    assert "stale-assumption-after-failure" not in _rule_ids(findings)


def test_missing_completion_signal_fires() -> None:
    """The run did work and then simply stopped."""
    findings = _audit(
        _record(
            tool_calls=[_call(1, "shell", intent="read", command="ls")],
            files_read=[],
            files_modified=[],
            completion_claims=[],
        )
    )
    assert "missing-completion-signal" in _rule_ids(findings)


def test_missing_completion_signal_does_not_fire_on_an_empty_record() -> None:
    """No recorded calls is no evidence — the auditor must stay silent.

    A driver whose tool calls mergeCraft never mediated would otherwise be
    reported as an incomplete run on every single execution.
    """
    findings = _audit(
        _record(
            tool_calls=[],
            files_read=[],
            files_modified=[],
            commands_run=[],
            tests_run=[],
            completion_claims=[],
            read_coverage=False,
        )
    )
    assert findings == []


def test_every_named_check_has_a_severity_and_a_recommended_action() -> None:
    """#49: findings carry severity and recommended action."""
    from mergecraft.evidence.trajectory_audit import TRAJECTORY_CHECKS

    expected = {
        "changed-unread-file",
        "ignored-tool-error",
        "no-post-edit-verification",
        "repeated-tool-loop",
        "unresolved-failure",
        "suspicious-broad-edit",
        "stale-assumption-after-failure",
        "missing-completion-signal",
    }
    assert {check.rule_id for check in TRAJECTORY_CHECKS} == expected
    for check in TRAJECTORY_CHECKS:
        assert check.severity, f"{check.rule_id} has no severity"
        assert check.recommended_action, f"{check.rule_id} has no recommended action"


# ── WC-T.2 — high-severity trajectory findings stay advisory (plan 12 D2) ─────


def test_high_severity_trajectory_finding_does_not_block_auto_merge() -> None:
    """Run-scoped trajectory findings reach the packet but never block approval.

    Plan 12 D2: even Critical run-health observations are advisory. The
    trajectory finding rides in the packet's finding list and `decide_approval`
    — the one gate — must still return success when they are the only findings.
    """
    from mergecraft.agents.gates import BLOCKING_SEVERITIES, blocking_findings, decide_approval
    from mergecraft.evidence.build import build_packet

    findings = _audit(_record(completion_claims=[], tool_calls=_record().tool_calls[:1]))
    high_severity = [f for f in findings if f.severity in BLOCKING_SEVERITIES]
    assert high_severity, "no trajectory check produces a blocking severity"
    assert all(finding.scope == "run" for finding in high_severity)
    assert blocking_findings(high_severity) == []

    packet = build_packet(
        change_id="acme/demo#1",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/app.py"],
        findings=high_severity,
        deterministic_checks=[],
        self_assessment={"would_approve": True, "sha": "cafe"},
    )
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "success", (
        "run-scoped trajectory findings are advisory and must not block approval"
    )


def test_trajectory_findings_reach_the_packet_from_a_real_run(tmp_path: Any) -> None:
    """The record and its findings must be populated on the live emit path.

    This is the #96 guard in test form: a `TrajectoryRecord` that is merely
    *constructible* is worth nothing. `emit_run_packet` is what `main()`
    calls, so this drives the same seam a real Action run enters.
    """
    import json

    from tests.evidence.test_run_packet import _make_ctx

    ctx = _make_ctx(tmp_path)
    from mergecraft.evidence.trajectory import record_tool_call

    record_tool_call(ctx.tool_state, tool="checkout_pr", arguments={}, ok=True)
    record_tool_call(
        ctx.tool_state,
        tool="create_pull_request_review",
        arguments={"body": "lgtm"},
        ok=True,
    )

    from mergecraft.evidence.run_packet import emit_run_packet, prepare_run_packet

    written = emit_run_packet(
        ctx,
        packet=prepare_run_packet(ctx, run_succeeded=True),
    )
    assert written is not None
    packet = json.loads(written.read_text(encoding="utf-8"))
    assert packet["trajectory"] is not None, "trajectory section stayed None on a real run"
    assert packet["trajectory"]["tool_calls"], "no MCP tool call reached the record"
    assert packet["trajectory"]["completion_claims"] == ["create_pull_request_review"]


# ── WC-T.3 / WC-T.4 — self-contained record, optional enrichment ─────────────


def test_trajectory_record_is_populated_without_external_trace() -> None:
    """D8: the record is built from MCP tool-call state alone."""
    from mergecraft.evidence.trajectory import build_trajectory_record, record_tool_call
    from mergecraft.mcp.tool_state import init_tool_state

    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    record_tool_call(state, tool="checkout_pr", arguments={}, ok=True)
    record_tool_call(
        state, tool="shell", arguments={"command": "pytest -q"}, ok=True, outcome_ok=True
    )
    record_tool_call(state, tool="create_pull_request_review", arguments={}, ok=True)

    record = build_trajectory_record(state, files_modified=["src/app.py"])

    assert record.external_trace is None
    assert record.sources == ["mcp-tool-calls"] or "mcp-tool-calls" in record.sources
    assert [call.tool for call in record.tool_calls] == [
        "checkout_pr",
        "shell",
        "create_pull_request_review",
    ]
    assert record.tests_run == ["pytest -q"]
    assert record.completion_claims == ["create_pull_request_review"]
    assert record.files_modified == ["src/app.py"]


def test_external_trace_is_optional_enrichment() -> None:
    """A record without the enrichment field still audits identically."""
    from mergecraft.evidence.trajectory import ExternalTraceRef

    without = _record()
    with_trace = _record(
        external_trace=ExternalTraceRef(
            source="mergecraft.tracing",
            event_count=3,
            tool_calls=[],
        ),
        sources=["mcp-tool-calls", "external-trace"],
    )
    assert _audit(without) == []
    assert _audit(with_trace) == []
    assert with_trace.external_trace is not None


def test_record_forbids_unknown_fields() -> None:
    """W7.1: `extra="forbid"` on the record."""
    import pydantic

    from mergecraft.evidence.trajectory import TrajectoryRecord

    payload = _record().model_dump()
    payload["invented"] = True
    with pytest.raises(pydantic.ValidationError):
        TrajectoryRecord(**payload)


def test_record_round_trips_through_json() -> None:
    """The record is a packet section, so it must survive serialization."""
    from mergecraft.evidence.trajectory import TrajectoryRecord

    record = _record()
    assert TrajectoryRecord.model_validate_json(record.model_dump_json()) == record


# ── WC-T.5 — the auditor is pure ─────────────────────────────────────────────


def test_auditor_is_pure() -> None:
    """No I/O, no environment reads, no mutation of its input (convention 5)."""
    import ast
    import inspect

    from mergecraft.evidence import trajectory_audit

    source = inspect.getsource(trajectory_audit)
    tree = ast.parse(source)
    banned = {"open", "getenv", "environ", "run", "post", "get", "write_text", "read_text"}
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                seen.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                seen.add(node.func.attr)
    assert not (seen & banned), f"auditor performs I/O: {sorted(seen & banned)}"

    record = _record(completion_claims=[])
    before = record.model_dump_json()
    _audit(record)
    assert record.model_dump_json() == before, "audit_trajectory mutated its input"


def test_audit_is_deterministic() -> None:
    """Same record in, same findings out — fingerprints included."""
    record = _record(completion_claims=[])
    first = [(f.rule_id, f.fingerprint, f.severity) for f in _audit(record)]
    second = [(f.rule_id, f.fingerprint, f.severity) for f in _audit(record)]
    assert first == second


# ── W8.3 — the noise budget ──────────────────────────────────────────────────


def test_trajectory_findings_never_crowd_out_code_findings() -> None:
    """W8.3: trajectory findings may only take inline slots code findings left."""
    from mergecraft.analyzers.finding import make_finding
    from mergecraft.evidence.trajectory_audit import place_trajectory_findings

    code = [
        make_finding(
            tool="ruff",
            rule_id=f"F{index:03d}",
            category="Maintainability & Code Quality",
            severity="Major",
            confidence="likely",
            message="problem",
            path=f"src/mod_{index}.py",
            start_line=1,
            end_line=1,
            source="agent",
        )
        for index in range(8)
    ]
    trajectory = _audit(_record(completion_claims=[]))
    assert trajectory, "no trajectory findings to place"

    placement = place_trajectory_findings(code, trajectory, inline_budget=8)
    inline_ids = {id(item) for item in placement.inline}
    assert all(id(item) in inline_ids for item in code), "a code finding lost its inline slot"
    assert all(id(item) not in inline_ids for item in trajectory)
