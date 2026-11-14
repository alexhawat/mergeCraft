"""Prepare and dispatch Action review agents and reviewer groups."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.action.inputs import (
    apply_setup_overrides,
)
from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.shared import Agent, AgentResult, AgentRunContext
from mergecraft.agents.verifier import verifier_denied_tool_names
from mergecraft.analyzers.redact import redact_secrets
from mergecraft.analyzers.trust import (
    allow_repo_command_overrides,
    resolve_analyzers_mode,
)
from mergecraft.config.env import ActionInputEnv
from mergecraft.config.settings import ReviewSettings
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.dependencies import start_installation
from mergecraft.mcp.endpoints import mcp_role_url
from mergecraft.mcp.server import start_mcp_http_server
from mergecraft.mcp.tool_state import (
    ToolState,
)
from mergecraft.modes import _custom_modes, compute_modes
from mergecraft.review.roster_execution import (
    RosterExecutionSummary,
    primary_repo_state_dir,
    run_file_group_reviewers,
)
from mergecraft.review_policy.ignore_paths import list_pull_request_paths
from mergecraft.scm.github import (
    github_client_from_scm,
)
from mergecraft.utils.agent_resolve import (
    effective_model_chain,
    pick_runnable_slug_from_chain,
    promote_model_evidence,
    resolve_model,
    resolve_runtime_agent,
)
from mergecraft.utils.git_setup import (
    setup_git,
)
from mergecraft.utils.instructions import resolve_instructions
from mergecraft.utils.learnings import (
    seed_learnings_file,
    seed_xrepo_learnings_file,
)
from mergecraft.utils.payload import (
    resolve_output_schema,
)
from mergecraft.utils.process_group import (
    kill_all_active_process_groups,
    kill_process_group,
    register_process_group,
    unregister_process_group,
)
from mergecraft.utils.skills import install_bundled_skills
from mergecraft.utils.workspace import (
    resolve_allowed_working_directory,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.action.review_state import RunContext
    from mergecraft.config.settings import RepoSettings
    from mergecraft.modes import Mode
    from mergecraft.types import AgentId
    from mergecraft.utils.instructions import ResolvedInstructions

from mergecraft.errors import AgentTimeoutError as _AgentTimeoutError
from mergecraft.errors import ConfigurationError as _ConfigurationError
from mergecraft.review.pipeline.dispatch import dispatch_reviewer, resolve_review_provider_budget
from mergecraft.review.pipeline.prep import build_reviewer_context, configured_static_checks

_RunAttempt = Callable[
    [Agent, AgentRunContext, "RepoSettings", ToolState, str | None], Awaitable[AgentResult]
]


def _first_runnable_in_chain(chain: list[str]) -> str:
    """Harness-patchable one-arg facade over :func:`pick_runnable_slug_from_chain`.

    ``allow_fallback`` lives on the function object (not a module global) so the
    harness can still replace this symbol with ``lambda chain: …`` while
    ``main`` stamps the policy before calling.
    """
    allow = bool(getattr(_first_runnable_in_chain, "allow_fallback", True))
    return pick_runnable_slug_from_chain(chain, allow_fallback=allow)


_first_runnable_in_chain.allow_fallback = True  # type: ignore[attr-defined]  # — allow_fallback is a runtime attribute added to the function object for chain control


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


def _stamp_requested_model(ctx: RunContext, payload_model: object) -> None:
    """Record the chain head as the requested model (W10.2) and reset fallback bookkeeping.

    Split out of ``_assemble_model_chain`` (G4.2) purely to keep that
    function's complexity down — this is the tail of the same original
    contiguous block, called immediately after agent/model resolution.
    """
    assert ctx.tool_state is not None
    tool_state = ctx.tool_state
    # W10.2 — record the chain head as the requested model so the packet
    # can prove requested vs executed even when selection skipped ahead.
    if ctx.chain_for_decision:
        tool_state.requested_model = ctx.chain_for_decision[0]
    elif ctx.selected_slug:
        tool_state.requested_model = ctx.selected_slug
    elif isinstance(payload_model, str) and payload_model.strip():
        tool_state.requested_model = payload_model.strip()
    else:
        tool_state.requested_model = tool_state.model
    tool_state.fallback_index = 0
    tool_state.fallback_occurred = False


async def _assemble_model_chain(ctx: RunContext) -> None:
    """Model-chain assembly: resolve cwd, the effective chain, and the running agent.

    Local extraction out of ``_execute_agent`` (G4.2) — no behaviour change,
    only a name for this contiguous block of the original body.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    settings = ctx.settings
    tool_state = ctx.tool_state
    payload = ctx.payload

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
    chain_for_decision = effective_model_chain(settings=settings, head=model_head, pin=model_pin)
    # ``use_model_chain`` is true whenever an effective chain has more
    # than one entry OR the operator asked for the chain explicitly. The
    # legacy ``not model_explicit`` short-circuit is gone — a supplied
    # ``model:`` no longer disables the chain.
    use_model_chain = len(chain_for_decision) > 1 or (
        bool(chain_for_decision) and model_head is not None and not model_pin
    )
    ctx.model_pin = model_pin
    ctx.model_head = model_head
    ctx.chain_for_decision = chain_for_decision
    ctx.use_model_chain = use_model_chain
    selected_slug: str | None

    if use_model_chain:
        _first_runnable_in_chain.allow_fallback = settings.allow_fallback  # type: ignore[attr-defined]  # — allow_fallback is a runtime attribute added to the function object for chain control
        selected_slug = _first_runnable_in_chain(chain_for_decision)
        if not selected_slug:
            msg = "no runnable model slug in chain — configure credentials for at least one entry"
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
    agent = resolve_runtime_agent(model=resolved_model, settings=settings)
    agent_id = agent.name
    ctx.agent = agent
    ctx.agent_id = agent_id
    ctx.resolved_model = resolved_model
    ctx.selected_slug = selected_slug
    tool_state.model = resolved_model or payload.get("model")

    from mergecraft.utils.agent_resolve import collect_roster_credential_degradations

    degradations = collect_roster_credential_degradations(
        settings=settings,
        cwd=Path.cwd(),
        model_head=ctx.model_head,
        model_pin=ctx.model_pin,
    )
    if degradations:
        tool_state.credential_degradations = degradations
        for line in degradations:
            logger.warning("» {}", line)
        tool_state.run_manifest_trust = {
            **tool_state.run_manifest_trust,
            "credential_degradations": " | ".join(degradations),
        }

    _stamp_requested_model(ctx, payload_model)


