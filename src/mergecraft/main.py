"""Main orchestration — local-config BYOK runtime (no mergecraft.com)."""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.action.inputs import apply_tracing_overrides
from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentResult, AgentRunContext
from mergecraft.analyzers.redact import install_loguru_redaction_filter
from mergecraft.analyzers.sarif_upload import resolve_sarif_upload_enabled
from mergecraft.analyzers.trust import (
    allow_repo_command_overrides,
    derive_trust_tier,
    resolve_analyzers_mode,
)
from mergecraft.evidence.run_packet import emit_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.dependencies import start_installation
from mergecraft.mcp.server import start_mcp_http_server
from mergecraft.mcp.tool_state import ProgressComment, init_tool_state
from mergecraft.modes import Mode, compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.run_outcome import RUN_OUTCOME_CONCLUSION, RunOutcome, run_succeeded_for_outcome
from mergecraft.utils.agent_resolve import (
    ModelFallbackPolicyError,
    effective_model_chain,
    pick_runnable_slug_from_chain,
    promote_model_evidence,
    resolve_model,
    resolve_runtime_agent,
    run_with_model_chain,
)
from mergecraft.utils.code_scanning import report_sarif_upload
from mergecraft.utils.git_setup import (
    cleanup_temp_directory,
    create_temp_directory,
    setup_git,
    wipe_runner_leak_surface,
)
from mergecraft.utils.github import GitHubClient, resolve_run_context_data
from mergecraft.utils.instructions import resolve_instructions
from mergecraft.utils.learnings import (
    persist_learnings,
    seed_learnings_file,
    seed_xrepo_learnings_file,
)
from mergecraft.utils.log import bind_run_context
from mergecraft.utils.normalize_env import normalize_env
from mergecraft.utils.payload import (
    TIMEOUT_DISABLED,
    read_github_event,
    resolve_output_schema,
    resolve_payload,
    resolve_prompt_input,
    resolve_timeout_ms,
)
from mergecraft.utils.privilege import prepare_workspace_for_agent
from mergecraft.utils.secrets import set_env_allowlist
from mergecraft.utils.skills import install_bundled_skills
from mergecraft.utils.status_checks import report_status_checks
from mergecraft.utils.token import get_job_token, resolve_tokens
from mergecraft.utils.workspace import (
    WorkspacePathError,
    ensure_github_workspace_registered,
    resolve_allowed_working_directory,
)

if TYPE_CHECKING:
    from mergecraft.config.settings import ModeDefinition


@dataclass(slots=True)
class MainResult:
    success: bool
    output: str | None = None
    error: str | None = None
    result: str | None = None
    # On-disk path of this run's merge evidence packet (#47 / #96), or None
    # when the run had no pull request to attest to. Surfaced as the action's
    # ``evidence_packet`` output by ``cli/gha_cmd.py`` (W5.4).
    evidence_packet_path: str | None = None
    # D3/W5.1-W5.2 — the closed six-value taxonomy this run landed in.
    # ``None`` only for call sites that predate W5 (tests constructing a
    # ``MainResult`` directly); every real ``main()`` return path sets it.
    outcome: RunOutcome | None = None


def _first_runnable_in_chain(chain: list[str]) -> str:
    """Harness-patchable one-arg facade over :func:`pick_runnable_slug_from_chain`.

    ``allow_fallback`` lives on the function object (not a module global) so the
    harness can still replace this symbol with ``lambda chain: …`` while
    ``main`` stamps the policy before calling.
    """
    allow = bool(getattr(_first_runnable_in_chain, "allow_fallback", True))
    return pick_runnable_slug_from_chain(chain, allow_fallback=allow)


_first_runnable_in_chain.allow_fallback = True  # type: ignore[attr-defined]


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


class _AgentTimeoutError(RuntimeError):
    """Marks the ``asyncio.wait_for`` timeout path (D3/W5.2).

    A plain ``RuntimeError`` would be indistinguishable from any other agent
    crash once it reaches the outer catch-all; this subclass lets
    ``_classify_error_outcome`` tag it ``RunOutcome.timed_out`` instead of
    the generic ``infra_error`` default.
    """


class _ConfigurationError(RuntimeError):
    """Marks fail-closed configuration errors (D4/W6.3).

    Raised for unparseable Action inputs (e.g. ``timeout``) so the outer
    handler can tag ``RunOutcome.configuration_error`` without confusing
    them with infra crashes.
    """


