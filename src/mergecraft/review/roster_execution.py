"""Server-side dispatch for multi-reviewer rosters (D15).

The orchestrator harness still exposes secondary reviewers as subagents, but
mergeCraft also runs any configured secondary reviewer bindings itself so a
primary model that never spawns ``reviewer2`` cannot skip the second provider.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.registry import AgentBinding, AgentRole, load_registry
from mergecraft.agents.verifier import verifier_denied_tool_names
from mergecraft.mcp.tool_state import (
    record_reviewer_dispatch_error,
    record_reviewer_dispatch_run,
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
    """Reviewer ids configured but neither recorded nor marked degraded."""
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


async def _run_one_secondary_reviewer(
    *,
    binding: AgentBinding,
    base_ctx: AgentRunContext,
    tool_context: ToolContext,
    settings: RepoSettings,
    payload: dict[str, Any],
    repo_root: Path,
    timeout_s: float | None,
) -> str | None:
    """Dispatch one secondary reviewer; return a hard error string or ``None``."""
    from mergecraft.agents.registry import resolve_agent_model as _resolve
    from mergecraft.modes import compute_modes
    from mergecraft.utils.instructions import resolve_instructions

    try:
        resolved = _resolve(binding, settings=settings)
    except RuntimeError as exc:
        record_reviewer_dispatch_error(
            tool_context.tool_state,
            agent_id=binding.agent_id,
            reason=str(exc),
        )
        return str(exc)

    slug = resolved.dispatched_model
    status = credential_status_for_slug(
        slug,
        settings=settings,
        cwd=repo_root,
        wired=True,
    )
    if not status.available:
        reason = format_credential_gap_message(slug=slug, status=status, wired=True)
        record_reviewer_dispatch_error(
            tool_context.tool_state,
            agent_id=binding.agent_id,
            reason=reason,
        )
        return reason

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
        learnings_file_path=tool_context.tool_state.learnings_file_path,
        learnings_headings=settings.learnings_headings,
        setup_hook_failure=tool_context.tool_state.setup_hook_failure or "",
        setup_script_skip_reason=tool_context.tool_state.setup_script_skip_reason or "",
        xrepo_brief=settings.xrepo_brief,
        xrepo_learnings_file_path=tool_context.tool_state.xrepo_learnings_file_path,
        xrepo_learnings_headings=settings.xrepo_learnings_headings,
        repo_root=repo_root,
        trust_tier=str(tool_context.tool_state.trust_tier or "untrusted"),
        review_mcp_names=list(tool_context.tool_state.review_mcp_names),
    )
    system = (instructions.system or "").strip()
    instructions = replace(
        instructions,
        system=f"{system}\n\n{_ROSTER_SUBMIT_INSTRUCTIONS}".strip()
        if system
        else _ROSTER_SUBMIT_INSTRUCTIONS,
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
    before_findings = _agent_findings_snapshot(tool_context.tool_state)
    logger.info(
        "» server roster dispatch agent={} model={}",
        binding.agent_id,
        slug,
    )

    async def _invoke() -> AgentResult:
        from mergecraft.tracing import get_tracer_from_settings
        from mergecraft.tracing.signals import agent_run_span

        with agent_run_span(
            get_tracer_from_settings(settings),
            agent_id=binding.agent_id,
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
        reason = f"secondary reviewer {binding.agent_id!r} timed out after {timeout_s:.0f}s"
        record_reviewer_dispatch_error(
            tool_context.tool_state,
            agent_id=binding.agent_id,
            reason=reason,
        )
        return reason

    if not result.success:
        reason = result.error or "secondary reviewer agent failed"
        record_reviewer_dispatch_error(
            tool_context.tool_state,
            agent_id=binding.agent_id,
            reason=reason,
        )
        return reason

    if not _binding_already_recorded(tool_context.tool_state, binding.agent_id):
        findings = _findings_since(before_findings, tool_context.tool_state)
        record_reviewer_dispatch_run(
            tool_context.tool_state,
            agent_id=binding.agent_id,
            findings=findings,
            model_slug=slug,
        )
    return None


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
            error = await _run_one_secondary_reviewer(
                binding=binding,
                base_ctx=base_run_ctx,
                tool_context=tool_context,
                settings=effective_settings,
                payload=payload,
                repo_root=root,
                timeout_s=timeout,
            )
            if error:
                hard_error = error
                break
            dispatched.append(binding.agent_id)
        if hard_error:
            break

    gaps = roster_dispatch_gaps(registry, tool_context.tool_state)
    if gaps and hard_error is None:
        hard_error = roster_dispatch_failure_message(gaps)
    return RosterExecutionSummary(hard_error=hard_error, dispatched_agent_ids=tuple(dispatched))


def primary_repo_state_dir(tool_state: ToolState) -> str:
    from mergecraft.mcp.tool_state import primary_repo_state

    repo = primary_repo_state(tool_state)
    return repo.dir or str(Path.cwd())


__all__ = [
    "RosterExecutionSummary",
    "roster_dispatch_failure_message",
    "roster_dispatch_gaps",
    "run_pending_roster_reviewers",
    "secondary_reviewer_agent_ids",
]
