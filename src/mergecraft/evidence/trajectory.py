"""The agent trajectory record — how a change was produced (#43, W7, D8).

A final diff can look plausible while the path that produced it reveals risk:
identical tool calls repeated until the budget ran out, a failure ignored, a
file edited that was never read, a completion claimed with nothing verifying
it. #43 asks mergeCraft to preserve that path; :mod:`mergecraft.evidence.
trajectory_audit` (#49) is what judges it.

**Where the data comes from (D8).** mergeCraft mediates every MCP tool call the
reviewing/engineering agent makes — ``mcp/server.py``'s ``tools/call`` handler
is the single choke point, started on every run by ``main.py`` and by the
offline ``diff-review`` path. :func:`record_tool_call` is called from there, so
the record is populated with no configuration, no sinks, and no dependency on
the tracing programme (#56). A richer external trace is declared here as
*optional enrichment* (:class:`ExternalTraceRef`) and is never required.

**What that substrate can and cannot see — read this before trusting a check.**
MCP sees every tool mergeCraft exposes: ``shell``, ``git``, ``checkout_pr``,
``run_analyzers``, ``run_static_checks``, ``create_pull_request_review`` and the
rest. It does **not** see a driver's *native* file tools — Claude's ``Read`` and
``Edit``, Codex's equivalents — because those never cross mergeCraft's wire. So
``files_read`` is complete only for reads that went through ``shell``/``git`` or
through an attached external trace. :attr:`TrajectoryRecord.read_coverage`
records that distinction honestly, and the auditor's ``changed-unread-file``
check is suppressed when it is ``False``: absence of read evidence is *unknown*,
not *unread*. ``files_modified``, by contrast, is authoritative — it comes from
the run's own diff, not from what the agent reported.

Note on ``tool_state.usage_entries``: the wave plan described it as the
trajectory substrate and as "write-only". Neither is right today. It holds
per-attempt ``AgentUsage`` token counts appended once per run in ``main.py``,
not tool calls, and the tracing programme's ``cost.*`` span attributes already
carry that signal. This module therefore adds its own field rather than
retrofitting that one; ``usage_entries`` is left exactly as it was.

Exports:
    ExternalTraceRef: Optional enrichment from an external trace (#56).
    TRAJECTORY_SCHEMA_VERSION: Pinned version of the record's shape.
    ToolCallRecord: One mediated tool call, normalised.
    TrajectoryRecord: The full record, ready for the packet and the auditor.
    build_trajectory_record: Assemble the record from run state (pure).
    classify_tool_intent: Map a tool call onto its trajectory intent.
    classify_failure_class: Derive a failure class from recorded error text.
    record_tool_call: Append one mediated call to the run's state.
"""

from __future__ import annotations

import hashlib
import shlex
from typing import TYPE_CHECKING, Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mergecraft.analyzers.redact import redact_secrets

if TYPE_CHECKING:
    from mergecraft.mcp.tool_state import ToolState

TRAJECTORY_SCHEMA_VERSION: Final[str] = "1.0.0"
"""Version of the record's shape. Bump with ``PACKET_SCHEMA_VERSION`` (D7)."""

SOURCE_MCP: Final[str] = "mcp-tool-calls"
SOURCE_RUN_DIFF: Final[str] = "run-diff"
SOURCE_EXTERNAL_TRACE: Final[str] = "external-trace"

Intent = Literal["read", "modify", "verify", "complete", "report", "other"]
"""What a tool call was *for*, as far as the trajectory is concerned."""

FailureClass = Literal["schema", "policy", "environment", "transient", "unknown"]
"""How a failed tool call should be interpreted by the trajectory auditor."""

# JSON-RPC ``-32602`` and pydantic/jsonschema validation shapes recorded in error
# text. Classifying here by string match is weaker than inspecting the typed
# exception at ``mcp/shared.py::execute`` (plan 13's seam) — follow-up:
# ``classify_failure_at_execute`` should stamp ``failure_class`` at the choke
# point so this module never re-parses prose.
_SCHEMA_FAILURE_MARKERS: Final[tuple[str, ...]] = (
    "-32602",
    "invalid arguments for",
    "input validation error",
    "validation error",
    "pydantic",
)

