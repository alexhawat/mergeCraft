"""Main orchestration — local-config BYOK runtime (no mergecraft.com).

The orchestrator stays thin: every non-trivial helper lives in a dedicated
``main_*.py`` module (``main_models``, ``main_setup``, ``main_agent``,
``main_outcome``) so this file holds only the top-level flow plus the
small handful of main-scoped helpers that have no other natural home.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.action.inputs import apply_setup_overrides, apply_tracing_overrides
from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentRunContext
from mergecraft.analyzers.redact import install_loguru_redaction_filter
from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.evidence.run_packet import emit_run_packet

# Re-exports keep every legacy import path working; the bodies live in
# dedicated ``main_*.py`` modules so the orchestrator stays under the
# 1k-line ceiling.
from mergecraft.main_agent import (
    _AgentRunArgs,
    _AgentTimeoutError,
    _build_tool_context,
    _run_agent_with_timeout,
)
from mergecraft.main_models import (
    _ConfigurationError,
    _resolve_agent_model,
    _resolve_run_budget,
)
from mergecraft.main_outcome import _classify_outcome, _publish_span_attrs
from mergecraft.main_setup import _compute_agent_deadline, _run_setup_script
from mergecraft.mcp.dependencies import start_installation
from mergecraft.mcp.server import start_mcp_http_server
from mergecraft.mcp.tool_state import ProgressComment, ToolState, init_tool_state
from mergecraft.modes import _custom_modes, compute_modes
from mergecraft.run_outcome import RUN_OUTCOME_CONCLUSION, RunOutcome, run_succeeded_for_outcome
from mergecraft.utils.agent_resolve import (
    ModelFallbackPolicyError,
    effective_model_chain,
    promote_model_evidence,
    resolve_model,
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
    read_github_event,
    resolve_output_schema,
    resolve_payload,
    resolve_prompt_input,
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
    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.context import ToolContext


__all__ = ["MainResult", "RunOutcome", "_AgentTimeoutError", "_ConfigurationError", "main"]

# Backwards-compat re-export — the S1/S3/S5 helper split (commit 4e8f420+)
# moved ``_first_runnable_in_chain`` into ``main_models``. ``main.py`` does
# not call it directly, but the test harness (``tests/support/run_main_harness.py``)
# monkeypatches ``mergecraft.main._first_runnable_in_chain`` to drive the
# harness single-slug fast-path, so we re-bind the name here as a stable
# patch surface. The helper module owns the actual call sites.
from mergecraft.main_models import _first_runnable_in_chain  # noqa: F401


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

    Awaits an in-progress install before inspecting status.
    Trusted-tier ``setup_script`` failures live in :func:`main`'s outcome
    resolver and never reach this helper — that path is policy-driven
    (configurable via ``setup_failure_policy``), while dependency-prep
    failure is a fixed-shape ``inconclusive`` mapping.
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


def _extract_pr_number(github_event: Any) -> int | str | None:
    """Pull the PR number off the GitHub event payload (PR or issue-shaped)."""
    if not isinstance(github_event, dict):
        return None
    pr = github_event.get("pull_request")
    if isinstance(pr, dict) and pr.get("number") is not None:
        number = pr["number"]
        return number if isinstance(number, (int, str)) else None
    issue = github_event.get("issue")
    if (
        isinstance(issue, dict)
        and isinstance(issue.get("pull_request"), dict)
        and issue.get("number") is not None
    ):
        number = issue["number"]
        return number if isinstance(number, (int, str)) else None
    return None


def _build_progress_comment(resolved_prompt: Any) -> ProgressComment | None:
    """Promote a resolved prompt's progress comment to a ``ProgressComment``."""
    if isinstance(resolved_prompt, str) or resolved_prompt.progress_comment is None:
        return None
    return ProgressComment(
        id=resolved_prompt.progress_comment.id,
        type=resolved_prompt.progress_comment.type,
    )


def _resolve_model_chain_inputs(
    payload: dict[str, Any], settings: RepoSettings
) -> tuple[bool, str | None, list[str], Any]:
    """Resolve ``model_pin`` / ``model_head`` / ``chain_for_decision`` (W4/D8)."""
    payload_model = payload.get("model")
    # ``model_pin`` opts into the legacy "use exactly this model" semantics
    # when True: ``model:`` collapses the chain to a single entry. Default
    # is chain-preserving — the supplied ``model:`` becomes the head of the
    # effective chain. ``modelExplicit`` is a back-compat alias for the
    # legacy pin signal.
    model_pin = bool(payload.get("modelPin") or payload.get("modelExplicit"))
    model_head = payload.get("modelHead") or (
        payload_model if isinstance(payload_model, str) else None
    )
    chain_for_decision = effective_model_chain(settings=settings, head=model_head, pin=model_pin)
    return model_pin, model_head, chain_for_decision, payload_model


