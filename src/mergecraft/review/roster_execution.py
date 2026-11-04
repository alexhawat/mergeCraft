"""Server-side dispatch for multi-reviewer rosters (D15).

The orchestrator harness still exposes secondary reviewers as subagents, but
mergeCraft also runs any configured secondary reviewer bindings itself so a
primary model that never spawns ``reviewer2`` cannot skip the second provider.

The same dispatch core runs the opt-in file-group fan-out
(:func:`run_file_group_reviewers`): one read-only reviewer per bounded group of
a large diff, recorded under ``file-group/<group-id>``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from loguru import logger

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.registry import AgentBinding, AgentRole, Registry, load_registry
from mergecraft.agents.verifier import verifier_denied_tool_names
from mergecraft.mcp.tool_state import (
    record_reviewer_dispatch_error,
    record_reviewer_dispatch_run,
)
from mergecraft.review.file_group_fanout import (
    FanoutSummary,
    FileGroup,
    dispatch_file_groups,
    file_group_agent_id,
    plan_file_groups,
)
from mergecraft.review.roster_dispatch import reviewer_dispatch_batches
from mergecraft.utils.agent_resolve import (
    credential_status_for_slug,
    format_credential_gap_message,
    resolve_model,
    resolve_runtime_agent,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.agents.shared import AgentResult, AgentRunContext
    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import ToolState

_ROSTER_SUBMIT_INSTRUCTIONS = """
You are a secondary reviewer on this run. Review the diff and record your outcome
with `record_reviewer_dispatch_run` (pass your ``agent_id`` and structured findings).
Do **not** call `submit_review_verdict` — the primary reviewer owns the terminal verdict.
""".strip()


@dataclass(frozen=True, slots=True)
class RosterExecutionSummary:
    """Outcome of server-side secondary reviewer dispatch."""

    hard_error: str | None
    dispatched_agent_ids: tuple[str, ...]
    # The named infrastructure reason a failed secondary carried, when it had
    # one (an expired Codex subscription login, for instance). It travels with
    # ``hard_error`` so the run can end as ``infra_error`` rather than as a
    # failed review.
    infra_reason: str | None = None


class _SecondaryOutcome(NamedTuple):
    """One secondary dispatch's hard error and its infrastructure reason, if any."""

    error: str | None
    infra_reason: str | None = None


def apply_roster_failure(
    result: AgentResult,
    summary: RosterExecutionSummary | None,
) -> AgentResult:
    """Fold a roster dispatch failure into the run's result (D15).

    A secondary reviewer that died of an infrastructure fault must read as
    ``infra_error``, not as a failed review. The primary result carries no reason
    of its own — the failure happened in another binding — so the roster's named
    reason is merged onto the result the primary produced, leaving whatever
    metadata the primary already carried intact.
    """
    if summary is None or not summary.hard_error:
        return result
    from mergecraft.agents.shared import INFRA_REASON_KEY

    metadata = dict(result.metadata or {})
    if summary.infra_reason:
        metadata[INFRA_REASON_KEY] = summary.infra_reason
    return replace(result, success=False, error=summary.hard_error, metadata=metadata)


def secondary_reviewer_agent_ids(registry: object) -> tuple[str, ...]:
    """Return non-primary reviewer ``agent_id`` values that must dispatch."""
    from mergecraft.agents.registry import Registry

    if not isinstance(registry, Registry):
        msg = "registry must be a Registry instance"
        raise TypeError(msg)
    reviewers = registry.resolve_roles(AgentRole.reviewer)
    if len(reviewers) <= 1:
        return ()
    primary_id = reviewers[0].agent_id
    return tuple(binding.agent_id for binding in reviewers if binding.agent_id != primary_id)