def _agent_timeout_ms(ctx: RunContext) -> int | None:
    """Return the agent deadline: the run timeout minus setup elapsed (S1 / F6).

    A slow setup must NOT silently extend the total run deadline, so its
    wall-clock duration comes out of the agent's share. ``None`` means the
    run has no timeout.
    """
    if ctx.timeout_ms is None:
        return None
    return max(1, int(ctx.timeout_ms - ctx.setup_elapsed_s * 1000))


def _render_run_modes(ctx: RunContext, agent_id: AgentId) -> list[Mode]:
    """Render built-in plus custom modes for ``agent_id`` with this run's budgets."""
    assert ctx.settings is not None
    settings = ctx.settings
    agent_timeout_ms = _agent_timeout_ms(ctx)
    return [
        *compute_modes(
            agent_id,
            inline_budget=settings.analyzers.inline_budget,
            time_budget_minutes=None if agent_timeout_ms is None else agent_timeout_ms // 60_000,
        ),
        *_custom_modes(settings.modes),
    ]


async def _build_run_tool_context(ctx: RunContext) -> None:
    """Build ``tool_context`` — modes, output schema, analyzers mode, SARIF flag (S1/F3+F4).

    Built BEFORE the equal-deadline guard and the fail-policy short-circuit
    (both later, in ``_execute_agent``) so the outer handler can still call
    ``report_status_checks`` when those guards raise ``_ConfigurationError``.
    The MCP server URL is blank here; ``_prepare_agent_dispatch`` fills it
    in once ``start_mcp_http_server`` runs.
    """
    assert ctx.settings is not None
    assert ctx.run_context is not None
    assert ctx.tool_state is not None
    assert ctx.scm is not None
    assert ctx.token_ref is not None
    assert ctx.tmpdir is not None

    settings = ctx.settings
    run_context = ctx.run_context
    tool_state = ctx.tool_state
    token_ref = ctx.token_ref
    payload = ctx.payload

    modes = _render_run_modes(ctx, ctx.agent_id)
    tool_state.modes = modes
    ctx.modes = modes
    output_schema = resolve_output_schema()
    ctx.output_schema = output_schema

    ctx_payload = _payload_to_ctx(payload)
    ctx.ctx_payload = ctx_payload
    analyzers_mode = resolve_analyzers_mode(ActionInputEnv().analyzers)
    ctx.analyzers_mode = analyzers_mode
    sarif_upload_enabled = ctx.sarif_upload_enabled
    from mergecraft.mcp.tool_state import primary_repo_state

    ctx.tool_context = ToolContext(
        agent_id=ctx.agent_id,
        repo=RepoIdentity(owner=run_context.repo.owner, name=run_context.repo.name),
        payload=ctx_payload,
        scm=ctx.scm,
        github=github_client_from_scm(ctx.scm),
        github_installation_token=token_ref.mcp_token,
        git_token=token_ref.git_token,
        api_token=run_context.api_token,
        modes=modes,
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=ctx.tmpdir,
        refresh_git_token=token_ref.refresh_git_token,
        read_token=token_ref.read_token,
        xrepo=payload.get("xrepo"),
        prepush_script=settings.prepush_script,
        pr_approve_enabled=settings.pr_approve_enabled,
        mode_instructions=settings.mode_instructions,
        static_checks=configured_static_checks(settings),
        static_checks_enabled=(
            ctx_payload.shell != "disabled" and allow_repo_command_overrides(ctx.trust_tier)
        ),
        ci_gate_checks=dict(settings.ci_evidence.gates),
        ci_sarif_artifacts=list(settings.ci_evidence.sarif_artifacts),
        ci_coverage_artifacts=list(settings.ci_evidence.coverage_artifacts),
        ci_mutation_artifacts=list(settings.ci_evidence.mutation_artifacts),
        analyzers_mode=analyzers_mode,
        trust_tier=ctx.trust_tier,
        authority_trust=ctx.authority_trust,
        analyzers_settings_enabled=settings.analyzers.enabled,
        sarif_upload_enabled=sarif_upload_enabled,
        run_id=int(os.environ["GITHUB_RUN_ID"]) if os.environ.get("GITHUB_RUN_ID") else None,
        job_id=os.environ.get("GITHUB_JOB"),
        oss=run_context.oss,
        resolved_model=ctx.resolved_model,
        suggest_eval_add=bool(payload.get("suggestEvalAdd")),
        budget_tracker=ctx.budget_tracker,
        gh_event=ctx.gh_event,
    )
    from mergecraft.config.settings_snapshot import capture_run_scope_snapshot

    snapshot = capture_run_scope_snapshot(
        ctx.tool_context,
        root=Path(primary_repo_state(tool_state).dir),
        settings=settings,
        load_learnings_files=False,
        operator_owned=ctx.settings_snapshot_operator_owned,
    )
    from mergecraft.review.roster_auth import (
        RosterAuthError,
        RosterSecretEmptyError,
        validate_roster_at_run_start,
    )

    try:
        validate_roster_at_run_start(snapshot=snapshot)
    except (RosterAuthError, RosterSecretEmptyError) as exc:
        raise _ConfigurationError(str(exc)) from exc


