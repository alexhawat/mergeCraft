"""Agent dispatch for offline CLI review (extracted from ``offline_review``)."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.agents import resolve_agent
from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.shared import AgentResult, AgentRunContext
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
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.mcp.verdict import establish_offline_review_scope
from mergecraft.modes import compute_modes
from mergecraft.review.offline_result import (
    OfflineReviewResult,
    _emit_offline_packet,
    _offline_error_outcome,
    _offline_failure,
)
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.agent_resolve import (
    ModelFallbackPolicyError,
    credential_status_for_slug,
    effective_model_chain,
    format_credential_gap_message,
    promote_model_evidence,
    resolve_harness,
    resolve_model,
    resolve_runtime_agent,
    run_with_model_chain,
)
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

    from mergecraft.mcp.tool_state import AnalyzerRunState
    from mergecraft.types import ShellPermission
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
    shell: ShellPermission = "disabled",
    run_bounds: RunBounds | None = None,
    on_finding: Callable[[dict[str, Any]], None] | None = None,
    analyzer_run: AnalyzerRunState | None = None,
) -> OfflineReviewResult:
    """Run the Review agent against a materialized local diff.

    ``shell`` is the operator-resolved shell permission (``--shell`` on
    ``mergecraft review``). It reaches both the resolved payload the MCP tool
    surface reads and the agent instructions, so the tool surface and the
    analyzer pipeline agree on one value. Default ``disabled``.
    """
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
        # Offline runs have no PR to check out; the materialized diff is the
        # review scope, and establishing it here is what lets the terminal
        # verdict tools run at all (issue #470).
        establish_offline_review_scope(tool_state, diff_path=str(materialization.path))
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
        chain = effective_model_chain(settings, head=model, pin=settings.model_pin)
        if not chain:
            raise ValueError("no model chain configured — set models: in .mergecraft/config.yaml")
        resolved_model = resolve_model(
            slug=chain[0] if chain else model, respect_env_override=False
        )
        # Context construction must not reject an unavailable primary before
        # the shared fallback loop can inspect it. Runtime resolution happens
        # only after each candidate passes the credential check.
        agent = resolve_agent(resolve_harness(settings, chain[0]))
        modes = compute_modes(agent.name, signed_commits=False)
        bounds = run_bounds or resolve_run_bounds(settings=settings)
        budget_tracker = BudgetTracker(bounds)

        payload = ResolvedPayload(
            event=PayloadEvent(trigger="unknown", title="offline diff-review"),
            shell=shell,
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
        if analyzer_run is not None:
            from mergecraft.mcp.analyzers import _store_run_state

            _store_run_state(tool_context, analyzer_run)

        from mergecraft.config.settings_snapshot import capture_run_scope_snapshot
        from mergecraft.review.roster_auth import (
            RosterAuthError,
            RosterSecretEmptyError,
            validate_roster_at_run_start,
        )
        from mergecraft.workflow.auth_manifest import DEFAULT_WORKFLOW_RELATIVE_PATH

        workflow_path = cwd / DEFAULT_WORKFLOW_RELATIVE_PATH
        if workflow_path.is_file():
            snapshot = capture_run_scope_snapshot(
                tool_context,
                root=cwd,
                settings=settings,
                load_learnings_files=False,
            )
            try:
                validate_roster_at_run_start(snapshot=snapshot, workflow_path=workflow_path)
            except (RosterAuthError, RosterSecretEmptyError) as exc:
                return _offline_failure(
                    error=str(exc),
                    outcome=RunOutcome.configuration_error,
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
                "shell": shell,
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

        async def run_once(slug: str) -> AgentResult:
            """Dispatch one candidate with fresh verdict/output state and shared budget."""
            tool_state.output = None
            tool_state.final_summary_written = False
            attempt_model = resolve_model(slug=slug, respect_env_override=False)
            status = credential_status_for_slug(slug, settings=settings, cwd=cwd, wired=True)
            if not status.available:
                return AgentResult(
                    success=False,
                    error=format_credential_gap_message(slug=slug, status=status, wired=True),
                    metadata={"retryable": True},
                )
            attempt_agent = resolve_runtime_agent(model=attempt_model, settings=settings)
            attempt_modes = compute_modes(attempt_agent.name, signed_commits=False)
            tool_context.agent_id = attempt_agent.name
            tool_context.modes = attempt_modes
            tool_context.resolved_model = attempt_model
            tool_state.modes = attempt_modes
            attempt_instructions = resolve_instructions(
                payload={
                    "event": {"trigger": "unknown", "title": "offline diff-review"},
                    "shell": shell,
                    "push": "disabled",
                    "prompt": prompt,
                },
                repo=RepoInfo(owner="local", name=cwd.name),
                modes=attempt_modes,
                agent_id=attempt_agent.name,
                output_schema=output_schema,
                setup_script_skip_reason=setup_script_skip_reason,
            )
            attempt_ctx = replace(
                run_ctx,
                resolved_model=attempt_model,
                instructions=attempt_instructions,
                subagent_denied_tools=subagent_denied_tool_names(tool_context, output_schema),
            )
            if budget_tracker.last_exhausted is not None:
                raise budget_tracker.last_exhausted
            logger.info("» offline diff-review via agent={} model={}", attempt_agent.name, slug)
            try:
                await attempt_agent.install()
            except (FileNotFoundError, OSError) as exc:
                return AgentResult(success=False, error=str(exc), metadata={"retryable": True})
            from mergecraft.tracing import get_tracer_from_settings
            from mergecraft.tracing.signals import agent_run_span

            with agent_run_span(
                get_tracer_from_settings(settings),
                agent_id=str(attempt_agent.name),
                role="reviewer",
                executed_model=attempt_model,
            ):
                result = await attempt_agent.run(attempt_ctx)
            record_agent_usage(budget_tracker, result.usage, phase="reviewer_dispatch")
            return result

        winning_slug, result = await run_with_model_chain(
            settings=settings,
            run_once=run_once,
            head=model,
            pin=settings.model_pin,
            tool_state=tool_state,
        )
        promote_model_evidence(
            tool_state,
            requested_model=chain[0] if chain else model,
            executed_model=resolve_model(slug=winning_slug, respect_env_override=False)
            if winning_slug
            else None,
            fallback_index=int(result.metadata.get("fallback_index", 0)),
        )
        from mergecraft.main_outcome import _classify_outcome

        outcome, failure_reason = _classify_outcome(
            result=result,
            setup_reason="",
            setup_policy="warn",
            prep_reason=None,
            mode="Review",
            verdict_protocol="enforce",
        )
        structured_output = tool_state.output
        markdown_output = result.output
        packet_path = await asyncio.to_thread(
            _emit_offline_packet,
            tool_context,
            cwd=cwd,
            materialization=materialization,
            run_succeeded=outcome == RunOutcome.passed,
            structured_output=structured_output,
            output_path=evidence_packet_path,
        )
        if outcome != RunOutcome.passed:
            return OfflineReviewResult(
                success=False,
                output=markdown_output,
                structured_output=structured_output,
                error=failure_reason or result.error or "agent failed",
                diff_path=str(materialization.path),
                evidence_packet_path=packet_path,
                outcome=outcome,
            )
        return OfflineReviewResult(
            success=True,
            output=markdown_output,
            structured_output=structured_output,
            diff_path=str(materialization.path),
            evidence_packet_path=packet_path,
            outcome=RunOutcome.passed,
        )
    except ModelFallbackPolicyError as exc:
        return _offline_failure(
            error=str(exc),
            outcome=RunOutcome.configuration_error,
            diff_path=str(materialization.path),
        )
    except BudgetExhausted as exc:
        return _offline_failure(
            error=str(exc),
            outcome=budget_exhaustion_outcome(exc),
            diff_path=str(materialization.path),
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