def _stamp_requested_model(
    tool_state: ToolState,
    payload_model: Any,
    chain_for_decision: list[str],
    selected_slug: str | None,
    resolved_model: str | None,
    payload: dict[str, Any],
) -> None:
    """Stamp the requested-vs-executed model evidence onto ``tool_state`` (W10.2)."""
    proxy_model: Any = payload.get("proxyModel")
    payload_model_value: Any = payload.get("model")
    chosen = proxy_model or resolved_model or payload_model_value
    tool_state.model = chosen if isinstance(chosen, str) else None
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


async def _seed_learnings(
    tool_state: ToolState, settings: RepoSettings, tmpdir: str, payload: dict[str, object]
) -> None:
    """Seed the run's learnings + xrepo-learnings files (best-effort)."""
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


def _promote_winning_slug(
    winning_slug: str,
    result: Any,
    chain_for_decision: list[str],
    tool_state: ToolState,
    tool_context: ToolContext,
    payload: dict[str, object],
) -> str | None:
    """Stamp the winning model + requested/executed evidence onto ``tool_state``.

    W10.2/W10.3 — single promotion path; chain stamps metadata in
    ``_attach_model_evidence``, single-slug defaults to index 0.
    """
    resolved_model = resolve_model(slug=winning_slug, respect_env_override=False)
    tool_context.resolved_model = resolved_model
    meta = getattr(result, "metadata", None) or {}
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
    return resolved_model


async def _run_publish_span_block(
    tool_context: ToolContext,
    tool_state: ToolState,
    settings: RepoSettings,
    outcome: RunOutcome,
    failure_reason: str | None,
) -> str | None:
    """Run the ``mergecraft.publish`` span block — evidence emission.

    Returns the packet path (or ``None`` if no ``tool_context`` is set up
    yet — the catch-all path). The ``attrs_source`` lambda is required by
    the tracer API (``Callable[[], dict[str, Any]] | None`` in
    ``tracing/tracer.py``); the helper it delegates to
    (``_publish_span_attrs``) is what ``#145`` contract reads.
    """
    from mergecraft.tracing.tracer import get_tracer_from_settings

    if tool_context is None:
        return None
    tracer = get_tracer_from_settings(settings)
    with tracer.start_span(
        "mergecraft.publish",
        attrs_source=lambda: _publish_span_attrs(outcome, tool_state.modes),
    ):
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
        return str(written) if written else None


def _build_main_result(
    outcome: RunOutcome,
    failure_reason: str | None,
    packet_path: str | None,
    result: Any,
    tool_state: ToolState,
) -> MainResult:
    """Build the ``MainResult`` returned to the caller (passed / failed)."""
    if outcome is not RunOutcome.passed:
        return MainResult(
            success=False,
            error=failure_reason or getattr(result, "error", None) or "agent execution failed",
            evidence_packet_path=packet_path,
            outcome=outcome,
        )
    output = tool_state.output or getattr(result, "output", None)
    return MainResult(
        success=True,
        output=output,
        result=output,
        evidence_packet_path=packet_path,
        outcome=outcome,
    )