def roster_dispatch_gaps(registry: object, tool_state: ToolState) -> tuple[str, ...]:
    """Reviewer ids configured but neither recorded nor marked degraded.

    Only registry reviewer bindings can be gaps: ``file-group/<group-id>`` runs
    and errors from the file-group fan-out neither satisfy nor create one.
    """
    required = secondary_reviewer_agent_ids(registry)
    if not required:
        return ()
    recorded = {run.agent_id for run in tool_state.reviewer_dispatch_runs}
    recorded.update(tool_state.reviewer_dispatch_errors)
    return tuple(agent_id for agent_id in required if agent_id not in recorded)


def roster_dispatch_failure_message(gaps: tuple[str, ...]) -> str:
    if not gaps:
        return ""
    joined = ", ".join(gaps)
    return (
        "secondary reviewer dispatch incomplete — the following reviewer binding(s) "
        f"never reached their provider: {joined}"
    )


def _agent_findings_snapshot(tool_state: ToolState) -> tuple[str, ...]:
    rows: list[str] = []
    for row in tool_state.agent_findings:
        if isinstance(row, dict):
            fp = row.get("fingerprint")
            if isinstance(fp, str) and fp:
                rows.append(fp)
    return tuple(rows)


def _findings_since(
    before: tuple[str, ...],
    tool_state: ToolState,
) -> list[dict[str, Any]]:
    seen = set(before)
    introduced: list[dict[str, Any]] = []
    for row in tool_state.agent_findings:
        if not isinstance(row, dict):
            continue
        fp = row.get("fingerprint")
        if not isinstance(fp, str) or not fp or fp in seen:
            continue
        introduced.append(dict(row))
        seen.add(fp)
    return introduced


def _binding_already_recorded(tool_state: ToolState, agent_id: str) -> bool:
    for run in tool_state.reviewer_dispatch_runs:
        if run.agent_id == agent_id:
            return True
    return agent_id in tool_state.reviewer_dispatch_errors


