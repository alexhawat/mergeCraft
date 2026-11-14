"""Render and publish the Action's deterministic review record."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import (
    ToolState,
    init_tool_state,
    loaded_review_skills_for_ledger,
)
from mergecraft.modes import compute_modes

if TYPE_CHECKING:
    from mergecraft.agents.lite import LiteOutcome
    from mergecraft.mcp.tool_state import ReviewRecord
    from mergecraft.run_outcome import (
        RunOutcome,
    )


def _publication_record_lines(tool_state: ToolState) -> list[str]:
    """Record lines naming what GitHub shows when it differs from the recorded verdict.

    A publication mismatch names both verdicts: the one GitHub shows (published
    earlier in this run) and the final recorded one, which was not published.
    A review on this head that proves no verdict (recovered after a lost create
    response, state neither approval nor change request) says the recorded
    verdict is not proven published. A same-verdict publication lists the
    recorded findings its inline comments lack, by fingerprint. Empty when the
    published review matches the record.
    """
    lines: list[str] = []
    review = tool_state.review
    submission = tool_state.terminal_submission
    if tool_state.terminal_publication_mismatch:
        published = review.verdict if review is not None and review.verdict else "unknown"
        recorded = str(submission.verdict) if submission is not None else "unknown"
        lines += [
            "",
            f"**Publication mismatch:** GitHub shows the `{published}` review this run "
            f"published earlier on this head; the final recorded verdict `{recorded}` was "
            "not published, and no second review was posted.",
        ]
    elif (
        submission is not None
        and review is not None
        and review.verdict is None
        and review.reviewed_sha is not None
    ):
        lines += [
            "",
            f"**Publication unproven:** GitHub shows a review this run published on this "
            f"head, but it is neither an approval nor a change request; the final recorded "
            f"verdict `{submission.verdict}` is not proven published, and no second review "
            "was posted.",
        ]
    elif tool_state.publication_incomplete:
        missing = sorted(tool_state.publication_incomplete)
        lines += [
            "",
            f"**Publication incomplete:** the published review does not show {len(missing)} "
            "recorded finding(s) as inline comments: "
            + ", ".join(f"`{fingerprint}`" for fingerprint in missing),
        ]
    return lines


def _record_attempt_marker(ctx: ToolContext) -> str:
    """Hidden marker naming the Actions run attempt that wrote a deterministic record."""
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "").strip() or "1"
    return f"<!-- mergecraft-record-attempt: {ctx.run_id or 'local'}:{attempt} -->"


async def publish_deterministic_record(
    *,
    pull_number: int,
    packet: Any,
    rejection_reason: str | None = None,
    tmpdir: str | None = None,
    ctx: ToolContext | None = None,
    run_outcome: RunOutcome | None = None,
    verdict_diagnostic: Any | None = None,
    approval_withheld_reason: str | None = None,
) -> None:
    """Complete the formal review with the final deterministic run record.

    ``approval_withheld_reason`` names why an ``approve`` verdict was published
    as a comment rather than an approval; the record states it.

    Plan 13 ``run_post_run_retry_loop`` routes non-retryable rejections here.
    Stable signature for cross-plan callers::

        publish_deterministic_record(
            *,
            pull_number: int,
            packet: MergeEvidencePacket,
            rejection_reason: str | None = None,
            tmpdir: str | None = None,
            ctx: ToolContext | None = None,
            run_outcome: RunOutcome | None = None,
            verdict_diagnostic: VerdictDiagnostic | None = None,
        ) -> None
    """
    import re

    from mergecraft.findings.ledger import (
        REVIEW_BODY_MARKER,
        ensure_finding_ledger,
        merge_ledger_into_comment,
    )
    from mergecraft.mcp.comment import add_footer
    from mergecraft.mcp.review import _truncate_review_body_for_github
    from mergecraft.scm.github import create_github_scm
    from mergecraft.utils.learnings import merge_learnings_delta_into_review_body
    from mergecraft.utils.status_checks import _run_url

    resolved_ctx = ctx
    if resolved_ctx is None:
        tool_state = init_tool_state(owner="local", name="local", dir=tmpdir or ".")
        tool_state.pr_number = pull_number
        resolved_ctx = ToolContext(
            agent_id="claude",
            repo=RepoIdentity(owner="local", name="local"),
            payload=ResolvedPayload(
                event=PayloadEvent(trigger="pull_request", issue_number=pull_number, is_pr=True),
            ),
            scm=create_github_scm(""),
            modes=compute_modes("claude"),
            tool_state=tool_state,
            tmpdir=tmpdir or ".",
            # No run event to derive trust from, so the record claims no trust.
            trust_tier="untrusted",
        )

    tool_state = resolved_ctx.tool_state
    block = await _render_run_record(
        resolved_ctx,
        packet=packet,
        rejection_reason=rejection_reason,
        run_outcome=run_outcome,
        verdict_diagnostic=verdict_diagnostic,
        approval_withheld_reason=approval_withheld_reason,
    )
    from mergecraft.mcp.review import should_publish_sticky_only

    if tool_state.review_publication_sticky_only or should_publish_sticky_only(packet):
        # #1078 — this rung is non-terminal (a fallback rung will replace a
        # neutral decision), so its record belongs in the sticky progress
        # comment. It must not create the formal review the publish seam
        # deliberately skipped, and must not retire the sticky as a legacy
        # record: the sticky is the record.
        from mergecraft.findings.ledger import upsert_sticky_progress_comment

        await upsert_sticky_progress_comment(resolved_ctx, block)
        return
    owner, repo = resolved_ctx.repo.owner, resolved_ctx.repo.name
    run_url = _run_url(resolved_ctx)
    attempt_marker = _record_attempt_marker(resolved_ctx)
    review, existing_body = await _recover_attempt_record(
        resolved_ctx, pull_number, run_url=run_url, attempt_marker=attempt_marker
    )

    block, legacy = await _read_legacy_progress(resolved_ctx, pull_number, block)
    legacy_body = str(legacy.get("body") or "") if legacy is not None else ""
    # Preserve the old comment's ephemeral learnings before retiring it. Its
    # run record and finding markers are rendered anew in this formal review.
    legacy_delta = re.search(
        r"### Learnings delta[\s\S]*?(?=\n<!-- mergecraft-ledger:|\n\*via mergecraft\*|\Z)",
        legacy_body,
    )
    tail = (
        existing_body.split(REVIEW_BODY_MARKER, 1)[1].strip()
        if REVIEW_BODY_MARKER in existing_body
        else ""
    )
    if legacy_delta is not None and "### Learnings delta" not in tail:
        tail = f"{tail}\n\n{legacy_delta.group(0).strip()}".strip()
    tail = merge_learnings_delta_into_review_body(tool_state, tail)
    body = f"{block.rstrip()}\n{attempt_marker}\n{REVIEW_BODY_MARKER}\n"
    if tail:
        body += f"\n{tail}\n"
    body = merge_ledger_into_comment(body, records=ensure_finding_ledger(tool_state).records())
    body = add_footer(resolved_ctx, body)
    body = str(
        _truncate_review_body_for_github(resolved_ctx, {"body": body}, pull_number=pull_number)[
            "body"
        ]
    )

    if review is not None:
        await resolved_ctx.scm.update_review(owner, repo, pull_number, review.id, body)
    else:
        # No model verdict was accepted or published. A diagnostic COMMENT
        # review records the failure without implying an approval or adding a
        # second summary-only review beside an accepted verdict.
        result = await resolved_ctx.scm.create_review(
            owner, repo, pull_number, event="COMMENT", body=body
        )
        from mergecraft.mcp.tool_state import ReviewRecord

        tool_state.review = ReviewRecord(
            id=int(result["id"]),
            node_id=str(result.get("node_id") or ""),
            reviewed_sha=None,
        )

    await _retire_legacy_progress(resolved_ctx, legacy, legacy_body)


def _action_pin_sha() -> str | None:
    from mergecraft.build_metadata import resolve_action_pin_sha

    return resolve_action_pin_sha()


def _image_source_sha() -> str | None:
    from mergecraft.build_metadata import resolve_build_commit

    return resolve_build_commit()


def _loaded_review_mcp(tool_state: ToolState) -> list[str]:
    return list(tool_state.review_mcp_names)


def _token_summary(
    usage_entries: list[Any],
    *,
    budget_tracker: Any | None = None,
) -> str | None:
    from mergecraft.utils.run_bounds import BudgetTracker, token_summary_from_usage

    tracker = budget_tracker if isinstance(budget_tracker, BudgetTracker) else None
    return token_summary_from_usage(usage_entries, budget_tracker=tracker)


def _cost_summary(
    usage_entries: list[Any],
    *,
    budget_tracker: Any | None = None,
) -> str | None:
    from mergecraft.agents.curated_model_catalog import cost_summary_from_usage_entries

    return cost_summary_from_usage_entries(usage_entries, budget_tracker=budget_tracker)


def _lite_record_summary(outcome: LiteOutcome | None) -> str | None:
    """The lite model's summary for the deterministic record, with record markers stripped.

    The full-review path strips forged or stale deterministic-record markers from
    agent prose before it is rendered; a lite summary is model output too.
    """
    from mergecraft.findings.ledger import _strip_deterministic_record_markers

    summary = getattr(outcome, "summary", None)
    if not summary:
        return None
    return _strip_deterministic_record_markers(str(summary)) or None


async def _render_run_record(
    resolved_ctx: ToolContext,
    *,
    packet: Any,
    rejection_reason: str | None,
    run_outcome: RunOutcome | None,
    verdict_diagnostic: Any | None,
    approval_withheld_reason: str | None,
) -> str:
    from mergecraft.findings.ledger import (
        hydrate_finding_ledger_from_progress_comment,
        render_deterministic_review_block,
    )
    from mergecraft.utils.status_checks import _run_url

    tool_state = resolved_ctx.tool_state
    await hydrate_finding_ledger_from_progress_comment(resolved_ctx)
    analyzer_run = tool_state.analyzer_run
    block = render_deterministic_review_block(
        packet=packet,
        rejection_reason=rejection_reason,
        run_url=_run_url(resolved_ctx),
        run_outcome=run_outcome,
        verdict_diagnostic=verdict_diagnostic,
        analyzer_summary=analyzer_run.pre_merge_summary if analyzer_run is not None else None,
        # The accepted summary already lives in the formal review body; a lite run
        # has no formal review body, so its single call's summary is the record's.
        agent_summary=_lite_record_summary(tool_state.lite_review),
        trust_tier=resolved_ctx.trust_tier,
        attempt_count=len(tool_state.usage_entries) if tool_state.usage_entries else None,
        token_summary=_token_summary(
            tool_state.usage_entries,
            budget_tracker=resolved_ctx.budget_tracker,
        ),
        cost_summary=_cost_summary(
            tool_state.usage_entries,
            budget_tracker=resolved_ctx.budget_tracker,
        ),
        llm_review_timing=tool_state.llm_review_timing,
        credential_degradations=list(tool_state.credential_degradations),
        agent_sandbox_decision=tool_state.agent_sandbox_decision,
        action_pin_sha=_action_pin_sha(),
        image_source_sha=_image_source_sha(),
        review_skills=loaded_review_skills_for_ledger(tool_state),
        review_mcp_servers=_loaded_review_mcp(tool_state),
        publication_entrypoint=tool_state.review_publication_entrypoint,
        inline_comments_demoted=tool_state.review_inline_comments_demoted,
        comment_fallback_applied=tool_state.review_comment_fallback_applied,
        review_body_truncated=tool_state.review_body_truncated,
    )
    publication_lines = _publication_record_lines(tool_state)
    if approval_withheld_reason:
        publication_lines += [
            "",
            "**Approval withheld:** the recorded verdict is `approve`, but this run did "
            f"not pass ({approval_withheld_reason}), so it was published as a comment.",
        ]
    if publication_lines:
        block = "\n".join([block.rstrip(), *publication_lines]) + "\n"
    return block


async def _recover_attempt_record(
    resolved_ctx: ToolContext, pull_number: int, *, run_url: str | None, attempt_marker: str
) -> tuple[ReviewRecord | None, str]:
    from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, _is_trusted_sticky_author

    tool_state = resolved_ctx.tool_state
    owner, repo = resolved_ctx.repo.owner, resolved_ctx.repo.name
    review = tool_state.review
    existing_body = ""
    if review is None and run_url:
        # A publish response can be lost after GitHub accepted the review.
        # Reuse the record this attempt created on this head on retry. The run
        # URL is the same on every attempt of a run, so the match also needs
        # this attempt's marker: a re-run never rewrites an earlier attempt's
        # review (which may be an approval).
        from mergecraft.mcp.tool_state import ReviewRecord, primary_repo_state

        bound_sha = primary_repo_state(tool_state).checkout_sha

        def _is_this_attempts_record(item: dict[str, Any]) -> bool:
            item_body = str(item.get("body") or "")
            item_sha = str(item.get("commit_id") or "")
            return (
                _is_trusted_sticky_author(item)
                and item_body.lstrip().startswith(DETERMINISTIC_RECORD_MARKER)
                and f"- **Run:** {run_url}" in item_body
                and attempt_marker in item_body
                and (not bound_sha or not item_sha or item_sha == bound_sha)
            )

        for page in range(1, 11):
            reviews = await resolved_ctx.scm.list_reviews(
                owner, repo, pull_number, params={"per_page": 100, "page": page}
            )
            matched = next((item for item in reviews if _is_this_attempts_record(item)), None)
            if matched is not None:
                review = ReviewRecord(
                    id=int(matched["id"]),
                    node_id=str(matched.get("node_id") or ""),
                    reviewed_sha=str(matched.get("commit_id") or "") or None,
                )
                tool_state.review = review
                break
            if len(reviews) < 100:
                break
    if review is not None:
        existing = await resolved_ctx.scm.get_review(owner, repo, pull_number, review.id)
        existing_body = str(existing.get("body") or "")
    return review, existing_body


async def _read_legacy_progress(
    resolved_ctx: ToolContext, pull_number: int, block: str
) -> tuple[str, dict[str, Any] | None]:
    from mergecraft.findings.ledger import (
        _run_bound_sticky_id,
        _run_sticky_scope,
        fetch_sticky_progress_comment,
    )
    from mergecraft.review.authorship import expected_publisher_logins

    owner, repo = resolved_ctx.repo.owner, resolved_ctx.repo.name
    # The old progress comment is read through the same rule as every other "did
    # mergeCraft post this?" decision: the run-bound comment id, then the run's
    # expected-publisher set, never a bare bot-type match. With neither, the read is
    # skipped and the record says so.
    legacy: dict[str, Any] | None = None
    if not expected_publisher_logins(resolved_ctx) and _run_bound_sticky_id(resolved_ctx) is None:
        logger.info(
            "learnings migration: earlier progress comment read skipped for PR #{} — no "
            "publisher identity and no run-bound comment id prove who wrote it",
            pull_number,
        )
        block = (
            f"{block.rstrip()}\n\n**Earlier progress comment not read:** no publisher "
            "identity proves which comment is mergeCraft's, so its learnings were not "
            "carried into this record.\n"
        )
    else:
        with _run_sticky_scope(resolved_ctx):
            legacy = await fetch_sticky_progress_comment(resolved_ctx.scm, owner, repo, pull_number)
    return block, legacy


async def _retire_legacy_progress(
    resolved_ctx: ToolContext, legacy: dict[str, Any] | None, legacy_body: str
) -> None:
    from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, _is_trusted_sticky_author

    owner, repo = resolved_ctx.repo.owner, resolved_ctx.repo.name
    tool_state = resolved_ctx.tool_state
    # Only a bot-authored legacy record may be removed, and only after the
    # formal review has accepted all of its persisted state. A contributor can
    # quote the heading and a ledger marker; body shape alone must not delete
    # that comment or copy it into the review.
    if (
        legacy is not None
        and _is_trusted_sticky_author(legacy)
        and legacy_body.startswith("## mergeCraft progress")
        and (DETERMINISTIC_RECORD_MARKER in legacy_body or "<!-- mergecraft-ledger:" in legacy_body)
    ):
        try:
            await resolved_ctx.scm.delete_issue_comment(owner, repo, int(legacy["id"]))
        except Exception as err:
            logger.warning("legacy review record could not be retired: {}", err)
        else:
            tool_state.progress_comment = False