# Guard refusals and mode/policy blocks surfaced as tool errors.
_POLICY_FAILURE_MARKERS: Final[tuple[str, ...]] = (
    "invalid git subcommand",
    "not available through this tool",
    "invalid parameters for tool",
    "refused",
    "mode_not_implemented",
)

# Network / overload signatures that warrant a retry, not a process indictment.
_TRANSIENT_FAILURE_MARKERS: Final[tuple[str, ...]] = (
    "connection reset",
    "reset by peer",
    "temporarily unavailable",
    "timeout",
    "timed out",
    "broken pipe",
    "502",
    "503",
    "504",
    "429",
    "rate limit",
)

# Intent by MCP tool name. `shell` and `git` are absent on purpose: both are
# general-purpose, so their intent is derived from the command (see
# `_command_intent`). A tool missing from this table lands on "other" — an
# unknown tool must never be silently counted as verification or completion.
_TOOL_INTENTS: Final[dict[str, Intent]] = {
    # read
    "checkout_pr": "read",
    "checkout_repo": "read",
    "list_repos": "read",
    "get_pull_request": "read",
    "get_commit_info": "read",
    "get_issue": "read",
    "get_issue_comments": "read",
    "get_issue_events": "read",
    "get_review_comments": "read",
    "list_pull_request_reviews": "read",
    "list_check_runs": "read",
    "get_check_suite": "read",
    "get_check_suite_logs": "read",
    "analyzer_findings": "read",
    "git_fetch": "read",
    # verify
    "run_analyzers": "verify",
    "run_static_checks": "verify",
    "analyze_ci_failures": "verify",
    "verify_agent_findings": "verify",
    "record_finding_verdict": "verify",
    # modify
    "commit_changes": "modify",
    "push_branch": "modify",
    "push_tags": "modify",
    "delete_branch": "modify",
    "upload_file": "modify",
    # complete — the run produced its declared output
    "create_pull_request_review": "complete",
    "create_pull_request": "complete",
    "update_pull_request_body": "complete",
    "close_pull_request": "complete",
    "set_output": "complete",
    "report_progress": "complete",
    "create_issue_comment": "complete",
    # report — side channels; real work, but never a completion signal
    "edit_issue_comment": "report",
    "reply_to_review_comment": "report",
    "resolve_review_thread": "report",
    "add_labels": "report",
    "remove_labels": "report",
    "create_issue": "report",
    "close_issue": "report",
    "reopen_issue": "report",
    "select_mode": "report",
    "start_dependency_installation": "report",
    "await_dependency_installation": "report",
    "kill_background": "report",
}

# Leading argv tokens that mean "this command looked at something".
_READ_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "awk",
        "bat",
        "cat",
        "diff",
        "find",
        "grep",
        "head",
        "less",
        "ls",
        "more",
        "rg",
        "sed",
        "tail",
        "tree",
        "wc",
    }
)

# Leading argv tokens (or their first sub-command) that mean "this verified
# something". Anything that can *fail informatively* belongs here.
_VERIFY_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "cargo",
        "eslint",
        "go",
        "gradle",
        "jest",
        "make",
        "mypy",
        "npm",
        "npx",
        "pnpm",
        "pyright",
        "pytest",
        "ruff",
        "tox",
        "tsc",
        "vitest",
        "yarn",
    }
)

# argv tokens that mean "this changed the tree".
_MODIFY_COMMANDS: Final[frozenset[str]] = frozenset(
    {"cp", "install", "mkdir", "mv", "patch", "rm", "sed-i", "tee", "touch"}
)

# `git` sub-commands that only read.
_GIT_READ_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {"blame", "diff", "log", "ls-files", "show", "status"}
)

_MAX_COMMAND_CHARS: Final[int] = 400
_MAX_ERROR_CHARS: Final[int] = 400
_MAX_PATHS_PER_CALL: Final[int] = 20


