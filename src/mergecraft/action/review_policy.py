"""Apply Action triage and approval policy."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.action.reapproval_recheck import run_deterministic_recheck
from mergecraft.action.review_state import LiteAgentReview, SkipAgentReview
from mergecraft.agents.lite import LiteOutcome, lite_model_slug, run_lite_review
from mergecraft.ci.sarif_ingest import (
    record_unverified_red_green,
)
from mergecraft.classify.triage import TriageDecision
from mergecraft.fast_path import load_triage_inputs, triage_pull_request
from mergecraft.review_policy.ignore_paths import INPUT_ENV as IGNORE_PATHS_INPUT_ENV
from mergecraft.review_policy.ignore_paths import list_pull_request_paths, resolve_review_ignore
from mergecraft.utils import gha_log

if TYPE_CHECKING:
    from mergecraft.action.review_state import RunContext
    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.tool_state import (
        ToolState,
    )
    from mergecraft.run_outcome import (
        CompletionConclusion,
    )


def _is_completed_review(review: dict[str, Any]) -> bool:
    """Recognize already-authenticated history for frequency, never approval."""
    import re

    from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, REVIEW_BODY_MARKER

    commit = review.get("commit_id")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-fA-F]{40}", commit) is None:
        return False
    state = str(review.get("state")).upper()
    if state in {"APPROVED", "CHANGES_REQUESTED"}:
        return True
    if state != "COMMENTED":
        return False
    body = str(review.get("body") or "").lstrip()
    if not body.startswith(f"{DETERMINISTIC_RECORD_MARKER}\n### mergeCraft run record\n"):
        return False
    record, separator, _prose = body.partition(REVIEW_BODY_MARKER)
    if not separator:
        return False
    header, boundary, _pre_merge = record.partition("\n### Pre-merge checks\n")
    lines = header.splitlines()
    if not boundary or len(lines) < 6:
        return False
    if "- **Publication path:** `publish_pull_request_review`" not in lines or any(
        line.startswith(("- **Tier:** skip", "- **Tier:** lite")) for line in lines
    ):
        return False
    # The renderer writes these fields before any variable record content.
    outcome, diagnostic, decision = lines[3:6]
    return (
        outcome == "- **Outcome:** `passed`"
        and diagnostic == "- **Verdict diagnostic:** `approved`"
        and decision.startswith("- **Decision:** `success` — ")
    )


async def _reapproval_gate(
    ctx: RunContext, pull_number: int, head_sha: str
) -> SkipAgentReview | None:
    """Carry a trusted prior pass over to this head when the reviewed change is intact (#1284).

    Returns ``SkipAgentReview`` when :func:`mergecraft.reapproval.evaluate_reapproval`
    proves the prior pass applies, and records the ``skip`` / ``reapproval`` tier and
    its record so the checks publish the reused verdict on this exact head. ``None``
    otherwise: the normal triage and review run. Either way the run's review stamp
    (pull request, target branch, review-policy digest) is recorded, so this run's own
    approval check can seed a later re-approval.

    A proof made under a changed review policy (``record.policy_changed``) carries
    over only after :func:`run_deterministic_recheck` ran the analyzers and static
    checks clean on this head; otherwise the normal review runs.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    assert ctx.tool_context is not None
    from mergecraft import __version__
    from mergecraft.build_metadata import resolve_action_pin_sha
    from mergecraft.classify.reapproval import APPROVAL_CHECK_NAME, REAPPROVAL_RECOGNIZER
    from mergecraft.mcp.checkout import list_mergecraft_reviews
    from mergecraft.reapproval import evaluate_reapproval, workflow_path_from_ref

    tool_context = ctx.tool_context
    repo = tool_context.repo

    async def _reviews() -> list[dict[str, Any]]:
        return await list_mergecraft_reviews(tool_context, pull_number=pull_number)

    outcome = await evaluate_reapproval(
        tool_context.scm,
        repo.owner,
        repo.name,
        pull_number,
        head_sha,
        config=ctx.settings.review.fast_path.reapproval,
        list_reviews=_reviews,
        workflow_path=workflow_path_from_ref(os.environ.get("GITHUB_WORKFLOW_REF")),
        version=__version__,
        action_pin=resolve_action_pin_sha(),
    )
    ctx.tool_state.review_stamp = outcome.stamp
    record = outcome.verdict.record
    if record is None:
        logger.info("» re-approval: normal review — {}", outcome.verdict.reason)
        return None
    if record.policy_changed:
        recheck = await run_deterministic_recheck(
            tool_context, pull_number=pull_number, head_sha=head_sha
        )
        if not recheck.clean:
            logger.info(
                "» re-approval: normal review — the review policy changed and {}",
                recheck.reason,
            )
            return None
        record = replace(record, rechecked=recheck.ran)
    ctx.tool_state.reapproval = record
    decision = TriageDecision(
        tier="skip",
        recognizer=REAPPROVAL_RECOGNIZER,
        reason=record.reason(),
        relied_on_checks=(f"{APPROVAL_CHECK_NAME}@{record.prior_head_sha}",),
    )
    ctx.tool_state.triage = decision
    logger.warning("» {} — {}", decision.record_line(), decision.reason)
    gha_log.notice(f"mergeCraft: {decision.reason} (prior review: {record.prior_url})")
    return SkipAgentReview(reason=decision.reason)


def _lite_finding_rows(outcome: LiteOutcome) -> list[dict[str, Any]]:
    """Compact ``lite`` rows for the packet, so a lite blocker reaches the gate.

    :func:`mergecraft.evidence.merge.lite_row_finding` expands them into findings.
    """
    from mergecraft.evidence.merge import LITE_FINDING_TOOL

    return [
        {
            "tool": LITE_FINDING_TOOL,
            "rule_id": "lite-review",
            "severity": item["severity"],
            "path": item["path"],
            "line": item["line"],
            "message": item["message"],
        }
        for item in outcome.findings
    ]


def _skip_without_review_diff(
    ctx: RunContext, skip: SkipAgentReview | LiteAgentReview
) -> SkipAgentReview | LiteAgentReview:
    """A run without the agent has no review diff, so a declared receipt is unverified.

    Both a ``skip`` tier and a ``lite`` tier leave the pull request unchecked out:
    neither writes the review diff the untouched-workflow check needs, so the
    fail-then-pass receipt cannot be verified on either path.
    """
    if ctx.tool_context is not None:
        reason = (
            skip.reason
            if isinstance(skip, SkipAgentReview)
            else f"lite tier: {skip.decision.reason}"
        )
        record_unverified_red_green(ctx.tool_context, reason=f"the agent did not run ({reason})")
    return skip


def _lite_completion_conclusion(
    tool_state: ToolState, prepared: Any, *, outcome_conclusion: CompletionConclusion
) -> tuple[CompletionConclusion, str | None] | None:
    """The ``mergecraft`` check for a ``lite`` run, and the lead its summary states.

    ``None`` when the run was not a ``lite`` run. A Critical or Major finding fails the
    check whatever else happened (a cap overrun never softens a blocker); otherwise a
    clean completion is ``neutral``, never ``success``, because a lite call is triage,
    not a review. Any other outcome conclusion (``neutral`` for ``inconclusive``,
    ``failure``) is kept.
    """
    triage = tool_state.triage
    if tool_state.lite_review is None or getattr(triage, "tier", None) != "lite":
        return None
    from mergecraft.agents.gates import blocking_findings

    blockers = blocking_findings(list(getattr(prepared, "findings", None) or []))
    if blockers and outcome_conclusion in {"success", "neutral"}:
        noun = "finding" if len(blockers) == 1 else "findings"
        return "failure", f"The lite review raised {len(blockers)} blocking {noun}."
    if outcome_conclusion == "success":
        return "neutral", "The lite review finished; approval is left to a human."
    return outcome_conclusion, None


def _lite_inconclusive_reason(outcome: LiteOutcome) -> str | None:
    """Why a ``lite`` run is ``inconclusive``: a failed call, or usage over the cap."""
    if outcome.status == "failed":
        return f"the lite review failed: {outcome.reason}"
    if outcome.cap_hit:
        return (
            f"the lite review used {outcome.tokens_used} tokens, over its cap; "
            "its result is not trusted"
        )
    return None


_IGNORE_SKIP_EVENTS: frozenset[str] = frozenset({"pull_request", "pull_request_target"})


async def _run_draft_lite(ctx: RunContext) -> SkipAgentReview | LiteAgentReview:
    """Run the capped draft review or stop without escalating to a full review."""
    assert ctx.draft_lite_settings is not None
    assert ctx.tool_context is not None
    assert ctx.tool_state is not None
    settings = ctx.draft_lite_settings
    lite = settings.review.fast_path.lite
    unavailable = SkipAgentReview(
        reason="Draft lite review skipped: a capped call was unavailable."
    )
    if not lite.enabled or lite_model_slug(settings) is None:
        return unavailable

    from mergecraft.config.trust_policy import bound_head_sha
    from mergecraft.fast_path import _read_diff
    from mergecraft.mcp.tool_state import primary_repo_state
    from mergecraft.review_policy.ignore_paths import _event_base_sha

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    head_sha = bound_head_sha(ctx.gh_event or {}, event_name=event_name)
    pull_number = ctx.tool_context.payload.event.issue_number
    base_sha = _event_base_sha(ctx.gh_event)
    if not head_sha or not base_sha or not isinstance(pull_number, int):
        return SkipAgentReview(reason="Draft lite review skipped: no bound pull request revision.")
    scm, repo = ctx.tool_context.scm, ctx.tool_context.repo
    number = pull_number

    async def revision_matches() -> bool:
        pull = await scm.get_pull(repo.owner, repo.name, number)
        event = {"pull_request": pull}
        return (
            bound_head_sha(event, event_name=event_name).casefold() == head_sha.casefold()
            and _event_base_sha(event).casefold() == base_sha.casefold()
        )

    changed = SkipAgentReview(
        reason="Draft lite review skipped: the pull request revision changed."
    )
    try:
        if not await revision_matches():
            return changed
        diff, _paths = await _read_diff(scm, repo.owner, repo.name, number)
        if not await revision_matches():
            return changed
    except Exception as exc:
        logger.info("Draft lite diff unavailable ({})", type(exc).__name__)
        return SkipAgentReview(
            reason="Draft lite review skipped: the pull request diff is unavailable."
        )
    decision = TriageDecision(
        tier="lite",
        recognizer=None,
        reason=ctx.automatic_review_reason,
        token_cap=lite.token_cap,
    )
    primary_repo_state(ctx.tool_state).checkout_sha = head_sha
    ctx.tool_state.triage = decision
    result = await _run_lite_tier(ctx, decision, diff_text=diff, draft_settings=settings)
    return result or unavailable


async def _triage_gate(ctx: RunContext) -> SkipAgentReview | LiteAgentReview | None:
    """Deterministic pre-dispatch triage (``review.fastPath``): skip the agent when certain.

    Returns ``SkipAgentReview`` for a ``skip`` tier and ``LiteAgentReview`` for a
    ``lite`` tier whose single capped call ran (``reviewed`` or ``failed``). A ``lite``
    call the driver ``downgraded`` (over the cap, no credential) returns ``None`` and
    records a ``full`` decision carrying the downgrade reason, so the run gets the
    normal review. Off by default; the config is honoured only when it is the
    operator's base-side config. The pull request is read once, and the ``lite``
    driver gets exactly the diff the decision was made from. The decision is
    recorded on the run (packet, check summaries, shadow log) whenever the gate was
    evaluated, and any doubt is ``full``. The PR's title, body, labels and head-side
    config are never read. With ``review.fastPath.reapproval`` enabled, the
    re-approval proof (:func:`_reapproval_gate`) runs first and may return a
    ``SkipAgentReview`` that carries a trusted prior pass over to this head.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    config = ctx.settings.review.fast_path
    if not config.enabled:
        return None
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    pull = event.get("pull_request")
    if not isinstance(pull, dict) or not isinstance(pull.get("number"), int):
        return None
    head = pull.get("head")
    head_sha = str(head.get("sha") or "") if isinstance(head, dict) else ""
    assert ctx.tool_context is not None
    repo = ctx.tool_context.repo
    if config.reapproval.enabled and ctx.settings_snapshot_operator_owned:
        reapproved = await _reapproval_gate(ctx, int(pull["number"]), head_sha)
        if reapproved is not None:
            return reapproved
    decision, inputs = await triage_pull_request(
        ctx.tool_context.scm,
        repo.owner,
        repo.name,
        int(pull["number"]),
        head_sha,
        config=config,
        operator_owned=ctx.settings_snapshot_operator_owned,
        loader=load_triage_inputs,
        instruction_extra_filenames=ctx.settings.review.instruction_extra_filenames,
    )
    ctx.tool_state.triage = decision
    if decision.tier == "lite" and inputs is not None:
        return await _run_lite_tier(ctx, decision, diff_text=inputs.diff_text)
    if decision.tier != "skip":
        return None
    logger.warning("» {} — {}", decision.record_line(), decision.reason)
    gha_log.warning(decision.record_line())
    return SkipAgentReview(reason=decision.reason)


async def _run_lite_tier(
    ctx: RunContext,
    decision: TriageDecision,
    *,
    diff_text: str,
    draft_settings: RepoSettings | None = None,
) -> LiteAgentReview | None:
    """Run the ``lite`` tier's single call; ``None`` (a full review) when it downgraded.

    Findings are recorded twice. The checks fail through the packet findings: compact
    ``tool="lite"`` rows on ``agent_findings``, which
    :func:`mergecraft.evidence.merge.lite_row_finding` expands, so a Critical or Major
    one fails the checks like any review finding. The roster record
    (``record_reviewer_dispatch_run(agent_id="lite")``) is kept separately as the
    provenance of who raised them. The driver is reached through this module's
    ``run_lite_review`` binding.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    tool_state = ctx.tool_state
    settings = draft_settings if draft_settings is not None else ctx.settings
    try:
        outcome = await run_lite_review(decision=decision, diff_text=diff_text, settings=settings)
    except Exception as err:  # the driver is total; a bug in it must not crash the run
        logger.warning("» lite review raised {}: the run is inconclusive", type(err).__name__)
        outcome = LiteOutcome(
            status="failed", reason=f"the lite review raised {type(err).__name__}"
        )
    if draft_settings is not None and outcome.status == "failed":
        return None
    if outcome.status == "downgraded":
        if draft_settings is None:
            tool_state.triage = TriageDecision(tier="full", recognizer=None, reason=outcome.reason)
            logger.warning("» Tier: full — lite downgraded: {}", outcome.reason)
        return None
    model_slug = outcome.model_slug or lite_model_slug(settings)
    if outcome.model_slug is None and model_slug is not None:
        outcome = replace(outcome, model_slug=model_slug)
    tool_state.lite_review = outcome
    if outcome.findings:
        from mergecraft.mcp.tool_state import record_reviewer_dispatch_run

        rows = [dict(finding) for finding in outcome.findings]
        record_reviewer_dispatch_run(
            tool_state, agent_id="lite", findings=rows, model_slug=model_slug
        )
        tool_state.agent_findings.extend(_lite_finding_rows(outcome))
    logger.warning("» {} — {} ({})", decision.record_line(), outcome.reason, outcome.status)
    gha_log.warning(decision.record_line())
    return LiteAgentReview(decision=decision, outcome=outcome)


async def _same_head_skip_gate(ctx: RunContext) -> SkipAgentReview | None:
    """Skip the agent when this exact head SHA already has a trusted completed review (#1490)."""
    assert ctx.tool_state is not None
    assert ctx.tool_context is not None
    from mergecraft.config.trust_policy import bound_head_sha
    from mergecraft.review_policy.same_head_review import evaluate_same_head_skip

    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    pull = event.get("pull_request")
    if not isinstance(pull, dict) or not isinstance(pull.get("number"), int):
        return None
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    head_sha = bound_head_sha(event, event_name=event_name)
    if not head_sha:
        return None
    decision = await evaluate_same_head_skip(
        ctx.tool_context, head_sha=head_sha, pull_number=int(pull["number"])
    )
    if decision is None:
        return None
    ctx.tool_state.triage = decision
    logger.warning("» {} — trusted review already on this head SHA", decision.record_line())
    gha_log.notice(
        "mergeCraft: This head SHA already has a trusted review. Skipping agent dispatch."
    )
    return SkipAgentReview(reason=decision.reason)


async def _ignore_paths_gate(ctx: RunContext) -> SkipAgentReview | None:
    """Resolve review path ignoring (#1109); skip the agent when every changed file is ignored.

    The matcher is built from the ``ignore_paths`` Action input, the built-in defaults
    and ``review.ignorePaths`` read from the operator's side of the pull request only,
    and is recorded on the tool state so ``checkout_pr`` trims the reviewer's diff.
    Only a ``pull_request`` / ``pull_request_target`` run whose complete file listing is
    ignored skips the agent; it then records a ``skip`` triage tier, so the run passes
    with "nothing to review" and approval is left to a human. Any doubt reviews.
    """
    assert ctx.settings is not None
    assert ctx.tool_state is not None
    assert ctx.tool_context is not None
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    repo = ctx.tool_context.repo
    try:
        ignore = await resolve_review_ignore(
            ctx.tool_context.scm,
            repo.owner,
            repo.name,
            event=event,
            run_start_review=ctx.settings.review,
            operator_owned=ctx.settings_snapshot_operator_owned,
            input_value=os.environ.get(IGNORE_PATHS_INPUT_ENV),
        )
    except Exception as err:  # path ignoring is an optimisation; failing it reviews everything
        logger.warning("ignore_paths: could not resolve the matcher, reviewing every file: {}", err)
        return None
    ctx.tool_state.review_ignore = ignore
    logger.info(
        "ignore_paths: {} glob(s), generated defaults {}, config from {}",
        len(ignore.patterns),
        "on" if ignore.generated_defaults else "off",
        ignore.source,
    )
    pull = event.get("pull_request")
    if not ignore.active or not isinstance(pull, dict) or not isinstance(pull.get("number"), int):
        return None
    if os.environ.get("GITHUB_EVENT_NAME", "") not in _IGNORE_SKIP_EVENTS:
        return None
    paths = await list_pull_request_paths(
        ctx.tool_context.scm, repo.owner, repo.name, int(pull["number"])
    )
    if not paths:
        return None
    kept, ignored = ignore.partition(paths)
    if kept:
        return None
    reason = f"nothing to review: all {len(ignored)} changed file(s) are ignored by config"
    ctx.tool_state.ignored_review_paths = ignored
    ctx.tool_state.triage = TriageDecision(tier="skip", recognizer="ignorePaths", reason=reason)
    logger.warning("» {} — {}", ctx.tool_state.triage.record_line(), reason)
    gha_log.notice(f"mergeCraft: {reason}")
    return SkipAgentReview(reason=reason)
