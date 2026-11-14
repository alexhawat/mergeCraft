"""Materialize the Action run and bind credentials to its trust policy."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.action.inputs import (
    apply_tracing_overrides,
    collect_tracing_warnings_for_summary,
    export_tracing_env_from_action_inputs,
)
from mergecraft.analyzers.sarif_upload import resolve_sarif_upload_enabled
from mergecraft.config.env import ActionInputEnv, EnvSettingsError, validate_env_settings
from mergecraft.mcp.tool_state import (
    ProgressComment,
    init_tool_state,
)
from mergecraft.scm.github import (
    create_github_scm,
    github_client_from_scm,
)
from mergecraft.utils import gha_log
from mergecraft.utils.git_setup import (
    create_temp_directory,
    wipe_runner_leak_surface,
)
from mergecraft.utils.github import GitHubClient, resolve_run_context_data
from mergecraft.utils.log import bind_run_context
from mergecraft.utils.payload import (
    TIMEOUT_DISABLED,
    read_github_event,
    resolve_payload,
    resolve_prompt_input,
    resolve_timeout_ms,
)
from mergecraft.utils.secrets import set_env_allowlist
from mergecraft.utils.token import get_job_token, resolve_tokens

if TYPE_CHECKING:
    from mergecraft.action.review_state import RunContext
    from mergecraft.config.settings import RepoSettings
    from mergecraft.scm.protocol import ScmProvider


from mergecraft.action.review_pull import _remember_pull_request
from mergecraft.errors import ConfigurationError as _ConfigurationError


@dataclass(frozen=True, slots=True)
class _ActionDeadline:
    timeout_ms: int | None
    error: str | None


def _resolve_action_deadline(timeout_raw: Any, *, default_timeout_ms: int) -> _ActionDeadline:
    """Resolve the configured deadline before any setup script can run."""
    timeout_ms: int | None
    timeout_error: str | None = None
    if timeout_raw == TIMEOUT_DISABLED:
        timeout_ms = None
    elif timeout_raw:
        usable = resolve_timeout_ms(timeout_raw)
        if usable is None:
            timeout_ms = None
            timeout_error = (
                f'invalid timeout "{timeout_raw}" '
                "(use a duration like 10m/1h or --notimeout to disable)"
            )
        else:
            timeout_ms = usable
    else:
        timeout_ms = default_timeout_ms
    return _ActionDeadline(timeout_ms, timeout_error)


async def _setup_run(ctx: RunContext, *, default_timeout_ms: int) -> RunContext:
    """Phase 1 — prompt resolution, run context, tool state, deadline inputs (G4.2).

    Populates everything ``_resolve_credentials`` and ``_execute_agent`` need
    but does not itself touch tokens or derive trust tier — that is the
    security boundary handled entirely by ``_resolve_credentials``.
    """
    ctx.job_token = get_job_token()
    github_client = GitHubClient(ctx.job_token)
    ctx.scm = create_github_scm(ctx.job_token, client=github_client)
    run_context = await resolve_run_context_data(github_client)
    ctx.run_context = run_context
    try:
        # Prompt resolution builds ``ActionInputEnv`` (the prompt fields share the
        # model with the fail-closed tracing inputs), so it belongs inside this
        # guard too: a malformed ``INPUT_TRACING`` must map to
        # ``_ConfigurationError`` (→ ``configuration_error``), never fall through
        # to the generic ``infra_error`` bucket. Plain prompt-validation errors
        # are not ``EnvSettingsError`` and propagate exactly as before.
        resolved_prompt = resolve_prompt_input()
        ctx.resolved_prompt = resolved_prompt
        export_tracing_env_from_action_inputs()
        validate_env_settings()
    except EnvSettingsError as exc:
        # A malformed control-carrying setting fails configuration before any
        # subprocess or agent exists. ``_ConfigurationError`` maps to
        # ``RunOutcome.configuration_error``; the message names the variable
        # and never the value.
        raise _ConfigurationError(str(exc)) from exc
    settings = apply_tracing_overrides(run_context.repo_settings)
    for tracing_warning in collect_tracing_warnings_for_summary():
        logger.warning(tracing_warning)
        gha_log.warning(tracing_warning)
    ctx.settings = settings
    from mergecraft.utils.run_bounds import BudgetTracker, resolve_run_bounds

    ctx.run_bounds = resolve_run_bounds(settings=settings)
    ctx.budget_tracker = BudgetTracker(ctx.run_bounds)

    gh_event = read_github_event()
    ctx.gh_event = gh_event

    pr_number: int | str | None = None
    if isinstance(gh_event, dict):
        pr = gh_event.get("pull_request")
        if isinstance(pr, dict) and pr.get("number") is not None:
            pr_number = pr["number"]
        else:
            issue = gh_event.get("issue")
            if (
                isinstance(issue, dict)
                and isinstance(issue.get("pull_request"), dict)
                and issue.get("number") is not None
            ):
                pr_number = issue["number"]
    ctx.pr_number = pr_number
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
    if pr_number is not None:
        tool_state.pr_number = int(pr_number)
    # HS2 — read the capture flag once, at run start, so a mid-run env change
    # cannot turn verdict capture on or off partway through a review.
    from mergecraft.evidence.verdict_capture import capture_verdicts_enabled

    tool_state.capture_verdicts = capture_verdicts_enabled()
    ctx.tool_state = tool_state
    tmpdir = create_temp_directory()
    ctx.tmpdir = tmpdir

    if settings.env_allowlist:
        set_env_allowlist(settings.env_allowlist)

    payload = resolve_payload(resolved_prompt, settings)
    ctx.payload = payload
    tool_state.model = payload.get("model")
    tool_state.oss = run_context.oss

    # Resolve the run deadline up front so the setup-script budget can
    # be capped against it (S1 / F6 — setup must never consume the
    # whole run budget). Invalid input is captured into a sentinel
    # ``timeout_error``; the actual ``_ConfigurationError`` raise is
    # deferred until AFTER ``tool_context`` is constructed so the
    # outer handler can still call ``report_status_checks`` for the
    # ``configuration_error`` outcome (S1 review / NEW1+NEW2 —
    # building the reporting context first, then validating, prevents
    # setup from running on bad inputs while preserving completion-
    # check reporting).
    timeout_raw = payload.get("timeout")
    ctx.timeout_raw = timeout_raw
    deadline = _resolve_action_deadline(timeout_raw, default_timeout_ms=default_timeout_ms)
    ctx.timeout_ms = deadline.timeout_ms
    ctx.timeout_error = deadline.error

    wipe_runner_leak_surface()

    if payload.get("shell") != "enabled":
        os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_URL", None)
        os.environ.pop("ACTIONS_ID_TOKEN_REQUEST_TOKEN", None)

    ctx.setup_completed = True
    return ctx


def _composed_prompt_from_payload(ctx: RunContext) -> str | None:
    """Return the composed review prompt this run actually uses, if any (F1).

    The Action writes the workflow's composed ``steps.prompt.outputs.text`` to the
    ``prompt`` input; ``resolve_payload`` stores it at ``payload["prompt"]`` (a JSON
    dispatch payload keeps the same key). Returns ``None`` when no usable prompt is
    present, so the caller leaves the event untouched.
    """
    prompt = (ctx.payload or {}).get("prompt")
    return prompt if isinstance(prompt, str) and prompt.strip() else None


async def _resolve_credentials(
    ctx: RunContext,
) -> RunContext:
    """Phase 2 — token brokering + trust-tier derivation. Behaviour-frozen (S4).

    Security boundary: token precedence (``GH_TOKEN`` > job token; App-JWT
    mint wins when configured, degrades to the job token on mint failure;
    no token anywhere fails closed) and trust-tier derivation (fail-closed
    ``untrusted`` default) must survive this extraction byte-for-byte — see
    ``tests/test_main_phases.py::test_resolve_credentials_matches_current_precedence``.
    """
    assert ctx.scm is not None
    assert ctx.run_context is not None
    settings = await _bind_action_trust(ctx)

    # Resolve capability-dependent API permissions only after repository
    # settings have passed the trust-tier filter. The same resolved SARIF flag
    # is carried into ToolContext later; it must not be reinterpreted after the
    # App tokens have already been minted.
    sarif_upload_enabled = resolve_sarif_upload_enabled(
        action_input=ActionInputEnv().sarif_upload,
        repo_setting=settings.analyzers.sarif_upload,
    )
    ctx.sarif_upload_enabled = sarif_upload_enabled
    token_ref = await resolve_tokens(
        push=ctx.payload.get("push") or "restricted",
        xrepo=ctx.payload.get("xrepo"),
        primary_repo=f"{ctx.run_context.repo.owner}/{ctx.run_context.repo.name}",
        status_checks=bool(ctx.payload.get("statusChecks")),
        sarif_upload=sarif_upload_enabled,
    )
    ctx.token_ref = token_ref
    # Prefer MCP token for API calls. Closing the superseded job-token client is
    # best-effort: a failure must not sink the run (CR-D8), so it is logged once
    # and the MCP-token client is installed regardless.
    await _close_superseded_scm(ctx.scm)
    ctx.scm = create_github_scm(token_ref.mcp_token, client=GitHubClient(token_ref.mcp_token))
    await _read_linked_issues(ctx)

    return ctx


async def _read_linked_issues(ctx: RunContext) -> None:
    """Record the issues this pull request closes, with their authors, once, at run start.

    The ``requirements`` policy evidence producer maps their acceptance criteria
    against the diff and names their authors. A run without a pull request reads
    nothing and leaves ``ToolState.linked_issues`` at ``None``. A read that fails,
    is malformed or spans more than one page *writes* ``None`` ("not read"), so the
    evidence stays absent rather than treating the pull request as closing nothing.
    """
    tool_state = ctx.tool_state
    run_context = ctx.run_context
    if tool_state is None or run_context is None or ctx.pr_number is None or ctx.scm is None:
        return
    client = github_client_from_scm(ctx.scm)
    if client is None:
        tool_state.linked_issues = None
        return
    try:
        issues = await client.closing_issues(
            run_context.repo.owner, run_context.repo.name, int(ctx.pr_number)
        )
    except Exception as exc:  # an advisory read: a failure must never fail the run
        logger.warning(
            "linked issues of PR #{} could not be read; requirements evidence stays absent: {}",
            ctx.pr_number,
            exc,
        )
        tool_state.linked_issues = None
        return
    if issues is None:
        logger.warning(
            "linked issues of PR #{} were not fully read; requirements evidence stays absent",
            ctx.pr_number,
        )
    tool_state.linked_issues = issues


async def _close_superseded_scm(scm: ScmProvider) -> None:
    """Best-effort close of the job-token SCM before the MCP-token SCM replaces it.

    A failure here is logged once, naming the superseded handle and never a
    secret, and never changes the run outcome (CR-D8). The replacement client
    is still closed by the best-effort ``finally`` teardown.
    """
    try:
        await scm.aclose()
    except Exception as exc:
        logger.warning(
            "» could not close superseded scm handle: {}: {}",
            type(exc).__name__,
            exc,
        )


async def _bind_action_trust(ctx: RunContext) -> RepoSettings:
    assert ctx.tool_state is not None
    assert ctx.scm is not None
    assert ctx.run_context is not None

    from mergecraft.action.inputs import (
        ForkCredentialInvariantError,
        validate_fork_credential_invariant,
    )
    from mergecraft.agents.codex import CODEX_SANDBOX_UNSANDBOXED
    from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
    from mergecraft.config.trust_policy import (
        agent_sandbox_manifest_fields,
        bound_head_sha,
        default_branch_from_event,
        log_trust_policy_at_run_start,
        resolve_agent_sandbox_decision,
        resolve_trust_policy,
        trust_policy_manifest_fields,
    )

    repo_root = Path.cwd()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    gh_event = await _bind_action_event(ctx, event_name=event_name)

    try:
        validate_fork_credential_invariant(event=gh_event, env=os.environ, settings=ctx.settings)
    except ForkCredentialInvariantError as exc:
        raise _ConfigurationError(str(exc)) from exc

    # D7 — the same ``event_name`` read above for ``resolve_trust_policy``
    # also decides whether the settings this snapshot pins are operator-owned
    # (the base ref, which only a ``pull_request_target`` run checks out
    # before ``checkout_pr`` ever runs). Every downstream reader of this
    # snapshot's provenance (tracing's D7 cap included) must consult
    # ``snapshot.operator_owned`` rather than re-deriving its own opinion of
    # the event from the ambient environment — see
    # ``mergecraft.tracing.genai._yaml_export_untrusted_for_capture`` and
    # e656debc's lesson: two independent reads of the same env var can disagree.
    operator_owned_settings = event_name == "pull_request_target"
    ctx.settings_snapshot_operator_owned = operator_owned_settings
    snapshot = capture_repo_settings_snapshot(
        root=repo_root,
        settings=ctx.settings,
        operator_owned=operator_owned_settings,
    )
    shell = str(ctx.payload.get("shell") or "restricted")
    policy = resolve_trust_policy(
        event=gh_event,
        config_root=repo_root,
        event_name=event_name,
        settings_snapshot=snapshot,
        shell=shell,
    )
    log_trust_policy_at_run_start(policy)

    from mergecraft.config.env import RuntimeOverridesEnv

    operator_override_requested = RuntimeOverridesEnv().codex_sandbox == CODEX_SANDBOX_UNSANDBOXED
    sandbox_decision = resolve_agent_sandbox_decision(
        event=gh_event,
        event_name=event_name,
        config_root=repo_root,
        settings_snapshot=snapshot,
        head_sha=bound_head_sha(gh_event, event_name=event_name) or "unknown",
        default_branch=default_branch_from_event(gh_event),
        operator_override_requested=operator_override_requested,
    )

    trust_tier = policy.execution_trust
    authority_trust = policy.authority_trust
    ctx.trust_tier = trust_tier
    ctx.authority_trust = authority_trust
    ctx.trust_self_review_level = policy.level
    ctx.tool_state.trust_tier = trust_tier
    ctx.tool_state.authority_trust = authority_trust
    ctx.tool_state.trust_self_review_level = policy.level
    ctx.tool_state.agent_sandbox_decision = sandbox_decision
    ctx.tool_state.run_manifest_trust = {
        **trust_policy_manifest_fields(policy),
        **agent_sandbox_manifest_fields(sandbox_decision),
    }

    assert ctx.settings is not None
    from mergecraft.config.settings import (
        apply_trust_tier_to_repo_settings,
    )

    event_name = os.environ.get("GITHUB_EVENT_NAME", "unknown")
    settings, drops = apply_trust_tier_to_repo_settings(
        ctx.settings,
        trust_tier,
        source_label=f"{event_name} event",
    )
    ctx.settings = settings
    from mergecraft.review.pipeline.prep import bind_filtered_execution_settings

    skip_reason = bind_filtered_execution_settings(settings, trust_tier, drops)
    if skip_reason:
        ctx.setup_script_skip_reason = skip_reason
        ctx.tool_state.setup_script_skip_reason = skip_reason
    return settings


async def _bind_action_event(ctx: RunContext, *, event_name: str) -> dict[str, Any]:
    """Bind comment and dispatch events to their target PR before trust resolution."""
    assert ctx.tool_state is not None
    assert ctx.scm is not None
    assert ctx.run_context is not None
    from mergecraft.config.trust_policy import (
        bind_dispatch_review_prompt,
        bind_target_pull_request,
        unbound_target_pull_number,
    )

    gh_event = ctx.gh_event or {}

    # F1 (TB-D1) — the live dispatch review path composes "Review pull request
    # #<n>. …" into the Action's ``prompt`` input, so ``github.event.inputs.prompt``
    # holds only the operator's raw input (usually empty). Merge the composed prompt
    # into the event before the first trust read so a dispatch that names a PR is
    # floored as a fork until ``get_pull`` binds it — exactly as a comment-on-PR run
    # is. A dispatch that names no PR (and every non-dispatch event) is unchanged.
    gh_event = bind_dispatch_review_prompt(
        gh_event,
        event_name=event_name,
        prompt=_composed_prompt_from_payload(ctx),
    )
    ctx.gh_event = gh_event

    # TB-D2 — bind the target PR by fetching, once, before the first trust read.
    # A comment on a PR (`issue.pull_request`, no head) and a `workflow_dispatch`
    # that names a PR carry no head, so their fork status is unknown until the
    # SCM API answers. Fetch here and replace ``ctx.gh_event`` with the bound
    # event so the credential invariant, the trust policy and the sandbox
    # decision all read one bound event. A fetch failure leaves the event
    # unbound — floored as a fork — and is warned, never raised; the invariant
    # below turns that into a refusal when credentials are present (P-8).
    unbound_pull = unbound_target_pull_number(gh_event)
    if unbound_pull is not None:
        try:
            pull = await ctx.scm.get_pull(
                ctx.run_context.repo.owner, ctx.run_context.repo.name, unbound_pull
            )
        except Exception as exc:
            logger.warning(
                "could not bind pull request #{} for this run; leaving it unbound "
                "so the fork floor applies: {}",
                unbound_pull,
                exc,
            )
        else:
            _remember_pull_request(
                ctx, ctx.run_context.repo.owner, ctx.run_context.repo.name, unbound_pull, pull
            )
            gh_event = bind_target_pull_request(gh_event, pull)
            ctx.gh_event = gh_event
            # Dispatch events carry no PR number during setup. Keep the run and
            # tool state in sync with the fetched PR before reading its issues.
            bound_pull_number = pull.get("number")
            if isinstance(bound_pull_number, int):
                ctx.pr_number = bound_pull_number
                ctx.tool_state.pr_number = bound_pull_number
    return gh_event
