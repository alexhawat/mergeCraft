"""Pure trajectory auditor — eight named checks over a `TrajectoryRecord` (#49).

The auditor reads *how* a change was produced, not the change itself. The diff
can look clean while the process that produced it was not: a file edited without
ever being read, a failing gate re-run byte-identically until it was abandoned,
a run that simply stopped. Those are invisible to a diff review and visible here.

Two properties are load-bearing:

**Silence on absent evidence.** mergeCraft only sees the tool calls it mediates.
A driver whose file reads never cross MCP produces a record with no reads — which
is *unknown*, not *unread*. Every check that could fire on missing signal is
gated on the record carrying that signal at all (``read_coverage``, a non-empty
``tool_calls``). A check that fires on every run is noise, not a gate.

**No second gate path.** The checks emit ordinary :class:`Finding` rows that go
into the packet's finding list, where ``decide_approval()`` — the one gate —
reads them (D5, W8.2). Nothing here decides anything.

Exports:
    TrajectoryCheck: One named check's metadata (severity, recommended action).
    TRAJECTORY_CHECKS: The eight checks, in report order.
    audit_trajectory: Run every check over a record and return findings.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from mergecraft.analyzers.finding import Finding, make_finding

if TYPE_CHECKING:
    from mergecraft.evidence.trajectory import ToolCallRecord, TrajectoryRecord

__all__ = [
    "TRAJECTORY_CHECKS",
    "TrajectoryCheck",
    "TrajectoryPlacement",
    "audit_trajectory",
    "place_trajectory_findings",
]

# A run touching more files than this in one pass is reported for a human look.
# Not a hard error: large mechanical refactors are legitimate, which is why the
# check is Minor and names the count rather than asserting wrongdoing.
BROAD_EDIT_FILE_THRESHOLD: Final[int] = 25

# Two identical calls is a retry. Three is a loop.
REPEATED_CALL_THRESHOLD: Final[int] = 3

_TOOL = "trajectory"
_CATEGORY = "Maintainability & Code Quality"


class TrajectoryCheck(BaseModel):
    """One named trajectory check's fixed metadata."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: str
    recommended_action: str
    summary: str


TRAJECTORY_CHECKS: Final[tuple[TrajectoryCheck, ...]] = (
    TrajectoryCheck(
        rule_id="changed-unread-file",
        severity="Major",
        recommended_action="Read the file before trusting the edit; re-review this change by hand.",
        summary="A file was modified that the run never read.",
    ),
    TrajectoryCheck(
        rule_id="ignored-tool-error",
        severity="Major",
        recommended_action="Re-run the failed tool and act on its output, or state why it was safe to skip.",
        summary="A tool call errored and was never retried.",
    ),
    TrajectoryCheck(
        rule_id="no-post-edit-verification",
        severity="Major",
        recommended_action="Run the repo's gates after the final edit, not before it.",
        summary="Files were modified and nothing verifying ran afterwards.",
    ),
    TrajectoryCheck(
        rule_id="repeated-tool-loop",
        severity="Minor",
        recommended_action="Inspect the loop: the same call repeated unchanged rarely produces new information.",
        summary="The same call was made with identical arguments three or more times.",
    ),
    TrajectoryCheck(
        rule_id="unresolved-failure",
        severity="Critical",
        recommended_action="Fix the failing command, or record why it is expected to fail.",
        summary="A command reported failure and no later run of it passed.",
    ),
    TrajectoryCheck(
        rule_id="suspicious-broad-edit",
        severity="Minor",
        recommended_action="Confirm the breadth is intended; a wide edit is hard to review by diff alone.",
        summary="One run modified an unusually large number of files.",
    ),
    TrajectoryCheck(
        rule_id="stale-assumption-after-failure",
        severity="Major",
        recommended_action="Read the failure output before retrying; an identical retry assumes the cause changed on its own.",
        summary="A failed call was retried byte-identically with nothing read in between.",
    ),
    TrajectoryCheck(
        rule_id="missing-completion-signal",
        severity="Minor",
        recommended_action="Confirm the run finished its work rather than stopping early.",
        summary="The run did work and never signalled completion.",
    ),
)