async def _dispatch_reviewer(
    *,
    binding: AgentBinding,
    record_as: str,
    label: str,
    base_ctx: AgentRunContext,
    tool_context: ToolContext,
    settings: RepoSettings,
    payload: dict[str, Any],
    repo_root: Path,
    timeout_s: float | None,
    extra_instructions: str = "",
    owns_finding: Callable[[dict[str, Any]], bool] | None = None,
) -> _SecondaryOutcome:
    """Run one reviewer binding server-side and record its outcome under ``record_as``.

    The shared core of the secondary roster and the file-group fan-out: resolve
    the binding's model, check its credential, render the reviewer instructions
    plus :data:`_ROSTER_SUBMIT_INSTRUCTIONS` (and ``extra_instructions``), run
    the agent under ``timeout_s``, then record either the new findings
    (``record_reviewer_dispatch_run``) or the reason it produced none
    (``record_reviewer_dispatch_error``). An exception the agent runtime raises
    other than a timeout propagates to the caller unrecorded.

    Args:
        binding: The registry binding whose model reviews.
        record_as: The agent id the outcome is recorded under.
        label: Human name used in the timeout reason (``secondary reviewer``).
        base_ctx: The primary run context the dispatch is derived from.
        tool_context: The run's tool context; its ``agent_id`` is restored.
        settings: The run-scope repo settings.
        payload: The resolved run payload used to render instructions.
        repo_root: The checkout root.
        timeout_s: Seconds the agent may run; ``None`` or ``<= 0`` means no cap.
        extra_instructions: Text appended after the roster submit instructions.
        owns_finding: When given, only new finding rows it accepts are
            attributed to this dispatch's run.

    Returns:
        The dispatch's hard error and infrastructure reason, both ``None`` on success.
    """
    from mergecraft.agents.registry import resolve_agent_model as _resolve
    from mergecraft.modes import compute_modes
    from mergecraft.utils.instructions import resolve_instructions

    tool_state = tool_context.tool_state
    try:
        resolved = _resolve(binding, settings=settings)
    except RuntimeError as exc:
        record_reviewer_dispatch_error(tool_state, agent_id=record_as, reason=str(exc))
        return _SecondaryOutcome(str(exc))

    slug = resolved.dispatched_model
    status = credential_status_for_slug(
        slug,
        settings=settings,
        cwd=repo_root,
        wired=True,
    )
    if not status.available:
        reason = format_credential_gap_message(slug=slug, status=status, wired=True)
        record_reviewer_dispatch_error(tool_state, agent_id=record_as, reason=reason)
        return _SecondaryOutcome(reason)

    attempt_model = resolve_model(slug=slug, respect_env_override=False)
    attempt_agent = resolve_runtime_agent(model=attempt_model, settings=settings)
    attempt_modes = compute_modes(
        attempt_agent.name,
        settings.signed_commits,
        inline_budget=settings.analyzers.inline_budget,
    )
    from mergecraft.config.settings import RepoInfo

    instructions = resolve_instructions(
        payload=payload,
        repo=RepoInfo(owner=tool_context.repo.owner, name=tool_context.repo.name),
        modes=attempt_modes,
        agent_id=binding.agent_id,
        signed_commits=settings.signed_commits,
        learnings_file_path=tool_state.learnings_file_path,
        learnings_headings=settings.learnings_headings,
        setup_hook_failure=tool_state.setup_hook_failure or "",
        setup_script_skip_reason=tool_state.setup_script_skip_reason or "",
        xrepo_brief=settings.xrepo_brief,
        xrepo_learnings_file_path=tool_state.xrepo_learnings_file_path,
        xrepo_learnings_headings=settings.xrepo_learnings_headings,
        repo_root=repo_root,
        trust_tier=str(tool_state.trust_tier or "untrusted"),
        review_mcp_names=list(tool_state.review_mcp_names),
    )
    tail = _ROSTER_SUBMIT_INSTRUCTIONS
    if extra_instructions.strip():
        tail = f"{tail}\n\n{extra_instructions.strip()}"
    system = (instructions.system or "").strip()
    instructions = replace(
        instructions,
        system=f"{system}\n\n{tail}" if system else tail,
    )
    previous_agent_id = tool_context.agent_id
    tool_context.agent_id = attempt_agent.name
    try:
        denied = subagent_denied_tool_names(tool_context, None)
        verifier_denied = verifier_denied_tool_names(tool_context, None)
    finally:
        tool_context.agent_id = previous_agent_id
    run_ctx = replace(
        base_ctx,
        resolved_model=attempt_model,
        instructions=instructions,
        subagent_denied_tools=denied,
        verifier_denied_tools=verifier_denied,
    )
    before_findings = _agent_findings_snapshot(tool_state)
    logger.info(
        "» server roster dispatch agent={} model={}",
        record_as,
        slug,
    )

    async def _invoke() -> AgentResult:
        from mergecraft.tracing import get_tracer_from_settings
        from mergecraft.tracing.signals import agent_run_span

        with agent_run_span(
            get_tracer_from_settings(settings),
            agent_id=record_as,
            role="reviewer",
            executed_model=attempt_model,
        ):
            return await attempt_agent.run(run_ctx)

    try:
        if timeout_s is not None and timeout_s > 0:
            result = await asyncio.wait_for(_invoke(), timeout=timeout_s)
        else:
            result = await _invoke()
    except TimeoutError:
        reason = f"{label} {record_as!r} timed out after {timeout_s:.0f}s"
        record_reviewer_dispatch_error(tool_state, agent_id=record_as, reason=reason)
        return _SecondaryOutcome(reason)

    if not result.success:
        from mergecraft.agents.shared import INFRA_REASON_KEY

        reason = result.error or f"{label} agent failed"
        infra_reason = (result.metadata or {}).get(INFRA_REASON_KEY)
        record_reviewer_dispatch_error(tool_state, agent_id=record_as, reason=reason)
        return _SecondaryOutcome(
            reason,
            infra_reason if isinstance(infra_reason, str) and infra_reason else None,
        )

    if not _binding_already_recorded(tool_state, record_as):
        findings = _findings_since(before_findings, tool_state)
        if owns_finding is not None:
            findings = [row for row in findings if owns_finding(row)]
        record_reviewer_dispatch_run(
            tool_state,
            agent_id=record_as,
            findings=findings,
            model_slug=slug,
        )
    return _SecondaryOutcome(None)


