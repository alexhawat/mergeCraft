"""Publish terminal reviews to GitHub and bind receipts to their run.

Module: mergecraft.mcp.review_publish
Depends: mergecraft.mcp.{inline_anchors,review_body,review_threads,tool_state}, httpx

Exports:
    Classes:
        PublicationScopeError — A publication request outside the bound PR or commit.
    Functions:
        assert_publication_scope — Refuse publication outside the bound PR or commit.
        bound_commit_id — Read the bound checkout SHA.
        create_github_review_with_anchor_recovery — Post with 422 and anchor recovery.
        existing_publication_response — Report an existing review for the bound head.
        publish_github_review — Prepare and post a GitHub review.
        publish_pull_request_review — Publish an already validated terminal submission.
        recover_review_after_lost_receipt — Find a review accepted before its response was lost.
        recovered_receipt — Bind a receipt to the review GitHub actually accepted.
        recovered_review_inline_comments — Read the inline comments of a recovered review.
        recovered_review_verdict — Read the verdict a recovered review proves.
        reject_mismatched_publication — Refuse a verdict different from the recorded one.
        resolve_bound_commit_id — Validate the requested target checkout SHA.
        resolve_bound_pull_number — Resolve the requested pull number against the run.
        should_publish_sticky_only — Decide when a neutral record belongs in the sticky comment.
        truncate_review_body_for_github — Cap the body at GitHub's review limit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from mergecraft.analyzers.finding import try_resolve_finding_short_ids
from mergecraft.mcp.comment import add_footer
from mergecraft.mcp.convergence_runtime import (
    collateral_by_fingerprint,
    enforce_recall_deferred_lane_at_publish,
    prepare_inline_comment_for_publish,
    recall_publish_sets,
    strip_recall_inline_comments,
)
from mergecraft.mcp.deferred_publish import (
    merge_analyzer_sections_into_review_body,
    refresh_analyzer_sections_for_publish,
)
from mergecraft.mcp.inline_anchors import (
    InlineAnchorIndex,
    adjust_inline_comment_anchor,
    append_demoted_inline_comments,
    build_inline_anchor_index,
    format_demoted_inline_comment,
    is_comments_anchor_422_response,
    parse_comment_422_index,
)
from mergecraft.mcp.review_body import (
    comment_fingerprint,
    comment_fingerprints,
    merge_review_body_with_deterministic_preamble,
    prepend_short_id,
    publish_fingerprint_batch,
    publish_fingerprint_paths,
    rebuild_review_body_with_deterministic_preamble,
)
from mergecraft.mcp.review_threads import resolve_fixed_finding_threads
from mergecraft.mcp.tool_state import ApprovalRecord, ReviewRecord, primary_repo_state
from mergecraft.mcp.verdict import ReviewPhase
from mergecraft.review_policy.ignore_paths import merge_ignored_paths_into_review_body
from mergecraft.review_resolution import finding_fingerprints_in
from mergecraft.review_taxonomy import finding_fingerprint, stamp_finding_fingerprint
from mergecraft.types import INCREMENTAL_REVIEW_MODE
from mergecraft.utils.github import github_review_request
from mergecraft.utils.learnings import (
    ensure_learnings_review_delta,
    merge_learnings_delta_into_review_body,
)

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

__all__ = [
    "ANCHOR_RECOVERY_RETRY_CEILING",
    "REVIEW_BODY_MAX_CHARS",
    "PublicationScopeError",
    "assert_publication_scope",
    "bound_commit_id",
    "create_github_review_with_anchor_recovery",
    "existing_publication_response",
    "publish_github_review",
    "publish_pull_request_review",
    "recover_review_after_lost_receipt",
    "recovered_receipt",
    "recovered_review_inline_comments",
    "recovered_review_verdict",
    "reject_mismatched_publication",
    "resolve_bound_commit_id",
    "resolve_bound_pull_number",
    "should_publish_sticky_only",
    "truncate_review_body_for_github",
]


class PublicationScopeError(ValueError):
    """A review mutation targeted a PR or commit outside the bound run scope."""


_FRESH_PR_TRIGGERS: frozenset[str] = frozenset(
    {"pull_request_opened", "pull_request_ready_for_review"}
)


def _is_rereview_trigger(trigger: str | None) -> bool:
    """Return True iff the run's trigger is a re-review (not a fresh PR).

    A re-review is any trigger that is **not** a fresh PR — synchronize,
    review_requested, review_submitted, review_comment, issue_comment, or
    similar. The trigger vocabulary is in
    ``mergecraft.utils.payload.PayloadTrigger``; the two values that
    name a fresh PR are the ones we exclude.

    Args:
        trigger: The trigger string from the run's payload event, or
            ``None`` for non-GitHub / offline runs.

    Returns:
        True when the trigger is not a fresh PR. Returns False when
        the trigger is unknown / unset — an unknown trigger is treated
        as a fresh PR so we never surface the suggestion on a run
        whose re-review status we cannot prove.
    """
    if not trigger:
        return False
    return trigger not in _FRESH_PR_TRIGGERS


def _maybe_suggest_eval_add(ctx: ToolContext) -> None:
    """Log a one-line suggestion to add the run to the eval bank (#44, W12.4).

    Fires when:

    - ``ctx.suggest_eval_add`` is True (opt-in via action input).
    - The trust tier is ``trusted`` (the suggestion is never surfaced
      on fork PRs or untrusted runs).
    - The trigger is a re-review (not a fresh PR; fresh PRs do not
      produce a *rejected / reverted* failure mode yet).
    - The run produced no positive findings.

    The function only logs — it never auto-adds. The eval bank is for
    *operator review*, not auto-capture.
    """
    if not getattr(ctx, "suggest_eval_add", False):
        return
    if ctx.authority_trust != "trusted":
        return
    trigger = ctx.payload.event.trigger
    if not _is_rereview_trigger(trigger):
        return
    # Positive signal: any analyzer finding attributed to the PR. The
    # analyzer pipeline writes into ``tool_state.analyzer_run.findings``
    # (a list of dicts); a missing or empty list means the run found
    # nothing.
    analyzer_run = getattr(ctx.tool_state, "analyzer_run", None)
    positive_findings = bool(getattr(analyzer_run, "findings", None))
    if positive_findings:
        return
    logger.info(
        "» suggest_eval_add: re-review produced no positive findings; "
        "consider capturing this run with `uv run mergecraft eval add` "
        "from a mergeCraft source checkout "
        "(never auto-added; #44, W12.4)",
    )


def _still_raised_fingerprints(
    ctx: ToolContext, *, posted: dict[str, Any], inline: list[dict[str, Any]]
) -> frozenset[str]:
    """Fingerprints this run still raises anywhere: submission, posted body, inline.

    The final inline list alone misses findings demoted to the review body (a
    422 or an anchor outside the diff) and findings deferred past the inline
    budget; their threads must stay open because the finding is still open.
    """
    raised: set[str] = set(_submission_fingerprints(ctx.tool_state.terminal_submission))
    raised |= finding_fingerprints_in(str(posted.get("body") or ""))
    for item in [*inline, *(posted.get("comments") or [])]:
        raised |= finding_fingerprints_in(str(item.get("body") or ""))
    return frozenset(raised)


def _requested_publication_verdict(params: dict[str, Any]) -> str | None:
    if bool(params.get("approved")):
        return "approve"
    if bool(params.get("request_changes")):
        return "request_changes"
    return None


def reject_mismatched_publication(submission: Any, params: dict[str, Any]) -> None:
    """Refuse a requested publication verdict that differs from the recorded verdict."""
    wanted = _requested_publication_verdict(params)
    if wanted is None or wanted == submission.verdict:
        return
    msg = f"publication {wanted} does not match recorded terminal verdict {submission.verdict}"
    raise ValueError(msg)


def _terminal_publication_body(submission: Any, params: dict[str, Any]) -> str:
    """Return the terminal submission body; refuse bare agent body overrides (D4)."""
    expected = str(submission.summary)
    supplied = params.get("body")
    if supplied is not None and str(supplied) != expected:
        msg = (
            "refusing publication: create_pull_request_review body parameter "
            "does not match terminal submission summary"
        )
        raise ValueError(msg)
    return expected


def _finding_identity(item: Any) -> str:
    """Return one terminal-submission finding's fingerprint (model or dict row)."""
    identity = getattr(item, "identity", None)
    if callable(identity):
        return str(identity()).strip()
    if isinstance(item, dict):
        explicit = str(item.get("fingerprint") or "").strip()
        if explicit:
            return explicit
        path = str(item.get("path") or "")
        body = str(item.get("body") or "")
        if path and body:
            return finding_fingerprint(path=path, body=body)
    return ""


def _submission_fingerprints(submission: Any) -> frozenset[str]:
    """Fingerprints of the recorded terminal submission's findings."""
    if submission is None:
        return frozenset()
    found = (_finding_identity(item) for item in (getattr(submission, "findings", None) or []))
    return frozenset(fingerprint for fingerprint in found if fingerprint)


def _inline_marker_fingerprints(comments: list[dict[str, Any]]) -> frozenset[str]:
    """``mergecraft-finding:v1`` markers GitHub shows in the inline comments."""
    found: set[str] = set()
    for comment in comments:
        found |= finding_fingerprints_in(str(comment.get("body") or ""))
    return frozenset(found)


def _receipt_payload_hash(verdict: str, fingerprints: frozenset[str] | set[str]) -> str:
    """Hash binding a receipt to ``(verdict, fingerprints)``.

    ``fingerprints`` are the finding markers in the published body and inline
    comments. Hashing markers rather than payload bytes keeps a review the agent
    posted itself (its own comment wording) comparable with the recorded verdict.
    """
    import hashlib

    material = verdict + "\n" + "\n".join(sorted(fingerprints))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _bound_receipt(
    result: dict[str, Any],
    *,
    posted: dict[str, Any],
    verdict: str | None,
) -> ReviewRecord:
    """Build the receipt for one accepted review from the payload GitHub accepted."""
    inline = _inline_marker_fingerprints(list(posted.get("comments") or []))
    published = inline | finding_fingerprints_in(str(posted.get("body") or ""))
    return ReviewRecord(
        id=int(result["id"]),
        node_id=str(result.get("node_id") or ""),
        reviewed_sha=posted.get("commit_id"),
        verdict=verdict,
        payload_hash=_receipt_payload_hash(verdict, published) if verdict else None,
        inline_fingerprints=tuple(sorted(inline)),
    )


def _record_publication_gap(ctx: ToolContext, review: ReviewRecord) -> list[str]:
    """Record submission findings GitHub does not show inline on ``review``.

    Only a receipt bound to a verdict whose inline set is known knows what
    GitHub shows inline; an unbound receipt, or a recovered one whose inline
    comments could not be listed (``inline_fingerprints is None``), leaves the
    recorded gap untouched rather than claiming every finding is missing.
    """
    if review.verdict is None or review.inline_fingerprints is None:
        return list(ctx.tool_state.publication_incomplete)
    submission = ctx.tool_state.terminal_submission
    missing = sorted(_submission_fingerprints(submission) - set(review.inline_fingerprints))
    ctx.tool_state.publication_incomplete = missing
    if missing:
        logger.warning(
            "review {} shows {} recorded finding(s) outside its inline comments: {}",
            review.id,
            len(missing),
            ", ".join(missing),
        )
    return missing


def _receipt_conflict_response(
    ctx: ToolContext,
    review: ReviewRecord,
    *,
    pull_number: int,
    commit_id: str,
) -> dict[str, Any] | None:
    """Return the no-second-POST response when ``review`` is not the recorded verdict.

    ``None`` when there is no recorded terminal submission, or the receipt is
    bound to the recorded verdict. Otherwise GitHub already holds a review from
    this run on ``commit_id`` and no second review is posted:

    * the receipt proves a different verdict -> ``terminal_publication_mismatch``
      is set and the response names both verdicts (VP-D5);
    * the receipt proves no verdict (a recovered review whose GitHub state is
      neither ``APPROVED`` nor ``CHANGES_REQUESTED``) -> the response says the
      recorded verdict is not proven published (``publicationUnproven``). The
      failure flag clears (a review did reach GitHub), and the run classifies
      ``inconclusive`` because a verdict-less receipt is never a receipt for the
      recorded verdict (``main_outcome._publication_outcome_inputs``).
    """
    submission = ctx.tool_state.terminal_submission
    if submission is None:
        return None
    recorded = str(submission.verdict)
    if review.verdict is None:
        from mergecraft.review.terminal_publication import (
            TerminalPublicationState,
            apply_terminal_publication_flags,
        )

        apply_terminal_publication_flags(ctx.tool_state, TerminalPublicationState.unproven_receipt)
        reason = (
            f"review {review.id} on sha {commit_id} shows neither an approval nor a change "
            f"request, so it proves no verdict; the recorded verdict {recorded} is not "
            "proven published (no second review is posted)"
        )
        logger.warning("unproven publication on PR #{}: {}", pull_number, reason)
        return {
            "success": False,
            "skipped": True,
            "published": False,
            "reason": reason,
            "reviewId": review.id,
            "recordedVerdict": recorded,
            "publicationUnproven": True,
        }
    if review.verdict != recorded:
        from mergecraft.review.terminal_publication import (
            TerminalPublicationState,
            apply_terminal_publication_flags,
        )

        apply_terminal_publication_flags(ctx.tool_state, TerminalPublicationState.verdict_mismatch)
        reason = (
            f"review {review.id} on sha {commit_id} already shows verdict {review.verdict}; "
            f"the recorded verdict {recorded} was not published (no second review is posted)"
        )
        logger.warning("publication mismatch on PR #{}: {}", pull_number, reason)
        return {
            "success": False,
            "skipped": True,
            "published": False,
            "reason": reason,
            "reviewId": review.id,
            "publishedVerdict": review.verdict,
            "recordedVerdict": recorded,
            "publicationMismatch": True,
        }
    return None


def existing_publication_response(
    ctx: ToolContext,
    *,
    pull_number: int,
    commit_id: str | None,
) -> dict[str, Any] | None:
    """Short-circuit when this run already published for ``(pull_number, commit_id)`` (D5).

    The receipt binds the verdict it published. Against the recorded terminal
    submission:

    * same verdict -> the receipt stands: no second POST, the failure flag
      clears, and any submission finding GitHub does not show inline is listed
      as ``publicationIncomplete``;
    * different verdict -> no second POST either (GitHub cannot un-publish, and
      a second review would duplicate every inline thread), but the stale
      receipt is never reported as a successful skip: the response is
      ``success: false`` naming both verdicts, and
      ``terminal_publication_mismatch`` is set.

    A receipt with no reviewed sha (the deterministic record's diagnostic
    review) never matches. A receipt on this sha that proves no verdict (a
    recovered COMMENT review) posts nothing either, but never counts as the
    recorded verdict's publication: see :func:`_receipt_conflict_response`.
    """
    review = ctx.tool_state.review
    if review is None or not commit_id or review.reviewed_sha != commit_id:
        return None
    conflict = _receipt_conflict_response(ctx, review, pull_number=pull_number, commit_id=commit_id)
    if conflict is not None:
        return conflict
    # Callers establish the current PR scope and head before reaching this
    # idempotent match. A receipt for the recorded verdict therefore resolves
    # any stale failure or mismatch state without creating a duplicate review.
    from mergecraft.review.terminal_publication import (
        TerminalPublicationState,
        apply_terminal_publication_flags,
    )

    missing = _record_publication_gap(ctx, review)
    pub_state = (
        TerminalPublicationState.published_incomplete
        if missing
        else TerminalPublicationState.published_ok
    )
    apply_terminal_publication_flags(
        ctx.tool_state,
        pub_state,
        publication_incomplete=tuple(ctx.tool_state.publication_incomplete),
    )
    response: dict[str, Any] = {
        "success": True,
        "skipped": True,
        "reason": (f"review {review.id} already submitted for sha {commit_id} this session"),
        "reviewId": review.id,
    }
    if missing:
        response["publicationIncomplete"] = missing
    return response


def _bound_pull_number(ctx: ToolContext) -> int | None:
    """Return the PR number this review run is bound to, if any.

    Uses only immutable run identity — never ``primary.issue_number``, which
    ``get_issue`` / ``get_issue_comments`` / ``get_issue_events`` may retarget.
    """
    if ctx.tool_state.pr_number is not None:
        return int(ctx.tool_state.pr_number)
    event = ctx.payload.event
    if event.is_pr and event.issue_number is not None:
        return int(event.issue_number)
    return None


def bound_commit_id(ctx: ToolContext) -> str | None:
    """Return the checkout SHA this review run is bound to, if any."""
    return primary_repo_state(ctx.tool_state).checkout_sha


def resolve_bound_pull_number(ctx: ToolContext, params: dict[str, Any]) -> int:
    """Resolve the pull number from the run and optional legacy tool arguments."""
    bound = _bound_pull_number(ctx)
    legacy = params.get("pull_number")
    if bound is None:
        if legacy is not None:
            msg = "pull_number cannot be supplied without a bound PR on this review run"
            raise ValueError(msg)
        msg = "no pull number bound to this review run"
        raise ValueError(msg)
    if legacy is not None:
        return int(legacy)
    return bound


def resolve_bound_commit_id(ctx: ToolContext, params: dict[str, Any]) -> str | None:
    """Resolve the bound checkout SHA and validate any legacy commit argument."""
    bound_sha = bound_commit_id(ctx)
    legacy = params.get("commit_id")
    if bound_sha is None:
        if legacy is not None:
            msg = "commit_id cannot be supplied without a bound checkout on this review run"
            raise ValueError(msg)
        return None
    if legacy is not None and str(legacy) != bound_sha:
        msg = (
            f"create_pull_request_review targeted commit {legacy} but this run is "
            f"bound to checkout sha {bound_sha}; refusing to publish"
        )
        raise PublicationScopeError(msg)
    return bound_sha


def assert_publication_scope(
    ctx: ToolContext,
    *,
    pull_number: int,
    commit_id: str | None = None,
) -> None:
    """Guard review mutations against a different pull request or checkout SHA."""
    bound = _bound_pull_number(ctx)
    if bound is not None and pull_number != bound:
        msg = (
            f"create_pull_request_review targeted PR #{pull_number} but this run is "
            f"bound to PR #{bound}; refusing to publish"
        )
        raise PublicationScopeError(msg)
    bound_sha = bound_commit_id(ctx)
    if commit_id is not None and bound_sha is not None and commit_id != bound_sha:
        msg = (
            f"create_pull_request_review targeted commit {commit_id} but this run is "
            f"bound to checkout sha {bound_sha}; refusing to publish"
        )
        raise PublicationScopeError(msg)


def _load_inline_anchor_index(primary: Any) -> InlineAnchorIndex | None:
    """Return anchor index from the checkout diff when ``diffPath`` is available."""
    diff_path = getattr(primary, "diff_path", None)
    if not diff_path:
        return None
    from pathlib import Path

    path = Path(str(diff_path))
    if not path.is_file():
        return None
    return _inline_anchor_index_for_diff(path.read_text(encoding="utf-8"))


def _inline_anchor_index_for_diff(diff_text: str) -> InlineAnchorIndex | None:
    """Build an anchor index when the diff carries at least one hunk."""
    index = build_inline_anchor_index(diff_text)
    if not index.hunk_ranges:
        return None
    return index


ANCHOR_RECOVERY_RETRY_CEILING = 8


def _payload_signature(payload: dict[str, Any]) -> tuple[str, int, int, int]:
    """Cheap structural signature for anchor-recovery progress checks (D1)."""
    comments = payload.get("comments") or []
    body = str(payload.get("body") or "")
    comment_body_len = sum(len(str(comment.get("body") or "")) for comment in comments)
    return (
        str(payload.get("event") or ""),
        len(body),
        len(comments),
        comment_body_len,
    )


def _demote_inline_comment_from_payload(
    payload: dict[str, Any],
    index: int,
) -> dict[str, Any] | None:
    """Move one inline comment into the review body and remove it from the payload."""
    comments = list(payload.get("comments") or [])
    if index < 0 or index >= len(comments):
        return None
    comment = comments.pop(index)
    demoted = format_demoted_inline_comment(comment)
    updated = dict(payload)
    updated["body"] = append_demoted_inline_comments(str(payload.get("body") or ""), [demoted])
    if comments:
        updated["comments"] = comments
    else:
        updated.pop("comments", None)
    return updated


def _demote_all_inline_comments(payload: dict[str, Any]) -> dict[str, Any]:
    """Demote every inline comment into the review body."""
    current = dict(payload)
    while current.get("comments"):
        demoted = _demote_inline_comment_from_payload(current, 0)
        if demoted is None:
            break
        current = demoted
    return current


# GitHub caps a pull request review body at 65536 characters (#619 Task 4c).
# The deterministic preamble plus every demoted inline comment can exceed it,
# and an over-cap body is itself a 422 — the same failure mode this whole
# recovery ladder exists to avoid.
REVIEW_BODY_MAX_CHARS = 65536
_REVIEW_BODY_TRUNCATION_MARKER = (
    "\n\n> _[mergeCraft] review body truncated — exceeded GitHub's "
    f"{REVIEW_BODY_MAX_CHARS}-character review body cap._"
)


def truncate_review_body_for_github(
    ctx: ToolContext,
    payload: dict[str, Any],
    *,
    pull_number: int,
) -> dict[str, Any]:
    """Cap ``payload['body']`` at GitHub's review-body limit, with a visible marker."""
    body = str(payload.get("body") or "")
    if len(body) <= REVIEW_BODY_MAX_CHARS:
        return payload
    marker = _REVIEW_BODY_TRUNCATION_MARKER
    from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, REVIEW_BODY_MARKER

    if body.startswith(DETERMINISTIC_RECORD_MARKER) and REVIEW_BODY_MARKER in body:
        record, prose = body.split(REVIEW_BODY_MARKER, 1)
        # The deterministic record, learnings delta and ledger markers are
        # durable state. Only free-form review prose may be shortened.
        suffix_positions = [
            position
            for token in ("\n### Learnings delta", "\n<!-- mergecraft-ledger:")
            if (position := prose.find(token)) >= 0
        ]
        suffix_at = min(suffix_positions) if suffix_positions else len(prose)
        prose, durable_suffix = prose[:suffix_at], prose[suffix_at:]
        prefix = record + REVIEW_BODY_MARKER
        keep = REVIEW_BODY_MAX_CHARS - len(prefix) - len(durable_suffix) - len(marker)
        if keep < 0:
            # The record and durable state alone are over the cap. Publishing a
            # shortened record beats publishing nothing: drop the prose and cut
            # the durable tail at a line boundary, so every marker left parses.
            logger.warning(
                "review record and durable metadata for PR #{} exceed GitHub's {}-character "
                "cap; dropping the review prose and the trailing durable rows",
                pull_number,
                REVIEW_BODY_MAX_CHARS,
            )
            durable = (prefix + durable_suffix)[: REVIEW_BODY_MAX_CHARS - len(marker)]
            boundary = durable.rfind("\n")
            shortened = (durable[:boundary] if boundary > 0 else durable) + marker
        else:
            shortened = prefix + prose[:keep] + marker + durable_suffix
    else:
        keep = max(REVIEW_BODY_MAX_CHARS - len(marker), 0)
        shortened = body[:keep] + marker
    logger.warning(
        "review body for PR #{} was {} chars, over GitHub's {}-character cap; truncating",
        pull_number,
        len(body),
        REVIEW_BODY_MAX_CHARS,
    )
    ctx.tool_state.review_body_truncated = True
    updated = dict(payload)
    updated["body"] = shortened
    return updated


def _log_review_422_payload(
    exc: httpx.HTTPStatusError,
    *,
    pull_number: int,
    event: str,
) -> None:
    """Log GitHub's redacted 422 response body at warning level (#619 Task 4a).

    ``str(exc)`` alone drops GitHub's ``errors[]`` array — the one piece of
    evidence that would have diagnosed the #619 422 loop from the run log.
    Structure-aware redaction (JSON when the body parses, text otherwise) so
    a stray secret in an echoed header cannot leak onto the log either.
    """
    from mergecraft.tracing.redaction import redact_tool_payload

    try:
        body: Any = exc.response.json()
    except ValueError:
        body = exc.response.text
    logger.warning(
        "create_review 422 on PR #{} (event={}): {}",
        pull_number,
        event,
        redact_tool_payload(body),
    )


def _last_resort_comment_payload(
    ctx: ToolContext,
    current: dict[str, Any],
    *,
    pull_number: int,
) -> dict[str, Any]:
    """Build the final COMMENT-only retry payload once normal 422 recovery is exhausted.

    #619 Task 4b — before this, an unrecovered 422 simply re-raised and the
    review was lost: the terminal verdict stayed recorded on ``ToolState``
    but never reached the Reviews tab. This is the single extra attempt
    callers make before giving up — every inline comment is dropped and
    ``event`` is forced to ``COMMENT`` (accepted unconditionally, unlike
    ``APPROVE``/``REQUEST_CHANGES``), so an unresolvable inline anchor or a
    refused review event cannot make the whole review vanish. The terminal
    submission's body is left otherwise intact.
    """
    logger.warning(
        "review publication on PR #{} exhausted normal 422 recovery; retrying once as a "
        "bare COMMENT review with no inline comments (dropping {} pending comment(s))",
        pull_number,
        len(current.get("comments") or []),
    )
    fallback = dict(current)
    fallback["event"] = "COMMENT"
    fallback.pop("comments", None)
    ctx.tool_state.review_comment_fallback_applied = True
    return fallback


async def create_github_review_with_anchor_recovery(
    ctx: ToolContext,
    *,
    pull_number: int,
    payload: dict[str, Any],
    packet: Any | None = None,
    posted: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Post a review, recovering APPROVE and inline-anchor 422 rejections (D8, #530).

    When ``posted`` is given, the payload GitHub accepted (after any demotion or
    truncation) is appended to it, so the caller can bind its receipt to what
    was actually published rather than to what it first asked for.
    """
    scm = ctx.scm
    current = dict(payload)
    approve_fallback = False
    attempt = 0
    last_resort_attempted = False

    while True:
        current = truncate_review_body_for_github(ctx, current, pull_number=pull_number)
        try:
            result = await scm.create_review(
                ctx.repo.owner,
                ctx.repo.name,
                pull_number,
                **github_review_request(current),
            )
            if posted is not None:
                posted.append(dict(current))
            return result, approve_fallback
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 422:
                raise

            event_attempted = str(current.get("event") or "COMMENT")
            _log_review_422_payload(exc, pull_number=pull_number, event=event_attempted)

            attempt += 1
            if attempt > ANCHOR_RECOVERY_RETRY_CEILING:
                if last_resort_attempted:
                    raise
                current = _last_resort_comment_payload(ctx, current, pull_number=pull_number)
                last_resort_attempted = True
                continue

            if current.get("comments") and is_comments_anchor_422_response(exc.response):
                index = parse_comment_422_index(exc.response)
                prior_sig = _payload_signature(current)
                comments = list(current.get("comments") or [])

                if index is None:
                    logger.warning(
                        "review comment 422 on PR #{} without index; demoting all inline comments",
                        pull_number,
                    )
                    current = _demote_all_inline_comments(current)
                    ctx.tool_state.review_inline_comments_demoted = True
                elif index < 0 or index >= len(comments):
                    logger.warning(
                        "review comment 422 on PR #{} at out-of-range index {} "
                        "(comment count {}); demoting all inline comments",
                        pull_number,
                        index,
                        len(comments),
                    )
                    current = _demote_all_inline_comments(current)
                    ctx.tool_state.review_inline_comments_demoted = True
                else:
                    logger.warning(
                        "review comment 422 on PR #{} at index {}; demoting inline comment to body",
                        pull_number,
                        index,
                    )
                    demoted = _demote_inline_comment_from_payload(current, index)
                    current = (
                        demoted if demoted is not None else _demote_all_inline_comments(current)
                    )
                    ctx.tool_state.review_inline_comments_demoted = True

                if packet is not None:
                    current = dict(current)
                    current["body"] = add_footer(
                        ctx,
                        rebuild_review_body_with_deterministic_preamble(
                            ctx,
                            body=str(current.get("body") or ""),
                            packet=packet,
                        ),
                    )

                if _payload_signature(current) == prior_sig:
                    logger.error(
                        "anchor recovery on PR #{} made no progress after attempt {} "
                        "(signature unchanged: event/body_len/comments_len/comment_body_len={})",
                        pull_number,
                        attempt,
                        prior_sig,
                    )
                    if last_resort_attempted:
                        raise exc
                    current = _last_resort_comment_payload(ctx, current, pull_number=pull_number)
                    last_resort_attempted = True
                continue

            event = str(current.get("event") or "COMMENT")
            if event == "APPROVE":
                prior_sig = _payload_signature(current)
                logger.info(
                    "APPROVE review rejected with 422 on PR #{}; falling back to COMMENT",
                    pull_number,
                )
                current = dict(current)
                current["event"] = "COMMENT"
                approve_fallback = True
                if _payload_signature(current) == prior_sig:
                    logger.error(
                        "anchor recovery on PR #{} made no progress after attempt {} "
                        "(signature unchanged: event/body_len/comments_len/comment_body_len={})",
                        pull_number,
                        attempt,
                        prior_sig,
                    )
                    if last_resort_attempted:
                        raise exc
                    current = _last_resort_comment_payload(ctx, current, pull_number=pull_number)
                    last_resort_attempted = True
                continue

            # Not a comments-anchor 422 and not an APPROVE rejection — every
            # targeted recovery has been tried. #619 Task 4b: one last resort
            # (bare COMMENT, no inline comments) before giving up entirely.
            if last_resort_attempted:
                raise
            current = _last_resort_comment_payload(ctx, current, pull_number=pull_number)
            last_resort_attempted = True


async def recover_review_after_lost_receipt(
    ctx: ToolContext, *, pull_number: int, commit_id: str | None
) -> dict[str, Any] | None:
    """Find a review GitHub accepted before its response was lost."""
    from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, is_trusted_sticky_author
    from mergecraft.utils.status_checks import github_run_url

    run_url = github_run_url(ctx)
    if not run_url:
        return None
    for page in range(1, 11):
        reviews = await ctx.scm.list_reviews(
            ctx.repo.owner,
            ctx.repo.name,
            pull_number,
            params={"per_page": 100, "page": page},
        )
        for review in reviews:
            body = str(review.get("body") or "")
            reviewed_commit = str(review.get("commit_id") or "")
            if (
                is_trusted_sticky_author(review)
                and body.lstrip().startswith(DETERMINISTIC_RECORD_MARKER)
                and f"- **Run:** {run_url}" in body
                and (not commit_id or not reviewed_commit or reviewed_commit == commit_id)
            ):
                return review
        if len(reviews) < 100:
            break
    return None


_REVIEW_STATE_VERDICTS: dict[str, str] = {
    "APPROVED": "approve",
    "CHANGES_REQUESTED": "request_changes",
}


def recovered_review_verdict(review: dict[str, Any]) -> str | None:
    """The verdict a recovered review's GitHub state proves, or ``None``.

    Only ``APPROVED`` and ``CHANGES_REQUESTED`` prove a verdict. ``COMMENTED``
    (including an approve that fell back to COMMENT) or a missing state proves
    none: the recovered review cannot show which verdict it carried.
    """
    return _REVIEW_STATE_VERDICTS.get(str(review.get("state") or "").strip().upper())


async def recovered_review_inline_comments(
    ctx: ToolContext, *, pull_number: int, review_id: int
) -> list[dict[str, Any]] | None:
    """List the recovered review's inline comments, or ``None`` when unreadable.

    ``None`` (never ``[]``) on any failure, a non-list page, or a listing cut by
    the page cap: an unknown inline set must not read as "GitHub shows no
    finding inline".
    """
    from mergecraft.mcp.list_pages import collect_list_pages

    endpoint = (
        f"/repos/{ctx.repo.owner}/{ctx.repo.name}/pulls/{pull_number}/reviews/{review_id}/comments"
    )

    async def _page(params: dict[str, Any]) -> list[Any]:
        raw = await ctx.scm.get(endpoint, params=params)
        if not isinstance(raw, list):
            msg = f"unexpected {type(raw).__name__} page"
            raise TypeError(msg)
        return raw

    try:
        listing = await collect_list_pages(_page, label=f"review {review_id} inline comments")
    except Exception as exc:
        logger.warning(
            "could not list inline comments of recovered review {} on PR #{}: {}",
            review_id,
            pull_number,
            exc,
        )
        return None
    if listing.incomplete:
        return None
    return listing.rows


async def recovered_receipt(
    ctx: ToolContext,
    review: dict[str, Any],
    *,
    pull_number: int,
    commit_id: str | None,
) -> ReviewRecord:
    """Bind a recovered review's receipt from what GitHub shows, never the unsent payload.

    ``verdict`` comes from the review's state (:func:`recovered_review_verdict`).
    Fingerprints come from the review's body markers plus its listed inline
    comments. When the inline comments cannot be listed, ``inline_fingerprints``
    is ``None`` and ``payload_hash`` stays unset: the fingerprint set is unknown.
    ``reviewed_sha`` is the review's own ``commit_id``, falling back to the head
    the recovery searched for, so a later publish still finds this receipt and
    posts no duplicate.
    """
    review_id = int(review["id"])
    verdict = recovered_review_verdict(review)
    comments = await recovered_review_inline_comments(
        ctx, pull_number=pull_number, review_id=review_id
    )
    inline = _inline_marker_fingerprints(comments) if comments is not None else None
    payload_hash: str | None = None
    if verdict is not None and inline is not None:
        published = inline | finding_fingerprints_in(str(review.get("body") or ""))
        payload_hash = _receipt_payload_hash(verdict, published)
    return ReviewRecord(
        id=review_id,
        node_id=str(review.get("node_id") or ""),
        reviewed_sha=str(review.get("commit_id") or "") or commit_id,
        verdict=verdict,
        payload_hash=payload_hash,
        inline_fingerprints=tuple(sorted(inline)) if inline is not None else None,
    )


def _finding_rows_for_provenance(ctx: ToolContext) -> list[dict[str, Any]]:
    """Collect finding rows for provenance display, including terminal submission."""
    rows = [row for row in ctx.tool_state.iter_finding_rows() if isinstance(row, dict)]
    submission = ctx.tool_state.terminal_submission
    if submission is None:
        return rows
    seen_fingerprints = {
        str(row.get("fingerprint") or "").strip()
        for row in rows
        if str(row.get("fingerprint") or "").strip()
    }
    for item in submission.findings:
        if hasattr(item, "model_dump"):
            row = item.model_dump()
        elif isinstance(item, dict):
            row = item
        else:
            continue
        if not isinstance(row, dict):
            continue
        fingerprint = str(row.get("fingerprint") or "").strip()
        if fingerprint and fingerprint in seen_fingerprints:
            continue
        rows.append(row)
        if fingerprint:
            seen_fingerprints.add(fingerprint)
    return rows


def _raised_by_lookup_key(row: dict[str, Any]) -> str | None:
    """Map a finding row to the key used for inline-comment provenance lookup."""
    fingerprint = str(row.get("fingerprint") or "").strip()
    if fingerprint:
        return fingerprint
    from mergecraft.review.finding_key import finding_key

    path, body, line = finding_key(row)
    if not path and not body:
        return None
    return f"{path}:{line}:{body}"


def should_publish_sticky_only(packet: Any) -> bool:
    """Return whether this rung must keep its neutral record off the formal review (#1078).

    ``MERGECRAFT_STICKY_ONLY_NEUTRAL`` is set by the workflow on a rung that a
    later fallback rung will replace when its decision is neutral (the
    OpenCode Go -> Codex edge). Without verifiable authorship (#1029) that
    later rung cannot supersede an earlier formal review, so the earlier
    neutral rung records its run in the sticky progress comment only. A
    non-neutral decision always publishes normally: ``failure`` needs a
    blocking formal review, and ``success`` is terminal.
    """
    from mergecraft.config.env import ReviewEnv

    enabled = (ReviewEnv().sticky_only_neutral or "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False
    decision = getattr(packet, "decision", None)
    if decision is None or getattr(decision, "verdict", None) != "neutral":
        return False
    # An untrusted-tier neutral is terminal by construction: the fallback chain
    # now skips Codex for it (a retry cannot change the verdict), and the Claude
    # backstop only runs on a provider failure. Sticky-only here would leave the
    # PR with no formal review at all (#1078).
    return "untrusted tier" not in str(getattr(decision, "reason", ""))


async def publish_github_review(
    ctx: ToolContext,
    params: dict[str, Any],
    *,
    entrypoint: str = "create_pull_request_review",
    run_not_passing_reason: str | None = None,
) -> dict[str, Any]:
    """Post a GitHub review after a validated terminal submission exists (V6).

    ``run_not_passing_reason`` (see :func:`publish_pull_request_review`) keeps an
    APPROVE off the pull request and skips resolving earlier finding threads.
    """
    primary = primary_repo_state(ctx.tool_state)
    pull_number = resolve_bound_pull_number(ctx, params)
    commit_id = resolve_bound_commit_id(ctx, params)
    assert_publication_scope(ctx, pull_number=pull_number, commit_id=commit_id)

    existing = existing_publication_response(
        ctx,
        pull_number=pull_number,
        commit_id=commit_id,
    )
    if existing is not None:
        ctx.tool_state.review_publication_entrypoint = entrypoint
        return existing

    ctx.tool_state.review_publication_entrypoint = entrypoint

    approved = bool(params.get("approved"))
    request_changes = bool(params.get("request_changes"))
    submission = ctx.tool_state.terminal_submission
    body: str | None
    if submission is not None:
        approved = submission.verdict == "approve"
        request_changes = submission.verdict == "request_changes"
        body = _terminal_publication_body(submission, params)
    else:
        body = params.get("body")

    comments = list(params.get("comments") or [])

    primary.issue_number = pull_number

    event = "COMMENT"
    triage_skipped = getattr(ctx.tool_state.triage, "tier", None) == "skip"
    if ctx.comment_only_review:
        # ``review_event: comment`` — an advisory reviewer. The verdict is still
        # recorded (and bound to the receipt below); only the GitHub event, the
        # part that can block or unblock a merge, stays COMMENT.
        logger.info(
            "review_event is comment: publishing the {} verdict as a COMMENT review",
            "approve" if approved else "request_changes" if request_changes else "comment",
        )
    elif (
        approved
        and ctx.pr_approve_enabled
        and run_not_passing_reason is None
        and ctx.authority_trust == "trusted"
        and not triage_skipped  # nothing was in review scope; a human approves (#1109)
    ):
        event = "APPROVE"
    elif request_changes:
        event = "REQUEST_CHANGES"

    publish_sets = recall_publish_sets(ctx)
    enforce_recall_deferred_lane_at_publish(ctx, publish_sets=publish_sets)

    from mergecraft.config.settings_snapshot import repo_settings_from_context

    review_settings = repo_settings_from_context(ctx).review

    publish_short_ids = try_resolve_finding_short_ids(
        publish_fingerprint_batch(comments, ctx),
        path_by_fingerprint=publish_fingerprint_paths(comments, ctx),
    )
    analyzer_run = ctx.tool_state.analyzer_run
    if analyzer_run is not None:
        refresh_analyzer_sections_for_publish(
            analyzer_run,
            short_ids=publish_short_ids,
            inline_comment_fingerprints=set(comment_fingerprints(comments)),
        )

    payload: dict[str, Any] = {"event": event}
    from mergecraft.evidence.run_packet import resolve_prepared_run_packet

    run_succeeded = True
    # The packet renders inside the terminal publish call, before ``mcp/rpc.py``
    # appends that call to the trajectory — name it so the trajectory audit
    # counts the in-flight terminal call as the completion signal (#1074).
    packet = resolve_prepared_run_packet(
        ctx, run_succeeded=run_succeeded, in_flight_tool=entrypoint
    )
    if should_publish_sticky_only(packet):
        # #1078 — a non-terminal neutral rung does not spend a formal review
        # the next rung cannot replace. The finalize path writes the same
        # deterministic record into the sticky progress comment.
        ctx.tool_state.review_publication_entrypoint = "sticky_only_neutral"
        ctx.tool_state.review_publication_sticky_only = True
        ctx.tool_state.was_updated = True
        logger.info(
            "decision neutral with a fallback rung available; recording this run in "
            "the sticky progress comment instead of a formal review"
        )
        return {
            "success": True,
            "published": False,
            "stickyOnly": True,
            "reason": (
                "decision neutral and a fallback rung is available; this rung's run "
                "record goes to the sticky progress comment only"
            ),
        }
    await ensure_learnings_review_delta(ctx.tool_state)
    body_with_delta = merge_learnings_delta_into_review_body(ctx.tool_state, str(body or ""))
    agent_body = merge_analyzer_sections_into_review_body(ctx, body_with_delta)
    agent_body = merge_ignored_paths_into_review_body(
        agent_body, ctx.tool_state.ignored_review_paths
    )
    if ctx.tool_state.dispatched_lens_ids:
        from mergecraft.modes import (
            merge_dispatched_lenses_into_review_metadata,
        )

        agent_body = merge_dispatched_lenses_into_review_metadata(
            agent_body,
            dispatched_lens_ids=ctx.tool_state.dispatched_lens_ids,
        )
    if commit_id:
        payload["commit_id"] = commit_id

    incremental_diff_text: str | None = None
    if ctx.tool_state.selected_mode == INCREMENTAL_REVIEW_MODE:
        incremental_path = primary.incremental_diff_path
        if incremental_path:
            from pathlib import Path

            incremental_diff_text = Path(incremental_path).read_text(encoding="utf-8")

    collateral_map = collateral_by_fingerprint(ctx)
    finding_rows = _finding_rows_for_provenance(ctx)
    from mergecraft.review.terminal_submission import should_render_finding_provenance

    show_provenance = should_render_finding_provenance(finding_rows)
    raised_by_map: dict[str, str | list[str]] = {}
    raised_by_model_map: dict[str, str] = {}
    raised_by_models_map: dict[str, dict[str, str]] = {}
    for row in finding_rows:
        lookup_key = _raised_by_lookup_key(row)
        raised = row.get("raised_by")
        if lookup_key and raised is not None:
            raised_by_map[lookup_key] = raised
        models = row.get("raised_by_models")
        if lookup_key and isinstance(models, dict) and models:
            raised_by_models_map[lookup_key] = {
                str(agent): str(model).strip()
                for agent, model in models.items()
                if str(agent).strip() and isinstance(model, str) and model.strip()
            }
            continue
        model = row.get("raised_by_model")
        if lookup_key and isinstance(model, str) and model.strip():
            raised_by_model_map[lookup_key] = model.strip()
    anchor_index = _load_inline_anchor_index(primary)
    demoted_bodies: list[str] = []

    inline: list[dict[str, Any]] = []
    for c in comments:
        path = str(c["path"])
        line = int(c["line"]) if "line" in c else None
        collateral = c.get("collateral")
        collateral_list = (
            [str(item) for item in collateral if str(item).strip()]
            if isinstance(collateral, list)
            else None
        )
        comment_body = str(c.get("body") or "")
        raw_fingerprint = comment_fingerprint(c)
        lookup_key = raw_fingerprint or _raised_by_lookup_key(
            {"path": path, "body": comment_body, "line": line or 0}
        )
        short_id = publish_short_ids.get(raw_fingerprint)
        prepared_body = prepare_inline_comment_for_publish(
            ctx,
            path=path,
            line=line,
            body=comment_body,
            collateral=collateral_list,
            fingerprint=raw_fingerprint,
            collateral_map=collateral_map,
            incremental_diff_text=incremental_diff_text,
            raised_by=raised_by_map.get(lookup_key or "") if lookup_key else None,
            show_provenance=show_provenance,
            raised_by_model=raised_by_model_map.get(lookup_key or "") if lookup_key else None,
            raised_by_models=raised_by_models_map.get(lookup_key or "") if lookup_key else None,
        )
        item: dict[str, Any] = {
            "path": path,
            "body": prepared_body,
            "fingerprint": raw_fingerprint,
        }
        if c.get("suggestion"):
            suggestion = str(c["suggestion"])
            item["body"] = (
                f"{item['body']}\n```suggestion\n{suggestion}\n```"
                if item["body"]
                else f"```suggestion\n{suggestion}\n```"
            )
        item["body"] = stamp_finding_fingerprint(
            path=item["path"],
            body=item["body"],
            fingerprint=raw_fingerprint,
        )
        if short_id:
            item["body"] = prepend_short_id(item["body"], short_id)
        if "line" in c:
            item["line"] = int(c["line"])
        if "side" in c:
            item["side"] = c["side"]
        if "start_line" in c:
            item["start_line"] = int(c["start_line"])
            item["start_side"] = c.get("start_side") or c.get("side") or "RIGHT"
        if anchor_index is not None:
            adjustment = adjust_inline_comment_anchor(item, index=anchor_index)
            if adjustment.comment is None:
                if adjustment.demoted_body:
                    demoted_bodies.append(adjustment.demoted_body)
                continue
            inline.append(adjustment.comment)
        else:
            inline.append(item)
    if review_settings.recall_pass:
        inline = strip_recall_inline_comments(ctx, inline, publish_sets=publish_sets)
    if demoted_bodies:
        ctx.tool_state.review_inline_comments_demoted = True
        agent_body = append_demoted_inline_comments(agent_body, demoted_bodies)
    from mergecraft.findings.ledger import (
        hydrate_finding_ledger_from_progress_comment,
        merge_ledger_into_comment,
        record_published_findings_in_ledger,
    )

    await hydrate_finding_ledger_from_progress_comment(ctx)
    record_published_findings_in_ledger(ctx.tool_state, inline)
    body_with_preamble = merge_review_body_with_deterministic_preamble(
        ctx,
        agent_body=agent_body,
        packet=packet,
    )
    payload["body"] = merge_ledger_into_comment(
        add_footer(ctx, body_with_preamble),
        records=ctx.tool_state.finding_ledger.records() if ctx.tool_state.finding_ledger else [],
    )
    if inline:
        payload["comments"] = inline
    else:
        payload.pop("comments", None)

    accepted_payloads: list[dict[str, Any]] = []
    try:
        recovered = (
            await recover_review_after_lost_receipt(
                ctx, pull_number=pull_number, commit_id=payload.get("commit_id")
            )
            if ctx.tool_state.terminal_publication_failed
            else None
        )
        if recovered is not None:
            result, approve_fallback = recovered, False
        else:
            result, approve_fallback = await create_github_review_with_anchor_recovery(
                ctx,
                pull_number=pull_number,
                payload=payload,
                packet=packet,
                posted=accepted_payloads,
            )
    except Exception:
        # #619 Task 3a — the terminal submission is already recorded on
        # ``ToolState`` (that happened before this function ran), but the
        # review itself never reached GitHub: every 422 recovery attempt,
        # including the last resort, failed, or GitHub refused the call for
        # some other reason entirely. ``main_outcome.py`` reads this flag to
        # map the run to ``RunOutcome.inconclusive`` instead of ``passed`` —
        # a recorded-but-unpublished verdict must never read as a clean run.
        from mergecraft.review.terminal_publication import (
            TerminalPublicationState,
            apply_terminal_publication_flags,
        )

        apply_terminal_publication_flags(ctx.tool_state, TerminalPublicationState.publish_failed)
        raise
    review_id = int(result["id"])
    if recovered is not None:
        # The create response was lost, so what this run sent is not proof of
        # what GitHub accepted: bind the receipt from the recovered review.
        receipt = await recovered_receipt(
            ctx, recovered, pull_number=pull_number, commit_id=payload.get("commit_id")
        )
        ctx.tool_state.review = receipt
        ctx.tool_state.terminal_publication_failed = False
        conflict = _receipt_conflict_response(
            ctx,
            receipt,
            pull_number=pull_number,
            commit_id=str(receipt.reviewed_sha or ""),
        )
        if conflict is not None:
            return conflict
    else:
        published_verdict = (
            str(submission.verdict)
            if submission is not None
            else _requested_publication_verdict(params)
        )
        receipt = _bound_receipt(
            result,
            posted=accepted_payloads[-1] if accepted_payloads else payload,
            verdict=published_verdict,
        )
        ctx.tool_state.review = receipt
    # Clear only after the response has yielded a parseable id and the local
    # receipt has been stored. Failed or malformed retry responses remain
    # unresolved and continue to fail closed in final outcome classification.
    from mergecraft.review.terminal_publication import (
        TerminalPublicationState,
        apply_terminal_publication_flags,
    )

    publication_gap = _record_publication_gap(ctx, receipt)
    pub_state = (
        TerminalPublicationState.published_incomplete
        if publication_gap
        else TerminalPublicationState.published_ok
    )
    apply_terminal_publication_flags(
        ctx.tool_state,
        pub_state,
        publication_incomplete=tuple(ctx.tool_state.publication_incomplete),
    )
    _maybe_suggest_eval_add(ctx)
    ctx.tool_state.approval = ApprovalRecord(
        would_approve=approved,
        sha=payload.get("commit_id"),
    )
    ctx.tool_state.was_updated = True
    logger.info("submitted review {} on PR #{}", review_id, pull_number)
    response: dict[str, Any] = {
        "success": True,
        "reviewId": review_id,
        "url": result.get("html_url"),
        "state": result.get("state"),
        "commitId": payload.get("commit_id"),
    }
    if approve_fallback:
        response["approveFallbackDueTo422"] = True
        response["requestedReviewState"] = "APPROVE"
    if ctx.tool_state.review_comment_fallback_applied:
        response["commentFallbackDueTo422"] = True
    if ctx.tool_state.review_body_truncated:
        response["bodyTruncated"] = True
    if publication_gap:
        response["publicationIncomplete"] = publication_gap
    if ctx.comment_only_review:
        # An advisory reviewer must not close threads: they may belong to the
        # reviewer whose verdict gates the merge.
        logger.info(
            "finding resolution: skipped on PR #{} because review_event is comment",
            pull_number,
        )
        resolved = 0
    elif run_not_passing_reason is not None:
        # The run will not pass (its approval, if any, was withheld): what this
        # review left out is no proof the earlier findings are fixed.
        logger.info(
            "finding resolution: skipped on PR #{} because the run does not pass: {}",
            pull_number,
            run_not_passing_reason,
        )
        resolved = 0
    else:
        resolved = await resolve_fixed_finding_threads(
            ctx,
            pull_number=pull_number,
            still_raised=_still_raised_fingerprints(
                ctx,
                posted=accepted_payloads[-1] if accepted_payloads else payload,
                inline=inline,
            ),
        )
    if resolved:
        response["resolvedThreads"] = resolved
    return response


def _comments_from_submission_findings(submission: Any) -> list[dict[str, Any]]:
    """Inline comments for the recorded findings when no agent comments are pending.

    Each finding already carries its path, line, body and fingerprint, so the
    published review shows the submission's findings inline (the publisher's
    anchor pass still re-anchors or demotes any line outside the diff).
    """
    comments: list[dict[str, Any]] = []
    for item in getattr(submission, "findings", None) or []:
        row = item.model_dump() if hasattr(item, "model_dump") else item
        if not isinstance(row, dict):
            continue
        path = str(row.get("path") or "").strip()
        body = str(row.get("body") or "")
        if not path or not body.strip():
            continue
        comment: dict[str, Any] = {"path": path, "body": body}
        fingerprint = _finding_identity(item)
        if fingerprint:
            comment["fingerprint"] = fingerprint
        line = row.get("line")
        if line is not None:
            comment["line"] = int(line)
        comments.append(comment)
    return comments


async def publish_pull_request_review(
    ctx: ToolContext, *, run_not_passing_reason: str | None = None
) -> dict[str, Any]:
    """Publish the validated terminal submission to GitHub (internal, not an MCP tool).

    ``run_not_passing_reason`` is why the run's outcome would not be ``passed``
    (resolved before publication). When set, an ``approve`` verdict is never
    posted as an APPROVE, and no earlier finding thread is resolved as fixed:
    a run that does not pass is no evidence that a finding is gone.
    """
    if ctx.tool_state.terminal_submission is None:
        msg = "no validated terminal submission available for publication"
        raise ValueError(msg)

    pull_number = _bound_pull_number(ctx)
    if pull_number is None:
        msg = "no pull number available for validated terminal submission publication"
        raise ValueError(msg)
    commit_id = bound_commit_id(ctx)
    existing = existing_publication_response(
        ctx,
        pull_number=pull_number,
        commit_id=commit_id,
    )
    if existing is not None:
        ctx.tool_state.review_publication_entrypoint = "publish_pull_request_review"
        return existing

    submission = ctx.tool_state.terminal_submission
    pending = ctx.tool_state.pending_review_publication
    if pending is not None and str(pending.get("body") or "") != str(submission.summary):
        # Agent params staged for an earlier attempt's submission (a fallback
        # recorded a new one since); they no longer describe what is published.
        pending = None
    if pending is None:
        pending = {
            "pull_number": pull_number,
            "body": submission.summary,
            "comments": _comments_from_submission_findings(submission),
            "approved": submission.verdict == "approve",
            "request_changes": submission.verdict == "request_changes",
        }
    if commit_id:
        pending = dict(pending)
        pending["commit_id"] = commit_id

    from mergecraft.mcp.review_phase_machine import advance_review_phase

    advance_review_phase(ctx.tool_state, ReviewPhase.PUBLISH)
    from mergecraft.mcp.verification import emit_published_findings

    emit_published_findings(ctx)
    result = await publish_github_review(
        ctx,
        pending,
        entrypoint="publish_pull_request_review",
        run_not_passing_reason=run_not_passing_reason,
    )
    advance_review_phase(ctx.tool_state, ReviewPhase.COMPLETE)
    return result
