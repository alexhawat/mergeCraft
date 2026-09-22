"""RS1.4 — trajectory read-coverage gating (RS2, F10 bounded).

Also guards the *write* side of the same record: ``files_modified`` must stay
authoritative, coming from the run diff — not from argument-derived guesses
(#796). ``_looks_like_path`` is deliberately permissive for reads (a false
positive there suppresses a finding, which is the safe direction); applied to
modify-intent tool arguments the trade inverts and a false positive
*manufactures* a Major ``changed-unread-file`` finding out of a revision range
or a regex.
"""

from __future__ import annotations

from typing import Any

from mergecraft.evidence.trajectory import (
    ExternalTraceRef,
    ToolCallRecord,
    build_trajectory_record,
    record_tool_call,
)
from mergecraft.evidence.trajectory_audit import audit_trajectory
from mergecraft.mcp.tool_state import init_tool_state


def _empty_external_trace() -> ExternalTraceRef:
    return ExternalTraceRef(source="mergecraft.tracing", event_count=0, tool_calls=[])


def _read_external_trace() -> ExternalTraceRef:
    return ExternalTraceRef(
        source="mergecraft.tracing",
        event_count=1,
        tool_calls=[
            ToolCallRecord(
                sequence=1,
                tool="Read",
                signature="Read:1",
                intent="read",
                ok=True,
                paths=["docs/review-doctrine.md"],
            )
        ],
    )


def test_external_trace_with_no_reads_is_not_read_coverage() -> None:
    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    record = build_trajectory_record(state, external_trace=_empty_external_trace())
    assert record.files_read == []
    assert record.read_coverage is False


def test_external_trace_with_reads_is_read_coverage() -> None:
    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    record = build_trajectory_record(state, external_trace=_read_external_trace())
    assert record.files_read == ["docs/review-doctrine.md"]
    assert record.read_coverage is True


def test_mcp_observed_reads_are_still_read_coverage() -> None:
    from mergecraft.evidence.trajectory import record_tool_call

    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    record_tool_call(
        state,
        tool="shell",
        arguments={"command": "cat src/app.py"},
        ok=True,
        outcome_ok=True,
    )
    record = build_trajectory_record(state)
    assert record.read_coverage is True


# ── #796 — a modify-intent argument is not a modified file ──────────────────


def _changed_unread_paths(record: Any) -> list[str]:
    """The paths the auditor reports as modified-but-never-read."""
    return [
        finding.path
        for finding in audit_trajectory(record)
        if finding.rule_id == "changed-unread-file"
    ]


def _record_from_real_payload(*, files_modified: list[str], bogus_arguments: bool) -> Any:
    """Build the record the way ``main.py`` does — via ``record_tool_call``.

    One read observed ``src/real.py`` (the only file the run diff changed) and
    one ``commit_changes`` carried a read-only ``git diff`` plus a ``grep``
    regex in its arguments. ``record_tool_call`` is the choke point that
    computes ``call.paths`` from those arguments, so this exercises the
    inflation at its source rather than hand-building an already-inflated
    record.
    """
    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    record_tool_call(
        state,
        tool="shell",
        arguments={"command": "cat", "path": "src/real.py"},
        ok=True,
        outcome_ok=True,
    )
    args: dict[str, Any] = {"message": "record claims"}
    if bogus_arguments:
        # From the #789 payload: two revision ranges and a regex — none of
        # which is a file, on either side. (A ``rev:path`` spec is handled
        # separately: it *is* a file read, so it is normalised, not dropped.)
        args["args"] = [
            "origin/main..HEAD",
            "origin/main...HEAD",
            r"^(def |class |@app\.command|    def )",
        ]
    record_tool_call(state, tool="commit_changes", arguments=args, ok=True, outcome_ok=True)
    return build_trajectory_record(state, files_modified=files_modified)


def test_revision_ranges_and_regexes_are_not_changed_unread_files() -> None:
    """A read-only ``git diff`` and a ``grep`` regex raise zero Major findings.

    ``files_modified`` comes from the run diff and is authoritative
    (``trajectory.py``'s own docstring says so). Extending it with
    ``call.paths`` from a modify-intent call lets ``origin/main..HEAD`` and a
    bare regex each emit a Major, burying the genuine findings (#796).
    """
    record = _record_from_real_payload(files_modified=["src/real.py"], bogus_arguments=True)

    assert record.read_coverage is True
    assert record.files_read == ["src/real.py"]
    assert _changed_unread_paths(record) == [], (
        "a revision range or a regex was reported as a modified file that was never read"
    )


def test_a_genuinely_unread_modified_file_still_raises_one_finding() -> None:
    """The check must survive the fix: a real unread edit still reports.

    ``src/real.py`` was read; ``src/unread.py`` appears only in the run diff.
    Exactly one ``changed-unread-file`` finding, naming the unread file.
    """
    record = _record_from_real_payload(
        files_modified=["src/real.py", "src/unread.py"],
        bogus_arguments=False,
    )

    assert _changed_unread_paths(record) == ["src/unread.py"]


def test_rev_path_reads_are_preserved_as_read_evidence() -> None:
    """A read at a revision is a read of the file, not of a bogus path.

    ``git show HEAD:src/base.py`` addresses ``src/base.py``. Normalising the
    ``rev:path`` object spec to its path keeps the base read in ``files_read``,
    so ``changed-unread-file`` does not fire on a file whose base *was* read —
    the read-side bias (Q-D3). A revision *range* is not a file and stays out.
    """
    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    record_tool_call(
        state,
        tool="shell",
        arguments={"command": "git show HEAD:src/base.py"},
        ok=True,
        outcome_ok=True,
    )
    record_tool_call(
        state,
        tool="shell",
        arguments={"command": "git diff origin/main..HEAD"},
        ok=True,
        outcome_ok=True,
    )

    record = build_trajectory_record(state, files_modified=["src/base.py", "src/unread.py"])

    assert "src/base.py" in record.files_read
    assert "HEAD:src/base.py" not in record.files_read
    assert "origin/main..HEAD" not in record.files_read
    assert _changed_unread_paths(record) == ["src/unread.py"]