async def _run_one_secondary_reviewer(
    *,
    binding: AgentBinding,
    base_ctx: AgentRunContext,
    tool_context: ToolContext,
    settings: RepoSettings,
    payload: dict[str, Any],
    repo_root: Path,
    timeout_s: float | None,
) -> _SecondaryOutcome:
    """Dispatch one secondary reviewer; return its hard error, if any."""
    return await _dispatch_reviewer(
        binding=binding,
        record_as=binding.agent_id,
        label="secondary reviewer",
        base_ctx=base_ctx,
        tool_context=tool_context,
        settings=settings,
        payload=payload,
        repo_root=repo_root,
        timeout_s=timeout_s,
    )


async def run_pending_roster_reviewers(
    *,
    tool_context: ToolContext,
    base_run_ctx: AgentRunContext,
    settings: RepoSettings,
    payload: dict[str, Any],
    repo_root: Path | None = None,
    per_reviewer_timeout_s: float | None = None,
    remaining_timeout_s: Callable[[], float | None] | None = None,
) -> RosterExecutionSummary:
    """Dispatch every secondary reviewer that has not yet recorded an outcome."""
    from mergecraft.config.settings_snapshot import repo_settings_from_context

    root = repo_root or Path(primary_repo_state_dir(tool_context.tool_state))
    effective_settings = repo_settings_from_context(tool_context)
    registry = load_registry(settings=effective_settings, repo_root=root)
    batches = reviewer_dispatch_batches(registry)
    if not batches:
        return RosterExecutionSummary(hard_error=None, dispatched_agent_ids=())

    reviewers = registry.resolve_roles(AgentRole.reviewer)
    if len(reviewers) <= 1:
        return RosterExecutionSummary(hard_error=None, dispatched_agent_ids=())

    primary_id = reviewers[0].agent_id
    dispatched: list[str] = []
    hard_error: str | None = None
    infra_reason: str | None = None

    for batch in batches:
        for agent_id in batch:
            if agent_id == primary_id:
                continue
            try:
                binding = registry.resolve_agent_ref(agent_id)
            except KeyError:
                hard_error = f"no registry binding for secondary reviewer {agent_id!r}"
                break
            if _binding_already_recorded(tool_context.tool_state, binding.agent_id):
                continue
            timeout = float(binding.timeout_s)
            timeout = min(timeout, 900.0)
            if remaining_timeout_s is not None:
                remaining = remaining_timeout_s()
                if remaining is not None:
                    timeout = min(timeout, max(1.0, remaining))
            elif per_reviewer_timeout_s is not None:
                timeout = min(timeout, per_reviewer_timeout_s)
            outcome = await _run_one_secondary_reviewer(
                binding=binding,
                base_ctx=base_run_ctx,
                tool_context=tool_context,
                settings=effective_settings,
                payload=payload,
                repo_root=root,
                timeout_s=timeout,
            )
            if outcome.error:
                hard_error = outcome.error
                infra_reason = outcome.infra_reason
                break
            dispatched.append(binding.agent_id)
        if hard_error:
            break

    gaps = roster_dispatch_gaps(registry, tool_context.tool_state)
    if gaps and hard_error is None:
        hard_error = roster_dispatch_failure_message(gaps)
    return RosterExecutionSummary(
        hard_error=hard_error,
        dispatched_agent_ids=tuple(dispatched),
        infra_reason=infra_reason,
    )


class _FileGroupDispatchError(RuntimeError):
    """A file group produced no findings; its reason is already recorded."""