_BY_ID: Final[dict[str, TrajectoryCheck]] = {c.rule_id: c for c in TRAJECTORY_CHECKS}


def _finding(
    rule_id: str,
    *,
    message: str,
    path: str = "",
    evidence: list[str] | None = None,
) -> Finding:
    """Build a `Finding` for a named check, carrying its severity and action."""
    check = _BY_ID[rule_id]
    # A trajectory finding is about the *run*, not a line of code, but
    # `Finding` requires a 1-based line range. Findings with no offending file
    # carry an empty path, which no diff hunk matches, so `analyzers/budget.py`
    # places them in the body rather than inline — where a claim about process
    # belongs.
    return make_finding(
        tool=_TOOL,
        rule_id=rule_id,
        category=_CATEGORY,
        severity=check.severity,
        confidence="certain",
        message=message,
        path=path,
        start_line=1,
        end_line=1,
        source="trajectory",
        scope="run",
        evidence=evidence or [],
        remediation=check.recommended_action,
        introduced_by_pr="false",
    )


def _changed_unread_file(record: TrajectoryRecord) -> list[Finding]:
    # Without any observed read the record says nothing about reading, so
    # "unread" would be an inference from missing data rather than evidence.
    if not record.read_coverage:
        return []
    read = set(record.files_read)
    return [
        _finding(
            "changed-unread-file",
            message=f"{path} was modified but never read during this run",
            path=path,
            evidence=[f"files_read={sorted(read)!r}"],
        )
        for path in record.files_modified
        if path not in read
    ]


def _ignored_tool_error(record: TrajectoryRecord) -> list[Finding]:
    """A call raised and that tool was never invoked again."""
    findings: list[Finding] = []
    for call in record.tool_calls:
        if call.ok:
            continue
        retried = any(
            later.tool == call.tool and later.sequence > call.sequence
            for later in record.tool_calls
        )
        if retried:
            continue
        findings.append(
            _finding(
                "ignored-tool-error",
                message=f"{call.tool} failed and was never retried",
                evidence=[call.error or "tool call reported failure"],
            )
        )
    return findings


def _no_post_edit_verification(record: TrajectoryRecord) -> list[Finding]:
    """Something verifying must run *after* the last modification."""
    # Trigger on the record's own `files_modified`, not on modify-intent calls:
    # a driver can edit files through a path mergeCraft never mediated, and the
    # question "was this verified?" is still answerable and still worth asking.
    if not record.files_modified:
        return []
    edits = [c for c in record.tool_calls if c.intent == "modify"]
    last_edit = max((c.sequence for c in edits), default=0)
    verified_after = any(c.intent == "verify" and c.sequence > last_edit for c in record.tool_calls)
    if verified_after:
        return []
    return [
        _finding(
            "no-post-edit-verification",
            message="files were modified and nothing verifying ran afterwards",
            evidence=[f"last edit at call {last_edit}"],
        )
    ]


def _repeated_tool_loop(record: TrajectoryRecord) -> list[Finding]:
    counts = Counter(call.signature for call in record.tool_calls)
    return [
        _finding(
            "repeated-tool-loop",
            message=f"the same call was repeated {count} times with identical arguments",
            evidence=[f"signature={signature!r}"],
        )
        for signature, count in sorted(counts.items())
        if count >= REPEATED_CALL_THRESHOLD
    ]


def _unresolved_failure(record: TrajectoryRecord) -> list[Finding]:
    """The call succeeded; the thing it ran failed, and never later passed."""
    findings: list[Finding] = []
    for call in record.tool_calls:
        if call.outcome_ok is not False:
            continue
        later_pass = any(
            other.signature == call.signature
            and other.sequence > call.sequence
            and other.outcome_ok is True
            for other in record.tool_calls
        )
        if later_pass:
            continue
        findings.append(
            _finding(
                "unresolved-failure",
                message=f"{call.command or call.tool} reported failure and never passed",
                evidence=[f"unresolved_errors={record.unresolved_errors!r}"],
            )
        )
    return findings


