"""Agent-context construction + dispatch helpers used by ``main.py``.

Extracted from ``main.py`` so the orchestrator stays under the 1k-line ceiling.
The three pieces — ``_AgentRunArgs`` closure bundle, ``_build_tool_context``
constructor, and ``_run_agent_with_timeout`` runner — are tightly coupled to
the agent execution path and naturally form one module.

The closures ``_run_agent_once`` and ``_execute_agent`` that
``_run_agent_with_timeout`` uses live alongside it as private helpers so the
``asyncio.wait_for`` coroutine-name filter (test
``test_setup_timeout_is_deducted_from_the_run_budget``) still resolves to
``_execute_agent``.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.analyzers.sarif_upload import resolve_sarif_upload_enabled
from mergecraft.analyzers.trust import allow_repo_command_overrides, resolve_analyzers_mode
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.modes import Mode, _custom_modes, compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.utils.agent_resolve import (
    resolve_model,
    resolve_runtime_agent,
    run_with_model_chain,
)
from mergecraft.utils.instructions import resolve_instructions
from mergecraft.utils.process_group import kill_all_active_process_groups

if TYPE_CHECKING:
    from mergecraft.agents.shared import Agent, AgentResult, AgentRunContext
    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.tool_state import ToolState
    from mergecraft.types import AgentId
    from mergecraft.utils.github import GitHubClient


class _AgentTimeoutError(RuntimeError):
    """Marks the ``asyncio.wait_for`` timeout path (D3/W5.2).

    A plain ``RuntimeError`` would be indistinguishable from any other agent
    crash once it reaches the outer catch-all; this subclass lets
    ``_classify_error_outcome`` (still in ``main.py``) tag it
    ``RunOutcome.timed_out`` instead of the generic ``infra_error`` default.
    """


def _payload_to_ctx(payload: dict[str, Any]) -> ResolvedPayload:
    event_val = payload.get("event")
    raw_event: dict[str, Any] = event_val if isinstance(event_val, dict) else {}
    event = PayloadEvent(
        trigger=str(raw_event.get("trigger") or "unknown"),
        issue_number=raw_event.get("issue_number"),
        is_pr=bool(raw_event.get("is_pr")),
        branch=raw_event.get("branch"),
        title=raw_event.get("title"),
        body=raw_event.get("body"),
    )
    return ResolvedPayload(
        event=event,
        shell=payload.get("shell") or "restricted",
        push=payload.get("push") or "restricted",
        triggerer=payload.get("triggerer"),
        model=payload.get("model"),
        cwd=payload.get("cwd"),
        generate_summary=bool(payload.get("generateSummary")),
        status_checks=bool(payload.get("statusChecks")),
        suggest_eval_add=bool(payload.get("suggestEvalAdd")),
        timeout=payload.get("timeout"),
        prompt=str(payload.get("prompt") or ""),
        xrepo=payload.get("xrepo"),
        extra=payload,
    )


def _build_tool_context(
    *,
    payload: dict[str, Any],
    settings: RepoSettings,
    run_context: Any,
    agent_id: AgentId,
    github: GitHubClient,
    token_ref: Any,
    modes: list[Mode],
    tool_state: ToolState,
    tmpdir: str,
    trust_tier: Literal["trusted", "untrusted"],
    resolved_model: str | None,
) -> ToolContext:
    """Build the ``ToolContext`` wired up for the MCP server + agent run.

    Encapsulates the ``_payload_to_ctx(payload)`` -> ``ctx_payload`` ->
    ``ToolContext(...)`` construction. ``analyzers_mode`` and
    ``sarif_upload_enabled`` are resolved in-place so the call site only
    deals with the final ``ToolContext`` value.
    """
    ctx_payload = _payload_to_ctx(payload)
    analyzers_mode = resolve_analyzers_mode(os.environ.get("INPUT_ANALYZERS"))
    sarif_upload_enabled = resolve_sarif_upload_enabled(
        action_input=os.environ.get("INPUT_SARIF_UPLOAD"),
        repo_setting=settings.analyzers.sarif_upload,
    )
    return ToolContext(
        agent_id=agent_id,
        repo=RepoIdentity(owner=run_context.repo.owner, name=run_context.repo.name),
        payload=ctx_payload,
        github=github,
        github_installation_token=token_ref.mcp_token,
        git_token=token_ref.git_token,
        api_token=run_context.api_token,
        modes=modes,
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=tmpdir,
        refresh_git_token=token_ref.refresh_git_token,
        read_token=token_ref.read_token,
        xrepo=payload.get("xrepo"),
        prepush_script=settings.prepush_script,
        pr_approve_enabled=settings.pr_approve_enabled,
        auto_merge_enabled=settings.auto_merge_enabled,
        signed_commits=settings.signed_commits,
        mode_instructions=settings.mode_instructions,
        static_checks=[
            StaticCheckConfig(
                name=check.name,
                command=check.command,
                suffixes=tuple(check.suffixes),
            )
            for check in settings.static_checks
        ],
        static_checks_enabled=(
            ctx_payload.shell != "disabled" and allow_repo_command_overrides(trust_tier)
        ),
        ci_gate_checks=dict(settings.ci_evidence.gates),
        ci_sarif_artifacts=list(settings.ci_evidence.sarif_artifacts),
        analyzers_mode=analyzers_mode,
        trust_tier=trust_tier,
        analyzers_settings_enabled=settings.analyzers.enabled,
        sarif_upload_enabled=sarif_upload_enabled,
        run_id=int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None,
        job_id=os.environ.get("GITHUB_JOB"),
        oss=run_context.oss,
        plan="unknown",
        resolved_model=resolved_model,
        suggest_eval_add=bool(payload.get("suggestEvalAdd")),
    )


@dataclass(slots=True)
class _AgentRunArgs:
    """Closure bundle for ``_run_agent_with_timeout``.

    The agent-run block in :func:`main` references 15 ``main``-local
    variables (agent, run_ctx, payload, output_schema, tool_state,
    tool_context, etc.). Hoisting it out as a module-scope helper would
    require threading that many parameters; the audit allows up to 5, so
    we bundle the closure variables here behind a single
    ``_AgentRunArgs`` arg. The dataclass is private (``_``-prefixed) so it
    does not extend the public surface.
    """

    agent: Agent
    agent_id: AgentId
    selected_slug: str | None
    use_model_chain: bool
    settings: RepoSettings
    model_head: str | None
    model_pin: bool
    run_ctx: AgentRunContext
    payload: dict[str, Any]
    run_context: Any  # ResolvedRunContext with .repo
    output_schema: Any
    tool_state: ToolState
    tool_context: ToolContext
    setup_hook_failure: str
    setup_script_skip_reason: str


async def _run_agent_with_timeout(
    args: _AgentRunArgs,
    agent_timeout_ms: int | None,
    timeout_raw: Any,
) -> tuple[str | None, AgentResult]:
    """Run the model-chain agent dispatch with an optional timeout.

    Encapsulates the ``_run_agent_once`` / ``_execute_agent`` closures
    (W4/D8) and the :func:`asyncio.wait_for` deadline dance (S1 / F6,
    D3/W5.2). Raises :class:`_AgentTimeoutError` on overrun; the outer
    catch-all in :func:`main` routes it to ``RunOutcome.timed_out``. The
    ``timeout_raw`` value is only used to format the timeout error
    message, matching the inline behaviour in :func:`main`.
    """

    async def _run_agent_once(slug: str) -> AgentResult:
        attempt_model = resolve_model(slug=slug, respect_env_override=False)
        attempt_agent = resolve_runtime_agent(model=attempt_model)
        attempt_agent_id = attempt_agent.name

        if attempt_agent_id == args.agent_id:
            attempt_ctx = replace(args.run_ctx, resolved_model=attempt_model)
        else:
            attempt_modes = [
                *compute_modes(attempt_agent_id, args.settings.signed_commits),
                *_custom_modes(args.settings.modes),
            ]
            attempt_instructions = resolve_instructions(
                payload=args.payload,
                repo=args.run_context.repo,
                modes=attempt_modes,
                agent_id=attempt_agent_id,
                output_schema=args.output_schema,
                signed_commits=args.settings.signed_commits,
                learnings_file_path=args.tool_state.learnings_file_path,
                learnings_headings=args.settings.learnings_headings,
                setup_hook_failure=args.setup_hook_failure,
                setup_script_skip_reason=args.setup_script_skip_reason,
                xrepo_brief=args.settings.xrepo_brief,
                xrepo_learnings_file_path=args.tool_state.xrepo_learnings_file_path,
                xrepo_learnings_headings=args.settings.xrepo_learnings_headings,
            )
            attempt_denied = subagent_denied_tool_names(
                replace(args.tool_context, agent_id=attempt_agent_id),
                args.output_schema,
            )
            attempt_ctx = replace(
                args.run_ctx,
                resolved_model=attempt_model,
                instructions=attempt_instructions,
                subagent_denied_tools=attempt_denied,
            )
            # The four lines below mutate ``tool_context`` / ``tool_state``
            # by reference on model-chain fallback — this is intentional.
            # The MCP server reads the live ``ToolContext`` mid-run, so the
            # agent that's actually running must own the live fields
            # (``agent_id``, ``modes``, ``resolved_model``). ``tool_state``
            # must follow ``tool_context.modes`` so the publish-span
            # ``attrs_source`` attributes the run to the prompt version that
            # actually ran, not the original mode's version (#145 contract).
            args.tool_context.agent_id = attempt_agent_id
            args.tool_context.modes = attempt_modes
            args.tool_state.modes = attempt_modes
            args.tool_context.resolved_model = attempt_model
            logger.info(
                "» model chain advanced to agent={} model={}",
                attempt_agent_id,
                attempt_model or "(auto)",
            )
        return await attempt_agent.run(attempt_ctx)

    async def _execute_agent() -> tuple[str | None, AgentResult]:
        if args.use_model_chain:
            winning_slug, chain_result = await run_with_model_chain(
                settings=args.settings,
                run_once=_run_agent_once,
                head=args.model_head,
                pin=args.model_pin,
            )
            return winning_slug, chain_result
        return args.selected_slug, await args.agent.run(args.run_ctx)

    agent_task = asyncio.create_task(_execute_agent())
    if agent_timeout_ms is None:
        return await agent_task
    try:
        return await asyncio.wait_for(agent_task, timeout=agent_timeout_ms / 1000.0)
    except TimeoutError:
        agent_task.cancel()
        kill_all_active_process_groups()
        msg = f"agent run timed out after {timeout_raw or '1h'}"
        raise _AgentTimeoutError(msg) from None


__all__ = [
    "_AgentRunArgs",
    "_AgentTimeoutError",
    "_build_tool_context",
    "_run_agent_with_timeout",
]