def _file_group_instructions(group: FileGroup, *, agent_id: str, diff_path: str) -> str:
    """Render the *file group* block appended to a group reviewer's instructions."""
    paths = "\n".join(f"- `{path}`" for path in group.paths)
    return (
        f"## File group `{agent_id}`\n\n"
        "This run splits a large diff into bounded read-only file groups. You review "
        f"one group: read the shared diff at `{diff_path}` and review **only** the "
        "files listed below; other reviewers cover every other file. Record each "
        "finding for these files with the finding tools, as any reviewer does. "
        "mergeCraft records this group's run under your agent id once you finish, "
        "so do not call `record_reviewer_dispatch_run` yourself.\n\n"
        f"Files in this group ({len(group.paths)}):\n{paths}"
    )


def _file_group_health_row(agent_id: str, reason: str) -> dict[str, Any]:
    """Return the run-scoped ``Minor`` row recording one failed file group.

    The row is ``Finding``-shaped so the packet loader validates it, and
    ``scope="run"`` keeps it on the run-health partition: it can tell a human
    that part of the diff went unreviewed by its group, never block a merge.
    """
    from mergecraft.analyzers.finding import make_finding

    finding = make_finding(
        tool="review",
        rule_id="file-group-dispatch-failed",
        category="Stability & Availability",
        severity="Minor",
        confidence="certain",
        message=f"file-group reviewer {agent_id} produced no findings: {reason}",
        path="",
        start_line=1,
        end_line=1,
        source="trajectory",
        scope="run",
        evidence=[f"agent_id={agent_id}"],
        remediation=(
            "The files in this group were still in the primary reviewer's scope; "
            "re-run the review, or check the group's provider and credential."
        ),
        introduced_by_pr="false",
    )
    return finding.model_dump(mode="json")


def _file_group_binding(
    registry: Registry,
    binding_ref: str | None,
) -> tuple[AgentBinding | None, str]:
    """Resolve the binding every group runs under, or the reason there is none."""
    if binding_ref:
        try:
            return registry.resolve_agent_ref(binding_ref), ""
        except KeyError:
            return None, (
                f"no registry binding {binding_ref!r} for the file-group fan-out "
                "(review.fileGroupFanout.binding)"
            )
    reviewers = registry.resolve_roles(AgentRole.reviewer)
    if not reviewers:
        return None, "no reviewer binding is configured for the file-group fan-out"
    return reviewers[0], ""