def _classify_error_outcome(error: BaseException) -> RunOutcome:
    """Split the outer catch-all into timeout / config / infra buckets (D3, W5.2).

    Defaults to ``infra_error`` — that is the "infra never looks like
    success" invariant the taxonomy replaces the old plain boolean with.
    Only exceptions that already carry an unambiguous, distinct cause are
    reclassified; an unclassified agent crash stays ``infra_error``.
    """
    from pydantic import ValidationError

    if isinstance(error, _AgentTimeoutError):
        return RunOutcome.timed_out
    if isinstance(
        error,
        (_ConfigurationError, ModelFallbackPolicyError, WorkspacePathError, ValidationError),
    ):
        return RunOutcome.configuration_error
    return RunOutcome.infra_error


async def _prep_failure_reason(tool_context: ToolContext) -> str | None:
    """Return a reason string when review-relevant dependency prep failed (W6.1).

    Awaits an in-progress install before inspecting status. Trusted-tier
    ``setup_script`` failures are intentionally *not* included here — they
    stay warn-only by policy (see ``docs/config-failure-policy.md``).
    """
    state = tool_context.tool_state.dependency_installation
    if state is None:
        return None
    if state.status == "in_progress" and state.promise is not None:
        try:
            await state.promise
        except Exception as exc:
            return f"dependency installation failed: {exc}"
    if state.status != "failed":
        return None
    reasons: list[str] = []
    for result in state.results or []:
        if not result.dependencies_installed and result.issues:
            reasons.extend(str(item) for item in result.issues)
    if reasons:
        return "; ".join(reasons)
    return "dependency installation failed"