def _suspicious_broad_edit(record: TrajectoryRecord) -> list[Finding]:
    count = len(record.files_modified)
    if count < BROAD_EDIT_FILE_THRESHOLD:
        return []
    return [
        _finding(
            "suspicious-broad-edit",
            message=f"{count} files were modified in one run",
            evidence=[f"threshold={BROAD_EDIT_FILE_THRESHOLD}"],
        )
    ]


def _read_between(calls: list[ToolCallRecord], lower: int, upper: int) -> bool:
    """True when any read-intent call sits strictly between two sequences."""
    return any(c.intent == "read" and lower < c.sequence < upper for c in calls)


def _stale_assumption_after_failure(record: TrajectoryRecord) -> list[Finding]:
    """An identical retry with nothing read in between assumes the cause moved."""
    findings: list[Finding] = []
    calls = list(record.tool_calls)
    for index, call in enumerate(calls):
        if call.ok:
            continue
        for later in calls[index + 1 :]:
            if later.signature != call.signature or later.ok:
                continue
            if _read_between(calls, call.sequence, later.sequence):
                break
            findings.append(
                _finding(
                    "stale-assumption-after-failure",
                    message=(
                        f"{call.tool} was retried with identical arguments after failing, "
                        "with nothing read in between"
                    ),
                    evidence=[f"signature={call.signature!r}"],
                )
            )
            break
    return findings


def _missing_completion_signal(record: TrajectoryRecord) -> list[Finding]:
    # An empty record is a driver mergeCraft did not mediate, not an abandoned
    # run — firing here would flag every such execution.
    if not record.tool_calls:
        return []
    if record.completion_claims:
        return []
    return [
        _finding(
            "missing-completion-signal",
            message="the run performed work and never signalled completion",
            evidence=[f"tool_calls={len(record.tool_calls)}"],
        )
    ]


_CHECK_FUNCTIONS = (
    _changed_unread_file,
    _ignored_tool_error,
    _no_post_edit_verification,
    _repeated_tool_loop,
    _unresolved_failure,
    _suspicious_broad_edit,
    _stale_assumption_after_failure,
    _missing_completion_signal,
)


def audit_trajectory(record: TrajectoryRecord) -> list[Finding]:
    """Run every trajectory check over ``record`` and return the findings.

    Pure: no I/O, no logging, no module state, no clock. The same record always
    yields the same findings, which is what lets a promoted eval case replay a
    trajectory verdict deterministically.

    Returns findings in check order. An empty list means every check was either
    satisfied or had no evidence to judge on — the two are deliberately
    indistinguishable to the caller, because both mean "nothing to report".
    """
    findings: list[Finding] = []
    for check in _CHECK_FUNCTIONS:
        findings.extend(check(record))
    return findings


class TrajectoryPlacement(BaseModel):
    """How trajectory findings were placed alongside code findings (W8.3)."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    inline: list[Finding]
    body: list[Finding]


def place_trajectory_findings(
    code_findings: list[Finding],
    trajectory_findings: list[Finding],
    *,
    inline_budget: int,
) -> TrajectoryPlacement:
    """Give code findings every inline slot first; trajectory takes leftovers.

    A trajectory finding is a claim about *process*, and a reviewer reading a
    diff wants the defect in their code before an observation about how it was
    produced. So the budget is spent on code findings first and trajectory
    findings only occupy slots nothing else wanted; the rest go to the body,
    where they are still reported and still reach the packet.

    Pure: it partitions the inputs and never mutates them.
    """
    inline = list(code_findings[:inline_budget])
    remaining = max(inline_budget - len(inline), 0)
    inline.extend(trajectory_findings[:remaining])
    placed = {id(item) for item in inline}
    body = [item for item in code_findings if id(item) not in placed]
    body.extend(item for item in trajectory_findings if id(item) not in placed)
    return TrajectoryPlacement(inline=inline, body=body)
