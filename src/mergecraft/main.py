"""Main orchestration — local-config BYOK runtime (no mergecraft.com)."""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentResult, AgentRunContext
from mergecraft.analyzers.redact import install_loguru_redaction_filter
from mergecraft.analyzers.trust import (
    allow_repo_command_overrides,
    derive_trust_tier,
    resolve_analyzers_mode,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.dependencies import start_installation
from mergecraft.mcp.server import start_mcp_http_server
from mergecraft.mcp.tool_state import ProgressComment, init_tool_state
from mergecraft.modes import Mode, compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.utils.agent_resolve import (
    effective_model_chain,
    resolve_model,
    resolve_runtime_agent,
    run_with_model_chain,
    select_runnable_model_slug,
)
from mergecraft.utils.git_setup import create_temp_directory, setup_git, wipe_runner_leak_surface
from mergecraft.utils.github import GitHubClient, resolve_run_context_data
from mergecraft.utils.instructions import resolve_instructions
from mergecraft.utils.learnings import (
    persist_learnings,
    seed_learnings_file,
    seed_xrepo_learnings_file,
)
from mergecraft.utils.normalize_env import normalize_env
from mergecraft.utils.payload import (
    TIMEOUT_DISABLED,
    read_github_event,
    resolve_output_schema,
    resolve_payload,
    resolve_prompt_input,
    resolve_timeout_ms,
)
from mergecraft.utils.secrets import set_env_allowlist
from mergecraft.utils.skills import install_bundled_skills
from mergecraft.utils.status_checks import report_status_checks
from mergecraft.utils.token import get_job_token, resolve_tokens

if TYPE_CHECKING:
    from mergecraft.config.settings import ModeDefinition


@dataclass(slots=True)
class MainResult:
    success: bool
    output: str | None = None
    error: str | None = None
    result: str | None = None


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


def _custom_modes(defs: list[ModeDefinition]) -> list[Mode]:
    return [Mode(name=d.name, description=d.description, prompt=d.prompt or None) for d in defs]


async def main() -> MainResult:
    install_loguru_redaction_filter()
    """Run the mergecraft action flow using local ``.mergecraft/config.yaml``."""
    normalize_env()
    stop_mcp = None
    github: GitHubClient | None = None
    token_ref = None
    tool_context: ToolContext | None = None

    try:
        resolved_prompt = resolve_prompt_input()
        job_token = get_job_token()
        github = GitHubClient(job_token)
        run_context = await resolve_run_context_data(github)
        settings = run_context.repo_settings

        progress = None
        if not isinstance(resolved_prompt, str) and resolved_prompt.progress_comment:
            progress = ProgressComment(
                id=resolved_prompt.progress_comment.id,
                type=resolved_prompt.progress_comment.type,
            )

        tool_state = init_tool_state(
            owner=run_context.repo.owner,
            name=run_context.repo.name,
            dir=os.getcwd(),
            progress_comment=progress,
        )
        tmpdir = create_temp_directory()

        if settings.env_allowlist:
            set_env_allowlist(settings.env_allowlist)

        payload = resolve_payload(resolved_prompt, settings)
        tool_state.model = payload.get("model")
        tool_state.oss = run_context.oss

        wipe_runner_leak_surface()

        if payload.get("shell") != "enabled":
            os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_URL", None)
            os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_TOKEN", None)

        token_ref = await resolve_tokens(
            push=payload.get("push") or "restricted", xrepo=payload.get("xrepo")
        )
        # Prefer MCP token for API calls
        await github.aclose()
        github = GitHubClient(token_ref.mcp_token)

        cwd = payload.get("cwd")
        if cwd and os.getcwd() != cwd:
            os.chdir(cwd)

        payload_model = payload.get("model")
        model_explicit = bool(payload.get("modelExplicit"))
        use_model_chain = bool(effective_model_chain(settings)) and not model_explicit
        selected_slug: str | None

        if use_model_chain:
            selected_slug = select_runnable_model_slug(settings=settings)
            resolved_model = resolve_model(slug=selected_slug, respect_env_override=False)
        else:
            resolved_model = resolve_model(
                slug=payload_model if isinstance(payload_model, str) else None,
                respect_env_override=not model_explicit,
            )
            selected_slug = payload_model if isinstance(payload_model, str) else None
        agent = resolve_runtime_agent(model=resolved_model)
        agent_id = agent.name
        tool_state.model = payload.get("proxyModel") or resolved_model or payload.get("model")

        await asyncio.to_thread(
            setup_git,
            git_token=token_ref.git_token,
            owner=run_context.repo.owner,
            name=run_context.repo.name,
            tool_state=tool_state,
            shell=payload.get("shell") or "restricted",
            tmpdir=tmpdir,
            octokit=github,
            post_checkout_script=settings.post_checkout_script,
        )

        # best-effort setup script
        if settings.setup_script:
            logger.info("» running setup script")
            proc = await asyncio.create_subprocess_shell(
                settings.setup_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _out, err = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(
                    "» setup script failed (exit {}): {}",
                    proc.returncode,
                    (err or b"").decode(errors="replace")[:500],
                )

        modes = [
            *compute_modes(agent_id, settings.signed_commits),
            *_custom_modes(settings.modes),
        ]
        output_schema = resolve_output_schema()

        ctx_payload = _payload_to_ctx(payload)
        analyzers_mode = resolve_analyzers_mode(os.environ.get("INPUT_ANALYZERS"))
        github_event = read_github_event()
        trust_tier = derive_trust_tier(
            event=github_event,
            shell=str(ctx_payload.shell),
        )
        tool_context = ToolContext(
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
            post_checkout_script=settings.post_checkout_script,
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
            analyzers_mode=analyzers_mode,
            trust_tier=trust_tier,
            analyzers_settings_enabled=settings.analyzers.enabled,
            run_id=int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None,
            job_id=os.environ.get("GITHUB_JOB"),
            oss=run_context.oss,
            plan="unknown",
            resolved_model=resolved_model,
            suggest_eval_add=bool(payload.get("suggestEvalAdd")),
        )

        mcp_url, stop_mcp = start_mcp_http_server(tool_context, output_schema=output_schema)
        tool_context.mcp_server_url = mcp_url
        logger.info("» MCP server started at {}", mcp_url)

        subagent_denied = subagent_denied_tool_names(tool_context, output_schema)

        try:
            learnings_path = await seed_learnings_file(tmpdir=tmpdir, current=settings.learnings)
            tool_state.learnings_file_path = learnings_path
            tool_state.learnings_seed = (settings.learnings or "").strip()
            # D10 / W6.5 — wire the opt-in auto-promote flag from
            # ``RepoSettings`` into ``tool_state`` so ``persist_learnings``
            # honors it. Default is fail-closed (staging only); setting
            # ``autopromoteLearnings: true`` restores legacy behaviour for
            # trusted maintainer authors (see ``utils/learnings.py``).
            tool_state.autopromote_learnings = settings.autopromote_learnings
            logger.info(
                "» learnings seeded at {} (existing={})",
                learnings_path,
                "yes" if settings.learnings else "no",
            )
        except Exception as exc:
            logger.warning("» learnings seed failed: {} — continuing without learnings file", exc)

        if payload.get("xrepo"):
            try:
                xrepo_path = await seed_xrepo_learnings_file(
                    tmpdir=tmpdir, current=settings.xrepo_learnings
                )
                tool_state.xrepo_learnings_file_path = xrepo_path
                tool_state.xrepo_learnings_seed = (settings.xrepo_learnings or "").strip()
            except Exception as exc:
                logger.warning("» xrepo learnings seed failed: {}", exc)

        start_installation(tool_context)

        # Install bundled skills into a fake HOME under tmpdir
        skills_home = os.path.join(tmpdir, "home")
        os.makedirs(skills_home, exist_ok=True)
        try:
            install_bundled_skills(home=skills_home)
        except Exception as exc:
            logger.warning("» bundled skills install failed: {}", exc)

        instructions = resolve_instructions(
            payload=payload,
            repo=run_context.repo,
            modes=modes,
            agent_id=agent_id,
            output_schema=output_schema,
            signed_commits=settings.signed_commits,
            learnings_file_path=tool_state.learnings_file_path,
            learnings_headings=settings.learnings_headings,
            setup_hook_failure="",
            xrepo_brief=settings.xrepo_brief,
            xrepo_learnings_file_path=tool_state.xrepo_learnings_file_path,
            xrepo_learnings_headings=settings.xrepo_learnings_headings,
        )
        logger.info("Using agent={} model={}", agent_id, resolved_model or "(auto)")

        run_ctx = AgentRunContext(
            payload=payload,
            mcp_server_url=mcp_url,
            tmpdir=tmpdir,
            subagent_denied_tools=subagent_denied,
            instructions=instructions,
            tool_state=tool_state,
            api_token=run_context.api_token,
            resolved_model=resolved_model,
            stop_script=settings.stop_script,
        )

        timeout_raw = payload.get("timeout")

        async def _run_agent_once(slug: str) -> AgentResult:
            attempt_model = resolve_model(slug=slug, respect_env_override=False)
            attempt_agent = resolve_runtime_agent(model=attempt_model)
            attempt_agent_id = attempt_agent.name

            if attempt_agent_id == agent_id:
                attempt_ctx = replace(run_ctx, resolved_model=attempt_model)
            else:
                attempt_modes = [
                    *compute_modes(attempt_agent_id, settings.signed_commits),
                    *_custom_modes(settings.modes),
                ]
                attempt_instructions = resolve_instructions(
                    payload=payload,
                    repo=run_context.repo,
                    modes=attempt_modes,
                    agent_id=attempt_agent_id,
                    output_schema=output_schema,
                    signed_commits=settings.signed_commits,
                    learnings_file_path=tool_state.learnings_file_path,
                    learnings_headings=settings.learnings_headings,
                    setup_hook_failure="",
                    xrepo_brief=settings.xrepo_brief,
                    xrepo_learnings_file_path=tool_state.xrepo_learnings_file_path,
                    xrepo_learnings_headings=settings.xrepo_learnings_headings,
                )
                attempt_denied = subagent_denied_tool_names(
                    replace(tool_context, agent_id=attempt_agent_id),
                    output_schema,
                )
                attempt_ctx = replace(
                    run_ctx,
                    resolved_model=attempt_model,
                    instructions=attempt_instructions,
                    subagent_denied_tools=attempt_denied,
                )
                tool_context.agent_id = attempt_agent_id
                tool_context.modes = attempt_modes
                tool_context.resolved_model = attempt_model
                logger.info(
                    "» model chain advanced to agent={} model={}",
                    attempt_agent_id,
                    attempt_model or "(auto)",
                )
            return await attempt_agent.run(attempt_ctx)

        async def _execute_agent() -> tuple[str | None, AgentResult]:
            if use_model_chain:
                winning_slug, chain_result = await run_with_model_chain(
                    settings=settings,
                    run_once=_run_agent_once,
                )
                return winning_slug, chain_result
            return selected_slug, await agent.run(run_ctx)

        agent_task = asyncio.create_task(_execute_agent())

        if timeout_raw == TIMEOUT_DISABLED:
            winning_slug, result = await agent_task
        else:
            usable = resolve_timeout_ms(timeout_raw)
            if timeout_raw and usable is None:
                logger.warning(
                    'invalid timeout "{}" (use --notimeout to disable), using 1h', timeout_raw
                )
            timeout_ms = usable if usable is not None else 3_600_000
            try:
                winning_slug, result = await asyncio.wait_for(
                    agent_task, timeout=timeout_ms / 1000.0
                )
            except TimeoutError:
                agent_task.cancel()
                msg = f"agent run timed out after {timeout_raw or '1h'}"
                raise RuntimeError(msg) from None

        if winning_slug:
            resolved_model = resolve_model(slug=winning_slug, respect_env_override=False)
            tool_state.model = payload.get("proxyModel") or resolved_model or payload_model
            tool_context.resolved_model = resolved_model

        if result.usage:
            tool_state.usage_entries.append(result.usage)

        if output_schema and not tool_state.output:
            msg = (
                "output_schema was provided but agent did not call set_output — "
                "structured output is required"
            )
            raise RuntimeError(msg)

        try:
            result = await finalize_agent_result(run_ctx, result)
        except Exception as exc:
            logger.debug("post-run finalize skipped: {}", exc)

        if tool_context:
            await persist_learnings(tool_context)
            await report_status_checks(
                tool_context,
                run_succeeded=result.success,
                failure_reason=result.error if not result.success else None,
            )

        if not result.success:
            return MainResult(success=False, error=result.error or "agent execution failed")

        output = tool_state.output or result.output
        return MainResult(success=True, output=output, result=output)

    except Exception as error:
        error_message = str(error) if error else "unknown error occurred"
        logger.error("{}", error_message)
        if tool_context:
            try:
                await persist_learnings(tool_context)
                await report_status_checks(
                    tool_context,
                    run_succeeded=False,
                    failure_reason=error_message,
                )
            except Exception:
                pass
        return MainResult(success=False, error=error_message)

    finally:
        if stop_mcp is not None:
            with contextlib.suppress(Exception):
                stop_mcp()
        if token_ref is not None:
            with contextlib.suppress(Exception):
                await token_ref.aclose()
        if github is not None:
            with contextlib.suppress(Exception):
                await github.aclose()


__all__ = ["MainResult", "main"]