async def main() -> MainResult:
    """Run the mergecraft action flow using local ``.mergecraft/config.yaml``."""
    install_loguru_redaction_filter()
    normalize_env()
    ensure_github_workspace_registered()
    workspace = os.environ.get("GITHUB_WORKSPACE", "").strip()
    if workspace:
        # Guard the workspace prep at its call site so a missing/UID-0 agent
        # user surfaces as a structured ``RunOutcome.configuration_error``
        # rather than escaping as an uncaught traceback. The outer ``try/except``
        # below is reached only after this block returns, so we route through
        # the same classification the outer handler would have used.
        try:
            prepare_workspace_for_agent(workspace)
        except _ConfigurationError as exc:
            return MainResult(
                success=False,
                error=str(exc),
                outcome=_classify_error_outcome(exc),
            )
    stop_mcp = None
    github: GitHubClient | None = None
    token_ref = None
    tool_context: ToolContext | None = None
    tmpdir: str | None = None

    try:
        resolved_prompt = resolve_prompt_input()
        job_token = get_job_token()
        github = GitHubClient(job_token)
        run_context = await resolve_run_context_data(github)
        settings = apply_tracing_overrides(run_context.repo_settings)

        github_event = read_github_event()
        trust_tier = derive_trust_tier(event=github_event)

        pr_number: int | str | None = None
        if isinstance(github_event, dict):
            pr = github_event.get("pull_request")
            if isinstance(pr, dict) and pr.get("number") is not None:
                pr_number = pr["number"]
            else:
                issue = github_event.get("issue")
                if (
                    isinstance(issue, dict)
                    and isinstance(issue.get("pull_request"), dict)
                    and issue.get("number") is not None
                ):
                    pr_number = issue["number"]
        bind_run_context(
            run_id=os.environ.get("GITHUB_RUN_ID"),
            repo=f"{run_context.repo.owner}/{run_context.repo.name}",
            pr=pr_number,
            phase="setup",
        )

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
        tool_state.trust_tier = trust_tier
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
        if cwd:
            resolved_cwd = resolve_allowed_working_directory(cwd, default=os.getcwd())
            if os.getcwd() != resolved_cwd:
                os.chdir(resolved_cwd)

        payload_model = payload.get("model")
        # #37 / W4 / D8 — ``model_pin`` opts into the legacy "use exactly this
        # model" semantics: when True, ``model:`` collapses the chain to a
        # single entry. Default is chain-preserving — the supplied ``model:``
        # becomes the head of the effective chain and the configured ``models:``
        # tail follows. ``modelExplicit`` is retained as a back-compat alias
        # for the legacy pin signal so any consumer that branched on it still
        # behaves the same.
        model_pin = bool(
            payload.get("modelPin") or payload.get("modelExplicit")  # legacy alias
        )
        model_head = payload.get("modelHead") or (
            payload_model if isinstance(payload_model, str) else None
        )
        chain_for_decision = effective_model_chain(
            settings=settings, head=model_head, pin=model_pin
        )
        # ``use_model_chain`` is true whenever an effective chain has more
        # than one entry OR the operator asked for the chain explicitly. The
        # legacy ``not model_explicit`` short-circuit is gone — a supplied
        # ``model:`` no longer disables the chain.
        use_model_chain = len(chain_for_decision) > 1 or (
            bool(chain_for_decision) and model_head is not None and not model_pin
        )
        selected_slug: str | None

        if use_model_chain:
            _first_runnable_in_chain.allow_fallback = settings.allow_fallback  # type: ignore[attr-defined]
            selected_slug = _first_runnable_in_chain(chain_for_decision)
            if not selected_slug:
                msg = (
                    "no runnable model slug in chain — configure credentials for at least one entry"
                )
                raise RuntimeError(msg)
            resolved_model = resolve_model(slug=selected_slug, respect_env_override=False)
        else:
            # Single-entry chain (or pin opt-in). The chain is collapsed to
            # exactly ``[model_head]`` when pinned; otherwise it is just the
            # first configured entry. Honour ``respect_env_override=False``
            # when the operator named a model explicitly — the action input
            # already wins.
            only_slug = (
                model_head if model_pin else (chain_for_decision[0] if chain_for_decision else None)
            )
            resolved_model = resolve_model(slug=only_slug, respect_env_override=False)
            selected_slug = only_slug
        agent = resolve_runtime_agent(model=resolved_model)
        agent_id = agent.name
        tool_state.model = payload.get("proxyModel") or resolved_model or payload.get("model")
        # W10.2 — record the chain head as the requested model so the packet
        # can prove requested vs executed even when selection skipped ahead.
        if chain_for_decision:
            tool_state.requested_model = chain_for_decision[0]
        elif selected_slug:
            tool_state.requested_model = selected_slug
        elif isinstance(payload_model, str) and payload_model.strip():
            tool_state.requested_model = payload_model.strip()
        else:
            tool_state.requested_model = tool_state.model
        tool_state.fallback_index = 0
        tool_state.fallback_occurred = False

        await asyncio.to_thread(
            setup_git,
            git_token=token_ref.git_token,
            owner=run_context.repo.owner,
            name=run_context.repo.name,
            tool_state=tool_state,
            shell=payload.get("shell") or "restricted",
            tmpdir=tmpdir,
            octokit=github,
        )

        setup_script_skip_reason = ""
        if settings.setup_script:
            if trust_tier == "trusted":
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
            else:
                event_name = os.environ.get("GITHUB_EVENT_NAME", "unknown")
                setup_script_skip_reason = (
                    f"skipped setup_script on untrusted tier ({event_name} event)"
                )
                tool_state.setup_script_skip_reason = setup_script_skip_reason
                logger.warning("» {}", setup_script_skip_reason)

        modes = [
            *compute_modes(agent_id, settings.signed_commits),
            *_custom_modes(settings.modes),
        ]
        output_schema = resolve_output_schema()

        ctx_payload = _payload_to_ctx(payload)
        analyzers_mode = resolve_analyzers_mode(os.environ.get("INPUT_ANALYZERS"))
        sarif_upload_enabled = resolve_sarif_upload_enabled(
            action_input=os.environ.get("INPUT_SARIF_UPLOAD"),
            repo_setting=settings.analyzers.sarif_upload,
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

        # W6.3 — unparseable timeout fails closed *before* the agent starts.
        # ``--notimeout`` / ``none`` remains the explicit escape; unset keeps
        # the historical 1h default.
        timeout_ms: int | None
        if timeout_raw == TIMEOUT_DISABLED:
            timeout_ms = None
        elif timeout_raw:
            usable = resolve_timeout_ms(timeout_raw)
            if usable is None:
                msg = (
                    f'invalid timeout "{timeout_raw}" '
                    "(use a duration like 10m/1h or --notimeout to disable)"
                )
                raise _ConfigurationError(msg)
            timeout_ms = usable
        else:
            timeout_ms = 3_600_000

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
                    head=model_head,
                    pin=model_pin,
                )
                return winning_slug, chain_result
            return selected_slug, await agent.run(run_ctx)

        agent_task = asyncio.create_task(_execute_agent())

        if timeout_ms is None:
            winning_slug, result = await agent_task
        else:
            try:
                winning_slug, result = await asyncio.wait_for(
                    agent_task, timeout=timeout_ms / 1000.0
                )
            except TimeoutError:
                agent_task.cancel()
                from mergecraft.utils.process_group import kill_all_active_process_groups

                kill_all_active_process_groups()
                msg = f"agent run timed out after {timeout_raw or '1h'}"
                raise _AgentTimeoutError(msg) from None

        if winning_slug:
            resolved_model = resolve_model(slug=winning_slug, respect_env_override=False)
            tool_context.resolved_model = resolved_model
            # W10.2/W10.3 — single promotion path; chain stamps metadata in
            # ``_attach_model_evidence``, single-slug defaults to index 0.
            meta = result.metadata or {}
            requested_meta = meta.get("requested_model")
            requested = (
                requested_meta.strip()
                if isinstance(requested_meta, str) and requested_meta.strip()
                else (chain_for_decision[0] if chain_for_decision else tool_state.requested_model)
            )
            fallback_raw = meta.get("fallback_index")
            fallback_index = fallback_raw if isinstance(fallback_raw, int) else 0
            executed = payload.get("proxyModel") or resolved_model or winning_slug
            promote_model_evidence(
                tool_state,
                requested_model=requested,
                executed_model=executed if isinstance(executed, str) else winning_slug,
                fallback_index=fallback_index,
            )

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

        # D3/W5.2 + W6.1 — a completed run is `passed` / `failed`, or
        # `inconclusive` when review-relevant dependency prep failed underneath
        # a otherwise-successful agent. Agent failure wins over prep failure.
        prep_reason = await _prep_failure_reason(tool_context)
        if not result.success:
            outcome = RunOutcome.failed
            failure_reason = result.error
        elif prep_reason:
            outcome = RunOutcome.inconclusive
            failure_reason = prep_reason
            logger.warning("» prep failure mapped run to inconclusive: {}", prep_reason)
        else:
            outcome = RunOutcome.passed
            failure_reason = None

        packet_path: str | None = None
        if tool_context:
            from mergecraft.tracing.tracer import get_tracer_from_settings

            tracer = get_tracer_from_settings(settings)
            with tracer.start_span(
                "mergecraft.publish",
                attrs_source=lambda: {"run_succeeded": outcome is RunOutcome.passed},
            ) as _publish_span:
                await persist_learnings(tool_context)
                await report_status_checks(
                    tool_context,
                    run_succeeded=run_succeeded_for_outcome(outcome),
                    failure_reason=failure_reason,
                    conclusion=RUN_OUTCOME_CONCLUSION[outcome],
                )
                # #39 — opt-in, off by default, and never a gate: with
                # `sarif_upload` unset this returns before making any request.
                await report_sarif_upload(tool_context)
                # Emit the merge evidence packet last, so it records the run's
                # final state. A blocked or failed run is exactly when the
                # evidence matters most, so this runs on both branches below.
                written = await asyncio.to_thread(
                    emit_run_packet, tool_context, run_succeeded=outcome is RunOutcome.passed
                )
                packet_path = str(written) if written else None

        if outcome is not RunOutcome.passed:
            return MainResult(
                success=False,
                error=failure_reason or result.error or "agent execution failed",
                evidence_packet_path=packet_path,
                outcome=outcome,
            )

        output = tool_state.output or result.output
        return MainResult(
            success=True,
            output=output,
            result=output,
            evidence_packet_path=packet_path,
            outcome=outcome,
        )

    except Exception as error:
        error_message = str(error) if error else "unknown error occurred"
        logger.error("{}", error_message)
        error_outcome = _classify_error_outcome(error)
        if tool_context:
            try:
                await persist_learnings(tool_context)
                await report_status_checks(
                    tool_context,
                    run_succeeded=run_succeeded_for_outcome(error_outcome),
                    failure_reason=error_message,
                    conclusion=RUN_OUTCOME_CONCLUSION[error_outcome],
                )
            except Exception:
                pass
        return MainResult(success=False, error=error_message, outcome=error_outcome)

    finally:
        if stop_mcp is not None:
            with contextlib.suppress(Exception):
                stop_mcp()
        with contextlib.suppress(Exception):
            cleanup_temp_directory()
        if token_ref is not None:
            with contextlib.suppress(Exception):
                await token_ref.aclose()
        if github is not None:
            with contextlib.suppress(Exception):
                await github.aclose()


__all__ = ["MainResult", "RunOutcome", "main"]
