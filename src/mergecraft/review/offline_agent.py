"""Agent dispatch for offline CLI review (extracted from ``offline_review``)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.shared import AgentRunContext
from mergecraft.analyzers.trust import allow_repo_command_overrides
from mergecraft.config import load_repo_settings
from mergecraft.config.settings import (
    RepoInfo,
    apply_trust_tier_to_repo_settings,
    build_executable_config_skip_reason,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.endpoints import mcp_role_url
from mergecraft.mcp.server import start_mcp_http_server
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.review.offline_result import (
    OfflineReviewResult,
    _emit_offline_packet,
    _offline_error_outcome,
    _offline_failure,
)
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.agent_resolve import resolve_model, resolve_runtime_agent
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.instructions import resolve_instructions
from mergecraft.utils.run_bounds import (
    BudgetExhausted,
    BudgetTracker,
    budget_exhaustion_outcome,
    record_agent_usage,
    resolve_run_bounds,
)
from mergecraft.utils.skills import install_bundled_skills

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.utils.offline_diff import DiffMaterialization
    from mergecraft.utils.run_bounds import RunBounds


async def run_offline_agent_review(
    *,
    cwd: Path,
    materialization: DiffMaterialization,
    prompt: str,
    model: str | None,
    tmpdir: Path,
    output_schema: dict[str, Any] | None = None,
    evidence_packet_path: Path | None = None,
    trust_tier: str = "trusted",
    run_bounds: RunBounds | None = None,
    on_finding: Callable[[dict[str, Any]], None] | None = None,
) -> OfflineReviewResult:
    """Run the Review agent against a materialized local diff."""
    resolved_tier: Literal["trusted", "untrusted"] = (
        "trusted" if trust_tier == "trusted" else "untrusted"
    )
    stop_mcp = None
    github: GitHubClient | None = None
    try:
        github = GitHubClient(token="")
        tool_state = init_tool_state(owner="local", name=cwd.name, dir=str(cwd))
        tool_state.on_finding = on_finding
        tool_state.trust_tier = resolved_tier
        primary_repo_state(tool_state).diff_path = str(materialization.path)
        settings = load_repo_settings(root=cwd, load_learnings_files=False)
        settings, drops = apply_trust_tier_to_repo_settings(
            settings,
            resolved_tier,
            source_label="CLI offline review",
        )
        from mergecraft.enterprise.runtime import bind_enterprise_after_trust

        bind_enterprise_after_trust(settings, resolved_tier)
        setup_script_skip_reason = ""
        if drops:
            for reason in drops.values():
                logger.warning("» {}", reason)
            setup_script_skip_reason = build_executable_config_skip_reason(drops)
            if setup_script_skip_reason:
                tool_state.setup_script_skip_reason = setup_script_skip_reason
        resolved_model = resolve_model(slug=model)
        agent = resolve_runtime_agent(model=resolved_model, settings=settings)
        modes = compute_modes(agent.name, signed_commits=False)
        bounds = run_bounds or resolve_run_bounds(settings=settings)
        budget_tracker = BudgetTracker(bounds)

        payload = ResolvedPayload(
            event=PayloadEvent(trigger="unknown", title="offline diff-review"),
            shell="disabled",
            push="disabled",
            model=model,
            cwd=str(cwd),
            prompt=prompt,
            generate_summary=False,
            status_checks=False,
            suggest_eval_add=False,
        )
        tool_context = ToolContext(
            agent_id=agent.name,
            repo=RepoIdentity(owner="local", name=cwd.name),
            payload=payload,
            github=github,
            github_installation_token="",
            git_token="",
            api_token="",
            modes=modes,
            tool_state=tool_state,
            mcp_server_url="",
            tmpdir=str(tmpdir),
            signed_commits=False,
            pr_approve_enabled=False,
            auto_merge_enabled=False,
            static_checks=[
                StaticCheckConfig(
                    name=check.name,
                    command=check.command,
                    suffixes=tuple(check.suffixes),
                )
                for check in settings.static_checks
            ],
            static_checks_enabled=allow_repo_command_overrides(resolved_tier),
            analyzers_mode="auto",
            trust_tier=resolved_tier,
            analyzers_settings_enabled=settings.analyzers.enabled,
            suggest_eval_add=False,
            resolved_model=resolved_model,
            budget_tracker=budget_tracker,
        )

        mcp_url, stop_mcp = start_mcp_http_server(tool_context, output_schema=output_schema)
        tool_context.mcp_server_url = mcp_url
        reviewer_mcp_url = mcp_role_url(mcp_url, None)
        skills_home = str(tmpdir / "home")
        await asyncio.to_thread(Path(skills_home).mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(install_bundled_skills, home=skills_home)

        instructions = resolve_instructions(
            payload={
                "event": {"trigger": "unknown", "title": "offline diff-review"},
                "shell": "disabled",
                "push": "disabled",
                "prompt": prompt,
            },
            repo=RepoInfo(owner="local", name=cwd.name),
            modes=modes,
            agent_id=agent.name,
            output_schema=output_schema,
            setup_script_skip_reason=setup_script_skip_reason,
        )
        run_ctx = AgentRunContext(
            payload=payload,
            mcp_server_url=reviewer_mcp_url,
            mcp_auth_token=tool_context.mcp_auth_token,
            tmpdir=str(tmpdir),
            subagent_denied_tools=subagent_denied_tool_names(tool_context, output_schema),
            instructions=instructions,
            tool_state=tool_state,
            api_token="",
            resolved_model=resolved_model,
        )

        logger.info("» offline diff-review via agent={}", agent.name)
        await agent.install()
        from mergecraft.tracing import get_tracer_from_settings
        from mergecraft.tracing.signals import agent_run_span

        with agent_run_span(
            get_tracer_from_settings(settings),
            agent_id=str(agent.name),
            role="reviewer",
            executed_model=resolved_model,
        ):
            result = await agent.run(run_ctx)
        try:
            record_agent_usage(budget_tracker, result.usage)
        except BudgetExhausted as exc:
            return OfflineReviewResult(
                success=False,
                output=result.output,
                structured_output=tool_state.output,
                error=str(exc),
                diff_path=str(materialization.path),
                outcome=budget_exhaustion_outcome(exc),
            )
        structured_output = tool_state.output
        markdown_output = result.output
        packet_path = await asyncio.to_thread(
            _emit_offline_packet,
            tool_context,
            cwd=cwd,
            materialization=materialization,
            run_succeeded=result.success,
            structured_output=structured_output,
            output_path=evidence_packet_path,
        )
        if not result.success:
            return OfflineReviewResult(
                success=False,
                output=markdown_output,
                structured_output=structured_output,
                error=result.error or "agent failed",
                diff_path=str(materialization.path),
                evidence_packet_path=packet_path,
                outcome=RunOutcome.failed,
            )
        return OfflineReviewResult(
            success=True,
            output=markdown_output,
            structured_output=structured_output,
            diff_path=str(materialization.path),
            evidence_packet_path=packet_path,
            outcome=RunOutcome.passed,
        )
    except Exception as exc:
        logger.exception("offline diff-review failed")
        return _offline_failure(
            error=str(exc),
            outcome=_offline_error_outcome(exc),
            diff_path=str(materialization.path),
        )
    finally:
        if stop_mcp is not None:
            stop_mcp()
        if github is not None:
            await github.aclose()
        if not os.environ.get("MERGECRAFT_KEEP_TMP"):
            logger.debug("offline review artifacts retained at {}", tmpdir)