async def run_file_group_reviewers(
    *,
    tool_context: ToolContext,
    base_run_ctx: AgentRunContext,
    settings: RepoSettings,
    payload: dict[str, Any],
    repo_root: Path,
    remaining_timeout_s: Callable[[], float | None] | None = None,
) -> FanoutSummary:
    """Dispatch one read-only reviewer per file group of a large diff.

    Off unless ``review.fileGroupFanout.enabled``. The plan is built from the
    primary checkout's materialised diff; with no diff path, an unreadable diff,
    or a diff below both size thresholds, nothing is dispatched and the summary
    is empty. Each group runs through the same dispatch core as a secondary
    reviewer, under the agent id ``file-group/<group-id>``, with its own paths
    and the shared diff path in the prompt. A successful group's new findings
    are recorded with ``record_reviewer_dispatch_run``; a failed group (missing
    binding or credential, timeout, failed result, raised exception) records a
    dispatch error plus one run-scoped ``Minor`` row in ``agent_findings``, and
    is never a hard error.

    Args:
        tool_context: The run's tool context; ``agent_id`` is restored after.
        base_run_ctx: The primary run context each group dispatch derives from.
        settings: The caller's settings; the run-scope snapshot read from
            ``tool_context`` is authoritative, as for the secondary roster.
        payload: The resolved run payload used to render instructions.
        repo_root: The checkout root.
        remaining_timeout_s: Optional callable returning the run budget left.

    Returns:
        The fan-out summary; ``failures`` rows carry the bare group id.
    """
    from mergecraft.config.settings_snapshot import repo_settings_from_context
    from mergecraft.mcp.tool_state import primary_repo_state

    effective_settings = repo_settings_from_context(tool_context)
    fanout = effective_settings.review.file_group_fanout
    if not fanout.enabled:
        return FanoutSummary()
    tool_state = tool_context.tool_state
    diff_path = primary_repo_state(tool_state).diff_path
    if not diff_path:
        return FanoutSummary()
    try:
        diff_text = await asyncio.to_thread(Path(diff_path).read_text, encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("file-group fan-out skipped: cannot read diff {}: {}", diff_path, exc)
        return FanoutSummary()
    plan = plan_file_groups(
        diff_text,
        max_groups=fanout.max_groups,
        min_diff_lines=fanout.min_diff_lines,
        min_files=fanout.min_files,
    )
    if not plan.groups:
        logger.debug("file-group fan-out not planned: {}", plan.reason)
        return FanoutSummary()
    logger.info("» file-group fan-out: {}", plan.reason)

    registry = load_registry(settings=effective_settings, repo_root=repo_root)
    binding, binding_gap = _file_group_binding(registry, fanout.binding)
    concurrent = fanout.concurrency > 1 and len(plan.groups) > 1

    async def _dispatch(group: FileGroup) -> str:
        agent_id = file_group_agent_id(group.group_id)
        if binding is None:
            record_reviewer_dispatch_error(tool_state, agent_id=agent_id, reason=binding_gap)
            raise _FileGroupDispatchError(binding_gap)
        timeout = float(min(fanout.per_group_timeout_s, binding.timeout_s))
        if remaining_timeout_s is not None:
            remaining = remaining_timeout_s()
            if remaining is not None:
                timeout = min(timeout, max(1.0, remaining))
        group_paths = frozenset(group.paths)

        def _owns(row: dict[str, Any]) -> bool:
            return row.get("path") in group_paths

        try:
            outcome = await _dispatch_reviewer(
                binding=binding,
                record_as=agent_id,
                label="file-group reviewer",
                base_ctx=base_run_ctx,
                tool_context=tool_context,
                settings=effective_settings,
                payload=payload,
                repo_root=repo_root,
                timeout_s=timeout,
                extra_instructions=_file_group_instructions(
                    group, agent_id=agent_id, diff_path=str(diff_path)
                ),
                # Concurrent groups share one findings list, so a group can only
                # claim rows on its own paths; a sequential group owns every new row.
                owns_finding=_owns if concurrent else None,
            )
        except Exception as exc:
            reason = str(exc) or exc.__class__.__name__
            record_reviewer_dispatch_error(tool_state, agent_id=agent_id, reason=reason)
            raise _FileGroupDispatchError(reason) from exc
        if outcome.error:
            raise _FileGroupDispatchError(outcome.error)
        return agent_id

    def _record_failure(group_id: str, reason: str) -> None:
        agent_id = file_group_agent_id(group_id)
        if agent_id not in tool_state.reviewer_dispatch_errors:
            record_reviewer_dispatch_error(tool_state, agent_id=agent_id, reason=reason)
        tool_state.agent_findings.append(_file_group_health_row(agent_id, reason))

    return await dispatch_file_groups(
        plan,
        _dispatch,
        on_failure=_record_failure,
        concurrency=fanout.concurrency,
    )


def primary_repo_state_dir(tool_state: ToolState) -> str:
    from mergecraft.mcp.tool_state import primary_repo_state

    repo = primary_repo_state(tool_state)
    return repo.dir or str(Path.cwd())


__all__ = [
    "RosterExecutionSummary",
    "apply_roster_failure",
    "roster_dispatch_failure_message",
    "roster_dispatch_gaps",
    "run_file_group_reviewers",
    "run_pending_roster_reviewers",
    "secondary_reviewer_agent_ids",
]