async def _apply_overrides_and_setup_git(ctx: RunContext) -> None:
    """Apply setup-input overrides, re-raise a captured bad ``timeout``, run ``setup_git``.

    Both run AFTER ``tool_context`` exists (S1 review / NEW1) so the outer
    handler can still call ``report_status_checks`` for the
    ``configuration_error`` outcome, but BEFORE
    ``asyncio.create_subprocess_shell`` so a bad value never triggers the
    setup script to run.
    """
    assert ctx.settings is not None
    assert ctx.run_context is not None
    assert ctx.tool_state is not None
    assert ctx.token_ref is not None
    assert ctx.tmpdir is not None
    assert ctx.scm is not None

    try:
        settings = apply_setup_overrides(ctx.settings)
    except ValueError as exc:
        raise _ConfigurationError(str(exc)) from None
    ctx.settings = settings

    # S1 review / NEW1 — re-raise the captured bad-``timeout`` sentinel now
    # that ``tool_context`` exists. The input parsing already classified
    # the input as bad earlier (``_setup_run``); this only fires the guard
    # so a ``--notimeout`` / unset input still resolves to ``None`` /
    # ``3_600_000`` without firing.
    if ctx.timeout_error is not None:
        raise _ConfigurationError(ctx.timeout_error) from None

    await asyncio.to_thread(
        setup_git,
        git_token=ctx.token_ref.git_token,
        owner=ctx.run_context.repo.owner,
        name=ctx.run_context.repo.name,
        tool_state=ctx.tool_state,
        shell=ctx.payload.get("shell") or "restricted",
        tmpdir=ctx.tmpdir,
        octokit=github_client_from_scm(ctx.scm),
    )