class ToolCallRecord(BaseModel):
    """One tool call mergeCraft mediated, normalised for auditing.

    Deliberately *not* a dump of the arguments. The packet is written to disk
    and surfaced as an Action output, and tool arguments routinely carry
    tokens, diff bodies and log excerpts. What the checks actually need is the
    call's identity, its outcome, and the paths it named — so that is all this
    keeps, with the command text redacted and truncated.

    ``ok`` and ``outcome_ok`` are different failures and drive different
    checks. ``ok=False`` means the *call* raised. ``outcome_ok=False`` means
    the call succeeded and the thing it ran reported failure (a non-zero exit,
    a failing gate). ``outcome_ok=None`` means the tool has no such notion.
    """

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1)
    tool: str
    signature: str
    """Stable digest of ``(tool, normalised arguments)`` — the loop key."""
    intent: Intent
    ok: bool
    outcome_ok: bool | None = None
    error: str | None = None
    failure_class: FailureClass = "unknown"
    """Classifier for ``ok=False`` rows; derived from ``error`` when unset."""
    command: str | None = None
    paths: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _derive_failure_class(self) -> Self:
        if not self.ok and self.error and self.failure_class == "unknown":
            self.failure_class = classify_failure_class(self.error)
        return self


class ExternalTraceRef(BaseModel):
    """Optional enrichment from an external agent trace (D8, #56).

    Declared in the schema so a consumer can tell an *unenriched* record from
    an enriched one, and never required: every check runs on the MCP-only
    record. When mergeCraft's tracing programme (#56) is enabled, its
    ``tool.call`` spans — which do cover a driver's native ``Read``/``Edit``
    — can be adapted into ``tool_calls`` here, which is what lifts
    ``read_coverage`` for drivers whose file access never crosses MCP.
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    event_count: int = Field(ge=0)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)


class TrajectoryRecord(BaseModel):
    """How this run produced its change (#43).

    Field names track #43's acceptance criteria one-for-one: files read, files
    modified, commands run, tests run, failures observed, fixes after failures,
    retries, unresolved errors, completion claims.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = TRAJECTORY_SCHEMA_VERSION
    sources: list[str] = Field(default_factory=list)
    """Which substrates populated this record — see the ``SOURCE_*`` constants."""
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    files_read: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    commands_run: list[str] = Field(default_factory=list)
    tests_run: list[str] = Field(default_factory=list)
    failures_observed: list[str] = Field(default_factory=list)
    fixes_after_failures: int = Field(default=0, ge=0)
    retries: int = Field(default=0, ge=0)
    unresolved_errors: list[str] = Field(default_factory=list)
    completion_claims: list[str] = Field(default_factory=list)
    read_coverage: bool = False
    """True when *some* read was observed, so "unread" is a real conclusion."""
    regions_cleared: list[str] = Field(default_factory=list)
    """Diff regions ruled out (no actionable finding) — D8 cheap pin; optional."""
    external_trace: ExternalTraceRef | None = None


def _argv(command: str) -> list[str]:
    """Split a command into argv, falling back to whitespace on bad quoting."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _looks_like_path(token: str) -> bool:
    """True for tokens that plausibly name a file in the checkout.

    Deliberately conservative: a false path in ``files_read`` would make
    ``changed-unread-file`` silently stop firing, which is worse than missing
    one. Flags, URLs and bare words are all rejected.
    """
    if not token or token.startswith("-") or "://" in token:
        return False
    if token.startswith(("/", "~")):
        return False
    return "/" in token or "." in token.lstrip(".")


def _paths_in(values: Any) -> list[str]:
    """Collect plausible repo-relative paths from an arbitrary argument tree."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if len(found) >= _MAX_PATHS_PER_CALL:
            return
        if isinstance(node, str):
            if _looks_like_path(node):
                found.append(node)
            return
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(values)
    seen: set[str] = set()
    unique: list[str] = []
    for path in found:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def _command_intent(tool: str, command: str) -> Intent:
    """Derive intent for the general-purpose ``shell`` / ``git`` tools."""
    argv = _argv(command)
    if not argv:
        return "other"
    head = argv[0].rsplit("/", maxsplit=1)[-1]
    if tool == "git" or head == "git":
        sub = next((token for token in argv[1:] if not token.startswith("-")), "")
        return "read" if sub in _GIT_READ_SUBCOMMANDS else "modify"
    if head in _VERIFY_COMMANDS:
        return "verify"
    if head in _READ_COMMANDS:
        # `sed -i` edits in place; every other sed invocation only prints.
        if head == "sed" and any(token.startswith("-i") for token in argv[1:]):
            return "modify"
        return "read"
    if head in _MODIFY_COMMANDS:
        return "modify"
    return "other"


def classify_failure_class(error: str | None) -> FailureClass:
    """Derive a failure class from the error text stored on a tool call.

    String matching on recorded prose is a deliberate trade-off: it lets plan 12
    classify failures in the auditor without editing ``mcp/shared.py::execute``,
    which plan 13 owns. The follow-up is to stamp ``failure_class`` from the
    typed exception at that choke point and treat this function as a fallback
    for records that predate the seam.
    """
    if not error:
        return "unknown"
    lowered = error.lower()
    if any(marker in lowered for marker in _SCHEMA_FAILURE_MARKERS):
        return "schema"
    if any(marker in lowered for marker in _POLICY_FAILURE_MARKERS):
        return "policy"
    from mergecraft.agents.codex import USER_NAMESPACE_FAILURES, is_user_namespace_failure
    from mergecraft.mcp.git import _AUTH_FAILURE_MARKERS

    if is_user_namespace_failure(error) or any(
        marker in error for marker in USER_NAMESPACE_FAILURES
    ):
        return "environment"
    if any(marker in lowered for marker in _AUTH_FAILURE_MARKERS):
        return "environment"
    if "newuidmap" in lowered or "bwrap" in lowered:
        return "environment"
    if any(marker in lowered for marker in _TRANSIENT_FAILURE_MARKERS):
        return "transient"
    return "unknown"


def classify_tool_intent(tool: str, arguments: dict[str, Any] | None) -> Intent:
    """Return the trajectory intent of one tool call.

    Named tools resolve from the table; ``shell`` and ``git`` resolve from the
    command they were asked to run. An unrecognised tool is ``"other"``, never
    ``"verify"`` or ``"complete"`` — guessing in that direction would let an
    unknown tool silence ``no-post-edit-verification`` or
    ``missing-completion-signal``.
    """
    known = _TOOL_INTENTS.get(tool)
    if known is not None:
        return known
    command = str((arguments or {}).get("command") or "")
    if command:
        return _command_intent(tool, command)
    return "other"


def _signature(tool: str, arguments: dict[str, Any] | None) -> str:
    """Stable identity for "the same call again", used for loop detection."""
    payload = repr(sorted((str(key), repr(value)) for key, value in (arguments or {}).items()))
    digest = hashlib.sha256(f"{tool}\x00{payload}".encode()).hexdigest()
    return f"{tool}:{digest[:16]}"


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}…"