async def main() -> MainResult:
    """Run the mergecraft action flow using local ``.mergecraft/config.yaml``."""
    install_loguru_redaction_filter()
    normalize_env()
    ensure_github_workspace_registered()
    stop_mcp = None
    github: GitHubClient | None = None
    token_ref = None
    tool_context: ToolContext | None = None
    try:
        workspace = os.environ.get("GITHUB_WORKSPACE", "").strip()
        if workspace:
            # S2 — a missing agent user fails closed as ``_ConfigurationError``.
            # Must be inside the ``try`` so the outer catch classifies it as
            # ``RunOutcome.configuration_error`` instead of crashing unclassified.
            prepare_workspace_for_agent(workspace)

        resolved_prompt = resolve_prompt_input()
        github = GitHubClient(get_job_token())
        run_context = await resolve_run_context_data(github)

        # S1 / D10 — apply the action-input setup overrides (policy + timeout).
        # ``apply_setup_overrides`` resolves ``INPUT_SETUP_FAILURE_POLICY`` and
        # ``INPUT_SETUP_TIMEOUT`` and raises ``ValueError`` on bad input. We
        # translate that into ``_ConfigurationError`` here so the outer catch
        # maps it to ``RunOutcome.configuration_error`` *after* ``tool_context``
        # is set up (so ``report_status_checks`` still fires).
        try:
            settings = apply_setup_overrides(apply_tracing_overrides(run_context.repo_settings))
        except ValueError as exc:
            raise _ConfigurationError(str(exc)) from None

        github_event = read_github_event()
        trust_tier = derive_trust_tier(event=github_event)
        bind_run_context(
            run_id=os.environ.get("GITHUB_RUN_ID"),
            repo=f"{run_context.repo.owner}/{run_context.repo.name}",
            pr=_extract_pr_number(github_event),
            phase="setup",
        )

        progress = _build_progress_comment(resolved_prompt)
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
        timeout_raw = payload.get("timeout")
        timeout_ms, setup_timeout_s = _resolve_run_budget(payload, settings)

        wipe_runner_leak_surface()
        if payload.get("shell") != "enabled":
            os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_URL", None)
            os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_TOKEN", None)

        token_ref = await resolve_tokens(
            push=payload.get("push") or "restricted", xrepo=payload.get("xrepo")
        )
        await github.aclose()
        github = GitHubClient(token_ref.mcp_token)

        cwd = payload.get("cwd")
        if cwd:
            resolved_cwd = resolve_allowed_working_directory(cwd, default=os.getcwd())
            if os.getcwd() != resolved_cwd:
                os.chdir(resolved_cwd)

        model_pin, model_head, chain_for_decision, payload_model = _resolve_model_chain_inputs(
            payload, settings
        )
        selected_slug, resolved_model, agent, use_model_chain = _resolve_agent_model(
            model_head, model_pin, chain_for_decision, settings
        )
        agent_id = agent.name
        _stamp_requested_model(
            tool_state, payload_model, chain_for_decision, selected_slug, resolved_model, payload
        )

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

        event_name = os.environ.get("GITHUB_EVENT_NAME", "unknown")
        setup_hook_failure, setup_script_skip_reason, setup_elapsed_s = await _run_setup_script(
            tool_state, settings, trust_tier, event_name, setup_timeout_s
        )

        modes = [
            *compute_modes(agent_id, settings.signed_commits),
            *_custom_modes(settings.modes),
        ]
        tool_state.modes = modes
        output_schema = resolve_output_schema()

        tool_context = _build_tool_context(
            payload=payload,
            settings=settings,
            run_context=run_context,
            agent_id=agent_id,
            github=github,
            token_ref=token_ref,
            modes=modes,
            tool_state=tool_state,
            tmpdir=tmpdir,
            trust_tier=trust_tier,
            resolved_model=resolved_model,
        )

        mcp_url, stop_mcp = start_mcp_http_server(tool_context, output_schema=output_schema)
        tool_context.mcp_server_url = mcp_url
        logger.info("» MCP server started at {}", mcp_url)
        subagent_denied = subagent_denied_tool_names(tool_context, output_schema)
        await _seed_learnings(tool_state, settings, tmpdir, payload)
        start_installation(tool_context)

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
            setup_hook_failure=setup_hook_failure,
            setup_script_skip_reason=setup_script_skip_reason,
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

        agent_timeout_ms, deadline_log = _compute_agent_deadline(timeout_ms, setup_elapsed_s)
        if deadline_log:
            logger.info(deadline_log)

        winning_slug, result = await _run_agent_with_timeout(
            _AgentRunArgs(
                agent=agent,
                agent_id=agent_id,
                selected_slug=selected_slug,
                use_model_chain=use_model_chain,
                settings=settings,
                model_head=model_head,
                model_pin=model_pin,
                run_ctx=run_ctx,
                payload=payload,
                run_context=run_context,
                output_schema=output_schema,
                tool_state=tool_state,
                tool_context=tool_context,
                setup_hook_failure=setup_hook_failure,
                setup_script_skip_reason=setup_script_skip_reason,
            ),
            agent_timeout_ms,
            timeout_raw,
        )

        if winning_slug:
            resolved_model = _promote_winning_slug(
                winning_slug, result, chain_for_decision, tool_state, tool_context, payload
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

        # D3/W5.2 + W6.1 + S1/D5/D10 — agent failure wins over prep / setup_script
        # failure; ``_classify_outcome`` maps the side-channels to the right
        # ``RunOutcome`` bucket.
        prep_reason = await _prep_failure_reason(tool_context)
        outcome, failure_reason = _classify_outcome(
            result=result,
            setup_reason=tool_state.setup_hook_failure or "",
            setup_policy=settings.setup_failure_policy,
            prep_reason=prep_reason,
        )

        packet_path = await _run_publish_span_block(
            tool_context, tool_state, settings, outcome, failure_reason
        )
        return _build_main_result(outcome, failure_reason, packet_path, result, tool_state)

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


if __name__ == "__main__":
    asyncio.run(main())