async def _run_setup_script_phase(ctx: RunContext) -> None:
    """Run (or skip) the trusted-tier ``setup_script`` inside its wall-clock budget (S1/F6).

    The action-input resolver already bounds the upper end
    (``DEFAULT_SETUP_TIMEOUT_S`` = 10 m); the *only* cross-budget constraint
    is that ``setup_timeout_s`` be strictly less than the run timeout, so a
    failed setup script cannot be masked by an agent timeout (S1 review /
    F3 follow-up — equal-or-larger setup budgets let the setup script
    consume the entire run deadline, after which the agent budget is
    clamped to ~1 ms and the failure surfaces as ``_AgentTimeoutError``
    (``timed_out``) instead of the ``configuration_error`` /
    ``inconclusive`` the setup policy was supposed to produce). Only
    checked when a setup script is actually configured and a run timeout
    is in scope.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    settings = ctx.settings
    tool_state = ctx.tool_state

    configured_setup_timeout_s = settings.setup_timeout_s
    timeout_ms = ctx.timeout_ms
    if (
        settings.setup_script
        and timeout_ms is not None
        and configured_setup_timeout_s * 1000 >= timeout_ms
    ):
        raise _ConfigurationError(
            f"setup_timeout ({configured_setup_timeout_s}s) must be less than the run "
            f"timeout ({timeout_ms // 1000}s) so a failed setup script is not "
            f"masked as an agent timeout"
        )
    setup_timeout_s = configured_setup_timeout_s
    ctx.setup_timeout_s = setup_timeout_s

    setup_script_skip_reason = ""
    setup_hook_failure = ""
    setup_started_at = time.monotonic()
    if settings.setup_script:
        if ctx.trust_tier == "trusted":
            logger.info("» running setup script")
            proc = await asyncio.create_subprocess_shell(
                settings.setup_script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # F6 — session leader so killpg reaches grandchildren
            )
            register_process_group(proc.pid)
            try:
                _out, err = await asyncio.wait_for(proc.communicate(), timeout=setup_timeout_s)
            except TimeoutError:
                # F6 — TERM → grace → KILL the whole tree (convention 9).
                kill_process_group(proc.pid)
                setup_hook_failure = f"setup script timed out after {setup_timeout_s}s"
            else:
                if proc.returncode != 0:
                    # S1 review / NEW3 — redact the full stderr text
                    # BEFORE truncating to 500 chars. Truncating first
                    # can lop a ``ghp_…`` token below the redactor's
                    # pattern minimum length, leaving a partial prefix
                    # in the prompt — redaction must run on the whole
                    # input so the pattern matches and the slice is
                    # taken from the *redacted* output.
                    detail = redact_secrets((err or b"").decode(errors="replace"))[:500]
                    setup_hook_failure = f"setup script failed (exit {proc.returncode}): {detail}"
            finally:
                unregister_process_group(proc.pid)
            if setup_hook_failure:
                tool_state.setup_hook_failure = setup_hook_failure
                logger.warning("» {}", setup_hook_failure)
        else:
            event_name = os.environ.get("GITHUB_EVENT_NAME", "unknown")
            setup_script_skip_reason = (
                f"skipped setup_script on untrusted tier ({event_name} event)"
            )
            tool_state.setup_script_skip_reason = setup_script_skip_reason
            logger.warning("» {}", setup_script_skip_reason)
    setup_elapsed_s = time.monotonic() - setup_started_at
    ctx.setup_hook_failure = setup_hook_failure
    if setup_script_skip_reason:
        ctx.setup_script_skip_reason = setup_script_skip_reason
    ctx.setup_elapsed_s = setup_elapsed_s
    tool_state.phase_elapsed_s["setup"] = round(setup_elapsed_s, 3)


async def _run_start_instruction_scope(
    ctx: RunContext,
) -> tuple[list[str], ReviewSettings | None]:
    """Resolve ranking paths and config for the bound PR before any harness runs."""
    from mergecraft.config.trust_policy import bound_head_sha
    from mergecraft.review_policy.ignore_paths import _base_review_settings, _event_base_sha

    event = ctx.gh_event or {}
    pull = event.get("pull_request")
    if not isinstance(pull, dict):
        return [], None
    assert ctx.tool_context is not None
    scm, repo = ctx.tool_context.scm, ctx.tool_context.repo
    base_sha = _event_base_sha(event)
    review = None
    if base_sha:
        review, _source, _detail = await _base_review_settings(scm, repo.owner, repo.name, base_sha)
    review = review if review is not None else ReviewSettings()

    head_sha = bound_head_sha(event, event_name=os.environ.get("GITHUB_EVENT_NAME", ""))
    number = pull.get("number")
    if not base_sha or not head_sha or not isinstance(number, int):
        return [], review
    paths = await list_pull_request_paths(
        scm, repo.owner, repo.name, number, head_sha=head_sha, base_sha=base_sha
    )
    return paths or [], review


async def _prepare_agent_dispatch(ctx: RunContext) -> None:
    """Start the MCP server, seed learnings/skills, resolve instructions, build ``run_ctx``.

    ``tool_context``, ``modes``, ``output_schema``, ``ctx_payload``,
    ``analyzers_mode`` and ``sarif_upload_enabled`` were all built earlier
    in ``_build_run_tool_context`` — before the equal-deadline guard and
    the fail-policy short-circuit in ``_execute_agent`` — so the outer
    handler can still call ``report_status_checks`` when those guards
    raise ``_ConfigurationError``. The MCP server URL is filled in here.
    """
    assert ctx.tool_context is not None
    assert ctx.settings is not None
    assert ctx.run_context is not None
    assert ctx.tool_state is not None
    assert ctx.tmpdir is not None

    tool_context = ctx.tool_context
    settings = ctx.settings
    run_context = ctx.run_context
    tool_state = ctx.tool_state
    payload = ctx.payload
    tmpdir = ctx.tmpdir

    # The setup script ran after ``_build_run_tool_context`` rendered the modes;
    # re-render so ``${TIME_BUDGET}`` states the deadline net of its elapsed time.
    if ctx.setup_elapsed_s:
        modes = _render_run_modes(ctx, ctx.agent_id)
        ctx.modes = modes
        tool_state.modes = modes
        tool_context.modes = modes

    mcp_url, stop_mcp = start_mcp_http_server(tool_context, output_schema=ctx.output_schema)
    tool_context.mcp_server_url = mcp_url
    ctx.mcp_url = mcp_url
    ctx.stop_mcp = stop_mcp
    _reviewer_mcp_url = mcp_role_url(mcp_url, None)
    logger.info("» MCP server started at {}", mcp_url)

    subagent_denied = subagent_denied_tool_names(tool_context, ctx.output_schema)
    ctx.subagent_denied = subagent_denied
    verifier_denied = verifier_denied_tool_names(tool_context, ctx.output_schema)
    ctx.verifier_denied = verifier_denied

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

    from mergecraft.review.consumer_mcp import load_consumer_mcp_servers

    repo_root = Path.cwd()
    trust_tier = str(tool_state.trust_tier or "untrusted")
    consumer_mcp = load_consumer_mcp_servers(
        repo_root,
        configured=list(settings.review.mcp_servers),
        trust_tier=trust_tier,
    )
    tool_state.review_mcp_names = tuple(server.name for server in consumer_mcp)
    tool_state.review_mcp_servers = tuple(consumer_mcp)
    changed_paths, review_instruction_settings = await _run_start_instruction_scope(ctx)
    instructions = resolve_instructions(
        payload=payload,
        repo=run_context.repo,
        modes=ctx.modes,
        agent_id=ctx.agent_id,
        output_schema=ctx.output_schema,
        learnings_file_path=tool_state.learnings_file_path,
        learnings_headings=settings.learnings_headings,
        setup_hook_failure=ctx.setup_hook_failure,
        setup_script_skip_reason=ctx.setup_script_skip_reason,
        xrepo_brief=settings.xrepo_brief,
        xrepo_learnings_file_path=tool_state.xrepo_learnings_file_path,
        xrepo_learnings_headings=settings.xrepo_learnings_headings,
        repo_root=repo_root,
        trust_tier=trust_tier,
        review_mcp_names=list(tool_state.review_mcp_names),
        changed_paths=changed_paths,
        review_instruction_settings=review_instruction_settings,
    )
    ctx.run_start_instructions = {str(ctx.agent_id): instructions}
    for other_agent_id in _run_start_harnesses(ctx):
        if other_agent_id in ctx.run_start_instructions:
            continue
        ctx.run_start_instructions[other_agent_id] = _render_agent_instructions(
            ctx,
            agent_id=other_agent_id,
            modes=_render_run_modes(ctx, other_agent_id),  # type: ignore[arg-type]  # — str from Agent.name is an AgentId at runtime
            repo_root=repo_root,
            changed_paths=changed_paths,
            review_instruction_settings=review_instruction_settings,
        )
    tool_state.review_skill_paths = tuple(
        str(item) for item in instructions.extra.get("review_skills") or []
    )
    tool_state.review_skills_ledger = tuple(
        str(item) for item in instructions.extra.get("review_skills_ledger") or []
    )
    ctx.instructions = instructions
    logger.info("Using agent={} model={}", ctx.agent_id, ctx.resolved_model or "(auto)")

    ctx.run_ctx = build_reviewer_context(
        tool_context,
        payload=payload,
        mcp_server_url=_reviewer_mcp_url,
        subagent_denied_tools=subagent_denied,
        verifier_denied_tools=verifier_denied,
        instructions=instructions,
        idle_timeout_s=float(settings.agent_idle_timeout_s),
    )


def _render_agent_instructions(
    ctx: RunContext,
    *,
    agent_id: str,
    modes: list[Mode],
    repo_root: Path,
    changed_paths: Sequence[str],
    review_instruction_settings: ReviewSettings | None,
) -> ResolvedInstructions:
    """Render one harness's instructions with this run's run-start inputs."""
    assert ctx.settings is not None
    assert ctx.run_context is not None
    assert ctx.tool_state is not None
    settings = ctx.settings
    tool_state = ctx.tool_state
    return resolve_instructions(
        payload=ctx.payload,
        repo=ctx.run_context.repo,
        modes=modes,
        agent_id=agent_id,
        output_schema=ctx.output_schema,
        learnings_file_path=tool_state.learnings_file_path,
        learnings_headings=settings.learnings_headings,
        setup_hook_failure=ctx.setup_hook_failure,
        setup_script_skip_reason=ctx.setup_script_skip_reason,
        xrepo_brief=settings.xrepo_brief,
        xrepo_learnings_file_path=tool_state.xrepo_learnings_file_path,
        xrepo_learnings_headings=settings.xrepo_learnings_headings,
        repo_root=repo_root,
        trust_tier=str(tool_state.trust_tier or "untrusted"),
        review_mcp_names=list(tool_state.review_mcp_names),
        changed_paths=changed_paths,
        review_instruction_settings=review_instruction_settings,
    )


def _run_start_harnesses(ctx: RunContext) -> list[str]:
    """Harness names any attempt or server-side reviewer of this run may run under.

    Resolved at run start, before the first attempt can check the reviewed
    head out into the workspace, so each harness's instructions are rendered
    from the tree the run started on. A slug or binding that cannot be resolved
    here is skipped: an attempt on it would fail to resolve its agent anyway,
    and a reviewer on it is refused for want of run-start instructions.
    """
    assert ctx.settings is not None
    settings = ctx.settings
    harnesses: list[str] = []

    def _add(model: str | None) -> None:
        try:
            agent = resolve_runtime_agent(
                model=resolve_model(slug=model, respect_env_override=False) if model else None,
                settings=settings,
            )
        except Exception as exc:  # an unresolvable rung renders nothing; it cannot run
            logger.debug("run-start instructions: no harness for {!r}: {}", model, exc)
            return
        if agent.name not in harnesses:
            harnesses.append(str(agent.name))

    if ctx.use_model_chain:
        for slug in ctx.chain_for_decision:
            _add(slug)
    if ctx.tool_context is not None and ctx.tool_state is not None:
        try:
            from mergecraft.agents.registry import AgentRole, load_registry, resolve_agent_model
            from mergecraft.config.settings_snapshot import repo_settings_from_context

            roster_settings = repo_settings_from_context(ctx.tool_context)
            registry = load_registry(settings=roster_settings, repo_root=Path.cwd())
            reviewers = registry.resolve_roles(AgentRole.reviewer)
        except Exception as exc:  # no roster to render for
            logger.debug("run-start instructions: roster unavailable: {}", exc)
            reviewers = ()
        for binding in reviewers:
            try:
                slug = resolve_agent_model(binding, settings=roster_settings).dispatched_model
            except Exception as exc:  # an unresolvable binding is refused at dispatch
                logger.debug("run-start instructions: binding {}: {}", binding.agent_id, exc)
                continue
            _add(slug)
    return harnesses


def _promote_and_finalize_agent_result(
    ctx: RunContext, winning_slug: str | None, result: AgentResult
) -> AgentResult:
    """Post-process the dispatched ``AgentResult``: model promotion, usage, schema check.

    Split out of ``_dispatch_agent_with_deadline`` (G4.2) purely to keep
    that function's complexity down — this is the tail of the same
    original contiguous block, called immediately after the agent task
    resolves (whether via the plain await or the deadline-wrapped one).
    """
    assert ctx.tool_state is not None
    assert ctx.tool_context is not None
    tool_state = ctx.tool_state
    tool_context = ctx.tool_context
    chain_for_decision = ctx.chain_for_decision
    output_schema = ctx.output_schema
    # Slice 6 — keep the watchdog diagnostic so the packet and the check
    # summary can name *what* stalled, not only that the clock expired.
    if (result.metadata or {}).get("idle_timeout"):
        tool_state.agent_diagnostic = dict(result.metadata)

    if winning_slug:
        resolved_model = resolve_model(slug=winning_slug, respect_env_override=False)
        tool_context.resolved_model = resolved_model
        ctx.resolved_model = resolved_model
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
        executed = resolved_model or winning_slug
        promote_model_evidence(
            tool_state,
            requested_model=requested,
            executed_model=executed if isinstance(executed, str) else winning_slug,
            fallback_index=fallback_index,
        )

    if result.usage:
        from mergecraft.agents.curated_model_catalog import apply_catalog_cost_to_usage

        usage = apply_catalog_cost_to_usage(result.usage, model=tool_state.model)
        if usage is not None:
            result = replace(result, usage=usage)
        tool_state.usage_entries.append(result.usage)
        from mergecraft.utils.run_bounds import BudgetExhausted, record_agent_usage

        try:
            record_agent_usage(ctx.budget_tracker, result.usage, phase="reviewer_dispatch")
        except BudgetExhausted as exc:
            ctx.budget_exhaustion = exc

    from mergecraft.utils.llm_review_timing import snapshot_llm_review_timing

    timing_snapshot = snapshot_llm_review_timing()
    if timing_snapshot is not None and tool_state.selected_mode in {"Review", "IncrementalReview"}:
        tool_state.llm_review_timing = timing_snapshot

    if output_schema and result.success:
        # Classified by the shared resolver (inconclusive), the same way the
        # offline review reads a missing ``set_output`` — not as a crash.
        from mergecraft.review.outcome_resolution import structured_output_error

        ctx.structured_output_error = structured_output_error(tool_state.output)

    return result


async def _run_agent_task_with_deadline(
    ctx: RunContext, *, dispatch_chained: _RunAttempt, dispatch_single: _RunAttempt
) -> tuple[str | None, AgentResult]:
    """Dispatch the agent (or model chain) as a task and await it under the deadline.

    ``timeout_ms`` / ``timeout_raw`` were resolved up front in
    ``_setup_run`` (right after ``payload = resolve_payload(...)``) so the
    setup-script budget could be capped against the run deadline (S1 /
    F6). The ``--notimeout`` / ``none`` escape and the fail-closed
    validation both happened there; this just spends the resolved values.
    """
    assert ctx.settings is not None
    assert ctx.run_context is not None
    assert ctx.tool_state is not None
    assert ctx.tool_context is not None
    assert ctx.run_ctx is not None
    assert ctx.agent is not None

    settings = ctx.settings
    tool_state = ctx.tool_state
    tool_context = ctx.tool_context
    run_ctx = ctx.run_ctx
    agent = ctx.agent
    agent_id = ctx.agent_id
    model_head = ctx.model_head
    model_pin = ctx.model_pin
    use_model_chain = ctx.use_model_chain
    selected_slug = ctx.selected_slug
    output_schema = ctx.output_schema

    from mergecraft.utils.llm_review_timing import bind_llm_review_timing_tracker

    # The reviewer normally selects its mode during dispatch. Bind before the
    # task is created so its first generation and every secondary share a tracker.
    bind_llm_review_timing_tracker()

    async def _run_agent_once(slug: str) -> AgentResult:
        attempt_model = resolve_model(slug=slug, respect_env_override=False)
        attempt_agent = resolve_runtime_agent(model=attempt_model, settings=settings)
        attempt_agent_id = attempt_agent.name

        if attempt_agent_id == agent_id:
            attempt_ctx = replace(run_ctx, resolved_model=attempt_model)
        else:
            attempt_modes = _render_run_modes(ctx, attempt_agent_id)
            # Every attempt reuses the instructions resolved at run start; an
            # earlier attempt may have checked the reviewed head out into the
            # workspace, so nothing is re-rendered from the tree now.
            attempt_instructions = ctx.run_start_instructions.get(str(attempt_agent_id))
            if attempt_instructions is None:
                return AgentResult(
                    success=False,
                    error=(
                        f"no instructions were resolved at run start for harness "
                        f"{attempt_agent_id!r}; the attempt does not run"
                    ),
                    metadata={"retryable": True},
                )
            # ``ToolContext`` has a custom ``__init__``, so ``dataclasses.replace``
            # cannot copy it; evaluate the denied sets under the attempt's id.
            previous_agent_id = tool_context.agent_id
            tool_context.agent_id = attempt_agent_id
            try:
                attempt_denied = subagent_denied_tool_names(tool_context, output_schema)
                attempt_verifier_denied = verifier_denied_tool_names(tool_context, output_schema)
            finally:
                tool_context.agent_id = previous_agent_id
            attempt_ctx = replace(
                run_ctx,
                resolved_model=attempt_model,
                instructions=attempt_instructions,
                subagent_denied_tools=attempt_denied,
                verifier_denied_tools=attempt_verifier_denied,
            )
            tool_context.agent_id = attempt_agent_id
            tool_context.modes = attempt_modes
            tool_state.modes = attempt_modes
            tool_context.resolved_model = attempt_model
            logger.info(
                "» model chain advanced to agent={} model={}",
                attempt_agent_id,
                attempt_model or "(auto)",
            )
        return await dispatch_chained(
            attempt_agent, attempt_ctx, settings, tool_state, attempt_model
        )

    async def _dispatch_selected_agent() -> tuple[str | None, AgentResult]:
        async def _single_attempt() -> tuple[str | None, AgentResult]:
            return selected_slug, await dispatch_single(
                agent, run_ctx, settings, tool_state, ctx.resolved_model
            )

        dispatched = await dispatch_reviewer(
            settings,
            model_head=model_head,
            model_pin=model_pin,
            tool_state=tool_state,
            run_once=_run_agent_once,
            single_attempt=None if use_model_chain else _single_attempt,
        )
        return dispatched.winning_slug, dispatched.agent_result

    from mergecraft.agents.token_budget import bind_run_budget
    from mergecraft.jev.types import PINNED_MODEL

    provider_budget = resolve_review_provider_budget(
        model=ctx.resolved_model or PINNED_MODEL,
        max_tokens=ctx.run_bounds.token_budget if ctx.run_bounds is not None else 250_000,
    )
    with bind_run_budget(provider_budget):
        agent_task = asyncio.create_task(_dispatch_selected_agent())

        # S1 / F6 — deduct the setup-script elapsed time from the agent
        # deadline. A slow setup must NOT silently extend the total run
        # deadline. ``setup_elapsed_s`` is the wall-clock duration measured
        # by the bounded setup block above; ``timeout_ms`` is the
        # pre-deduction run budget.
        timeout_ms = ctx.timeout_ms
        agent_timeout_ms = _agent_timeout_ms(ctx)
        if agent_timeout_ms is not None and agent_timeout_ms != timeout_ms:
            logger.info(
                "» deducted setup elapsed {:.2f}s from agent deadline ({}s -> {}s)",
                ctx.setup_elapsed_s,
                (timeout_ms or 0) / 1000,
                agent_timeout_ms / 1000,
            )

        # Stamped unconditionally (deadline or not) so a record rendered
        # mid-dispatch — inside the terminal publish call — can report the
        # agent phase as elapsed-so-far instead of 0s (#1075).
        tool_state.agent_started_monotonic = time.monotonic()
        if agent_timeout_ms is None:
            winning_slug, result = await agent_task
        else:
            agent_started = tool_state.agent_started_monotonic
            ctx.agent_deadline_monotonic = agent_started + agent_timeout_ms / 1000.0
            # The MCP server reads these to tell the agent how much time it has used.
            tool_state.agent_deadline_s = agent_timeout_ms / 1000.0
            try:
                winning_slug, result = await asyncio.wait_for(
                    agent_task, timeout=agent_timeout_ms / 1000.0
                )
            except TimeoutError:
                agent_task.cancel()
                kill_all_active_process_groups()
                msg = f"agent run timed out after {ctx.timeout_raw or '1h'}"
                raise _AgentTimeoutError(msg) from None

    return winning_slug, result


async def _run_server_roster_reviewers_if_needed(ctx: RunContext) -> RosterExecutionSummary | None:
    """Dispatch file groups and secondary reviewers server-side; return the roster summary.

    The opt-in file-group fan-out (``review.fileGroupFanout``) runs first, after
    the primary reviewer. Its failures are run-health notes recorded on the tool
    state, so its summary is never folded into the roster result.
    """
    assert ctx.tool_context is not None
    assert ctx.tool_state is not None
    assert ctx.settings is not None
    assert ctx.run_ctx is not None
    if ctx.tool_state.selected_mode not in {"Review", "IncrementalReview"}:
        return None
    from mergecraft.review.roster_execution import run_pending_roster_reviewers

    def _remaining_roster_timeout_s() -> float | None:
        if ctx.agent_deadline_monotonic is None:
            return None
        return max(1.0, ctx.agent_deadline_monotonic - time.monotonic())

    if ctx.settings.review.file_group_fanout.enabled:
        fanout = await run_file_group_reviewers(
            tool_context=ctx.tool_context,
            base_run_ctx=ctx.run_ctx,
            settings=ctx.settings,
            payload=ctx.payload,
            repo_root=Path(primary_repo_state_dir(ctx.tool_state)),
            remaining_timeout_s=_remaining_roster_timeout_s,
            instructions_for=ctx.run_start_instructions.get,
        )
        if fanout.degraded:
            logger.warning(
                "» file-group fan-out degraded: {} group(s) recorded as run health",
                len(fanout.failures),
            )

    # Each secondary reviewer runs under its own deadline budget, never the
    # remainder of the primary's (``secondary_reviewer_timeout_s``).
    return await run_pending_roster_reviewers(
        tool_context=ctx.tool_context,
        base_run_ctx=ctx.run_ctx,
        settings=ctx.settings,
        payload=ctx.payload,
        instructions_for=ctx.run_start_instructions.get,
    )