def record_tool_call(
    state: ToolState,
    *,
    tool: str,
    arguments: dict[str, Any] | None,
    ok: bool,
    outcome_ok: bool | None = None,
    error: str | None = None,
) -> ToolCallRecord:
    """Append one mediated tool call to the run's trajectory (D8).

    Called from ``mcp/server.py``'s ``tools/call`` handler — the one door
    every agent tool call goes through — so the record is populated on every
    run without configuration. Mutates ``state`` and returns the row it
    appended; no I/O, so it cannot fail a tool call.

    Command text and error text are redacted through
    :func:`mergecraft.analyzers.redact.redact_secrets` and truncated before
    they are stored, because the record is serialized into the evidence packet
    and surfaced as an Action output.
    """
    command_raw = str((arguments or {}).get("command") or "") or None
    error_text = _truncate(redact_secrets(error), _MAX_ERROR_CHARS) if error else None
    row = ToolCallRecord(
        sequence=len(state.tool_calls) + 1,
        tool=tool,
        signature=_signature(tool, arguments),
        intent=classify_tool_intent(tool, arguments),
        ok=ok,
        outcome_ok=outcome_ok,
        error=error_text,
        failure_class=classify_failure_class(error_text) if not ok and error_text else "unknown",
        command=_truncate(redact_secrets(command_raw), _MAX_COMMAND_CHARS) if command_raw else None,
        paths=_paths_in(arguments),
    )
    state.tool_calls.append(row)
    return row


def outcome_ok_from_result(result: Any) -> bool | None:
    """Read "did the thing the tool ran succeed?" out of a tool result.

    Returns ``None`` when the tool has no such notion, which is the common
    case — only ``shell`` and the gate-running tools report an outcome
    separate from the call itself. ``None`` is what keeps
    ``unresolved-failure`` keyed to real reported failures rather than to
    every tool whose payload happens to lack an ``exitCode``.
    """
    if not isinstance(result, dict):
        return None
    for key in ("exitCode", "exit_code"):
        value = result.get(key)
        if isinstance(value, int):
            return value == 0
    for key in ("timedOut", "timed_out"):
        if result.get(key) is True:
            return False
    value = result.get("success")
    if isinstance(value, bool):
        return value
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def build_trajectory_record(
    state: ToolState,
    *,
    files_modified: list[str] | None = None,
    external_trace: ExternalTraceRef | None = None,
) -> TrajectoryRecord:
    """Assemble the record from recorded tool calls and the run's diff.

    Pure: reads the state it is handed and returns a value. No I/O, no
    ``os.environ``, no network — the caller (``evidence/run_packet.py``) owns
    every environment-shaped input, including ``files_modified``, which comes
    from the run's own unified diff rather than from anything the agent said.

    ``external_trace`` is optional enrichment (D8): its ``tool_calls`` are
    appended after the mediated ones, which is what can lift
    ``read_coverage`` for a driver whose file reads never cross MCP.
    """
    calls: list[ToolCallRecord] = list(getattr(state, "tool_calls", []) or [])
    sources: list[str] = []
    if calls:
        sources.append(SOURCE_MCP)
    if external_trace is not None:
        calls = [*calls, *external_trace.tool_calls]
        sources.append(SOURCE_EXTERNAL_TRACE)
    if files_modified:
        sources.append(SOURCE_RUN_DIFF)

    read_paths: list[str] = []
    modified_paths: list[str] = list(files_modified or [])
    commands: list[str] = []
    tests: list[str] = []
    failures: list[str] = []
    completion: list[str] = []
    observed_read = False

    for call in calls:
        if call.command:
            commands.append(call.command)
        if call.intent == "read":
            observed_read = True
            read_paths.extend(call.paths)
        elif call.intent == "modify":
            modified_paths.extend(call.paths)
        elif call.intent == "verify":
            if call.command:
                tests.append(call.command)
        if call.intent == "complete" and call.ok:
            completion.append(call.tool)
        if call.outcome_ok is False:
            failures.append(call.command or call.signature)

    resolved: set[str] = set()
    for call in calls:
        if call.outcome_ok is True:
            resolved.add(call.command or call.signature)
    unresolved = [item for item in _dedupe(failures) if item not in resolved]
    fixes = len([item for item in _dedupe(failures) if item in resolved])

    seen_signatures: dict[str, int] = {}
    for call in calls:
        seen_signatures[call.signature] = seen_signatures.get(call.signature, 0) + 1
    retries = sum(count - 1 for count in seen_signatures.values() if count > 1)

    return TrajectoryRecord(
        sources=_dedupe(sources),
        tool_calls=calls,
        files_read=_dedupe(read_paths),
        files_modified=_dedupe(modified_paths),
        commands_run=_dedupe(commands),
        tests_run=_dedupe(tests),
        failures_observed=_dedupe(failures),
        fixes_after_failures=fixes,
        retries=retries,
        unresolved_errors=unresolved,
        completion_claims=_dedupe(completion),
        read_coverage=observed_read or external_trace is not None,
        external_trace=external_trace,
    )


__all__ = [
    "SOURCE_EXTERNAL_TRACE",
    "SOURCE_MCP",
    "SOURCE_RUN_DIFF",
    "TRAJECTORY_SCHEMA_VERSION",
    "ExternalTraceRef",
    "FailureClass",
    "Intent",
    "ToolCallRecord",
    "TrajectoryRecord",
    "build_trajectory_record",
    "classify_failure_class",
    "classify_tool_intent",
    "outcome_ok_from_result",
    "record_tool_call",
]
