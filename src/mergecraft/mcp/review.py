"""create_pull_request_review tool."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from mergecraft.analyzers.finding import (
    FINDING_SHORT_ID_PREFIX,
    try_resolve_finding_short_ids,
)
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
from mergecraft.mcp.review_comments import fetch_review_threads, resolve_review_thread
from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import ApprovalRecord, ReviewRecord, primary_repo_state
from mergecraft.mcp.verdict import (
    REJECTION_REQUEST_CHANGES_NO_FINDINGS,
    ReviewPhase,
    after_terminal_submission_recorded,
    ensure_review_scope_for_terminal,
    record_validated_terminal_submission,
    recorded_submission_payload,
    revalidate_recorded_submission,
    stamp_review_phase_on_active_span,
    validate_submission,
    validation_state_from_tool_context,
)
from mergecraft.review_resolution import finding_fingerprints_in, resolvable_thread_ids
from mergecraft.review_taxonomy import (
    finding_fingerprint,
    stamp_finding_fingerprint,
)
from mergecraft.types import INCREMENTAL_REVIEW_MODE
from mergecraft.utils.learnings import (
    ensure_learnings_review_delta,
    merge_learnings_delta_into_review_body,
)

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.verdict import VerdictDiagnostic
    from mergecraft.run_outcome import RunOutcome


def merge_deterministic_preamble_into_review_body(
    *,
    agent_body: str,
    deterministic_block: str,
) -> str:
    """Prepend the server-owned deterministic record; agent copies cannot win (D7)."""
    from mergecraft.findings.ledger import (
        DETERMINISTIC_RECORD_MARKER,
        _strip_deterministic_record_markers,
    )

    cleaned_agent = _strip_deterministic_record_markers(agent_body)
    block = deterministic_block.strip()
    if not block.startswith(DETERMINISTIC_RECORD_MARKER):
        block = f"{DETERMINISTIC_RECORD_MARKER}\n{block}"
    if cleaned_agent:
        return f"{block.rstrip()}\n\n{cleaned_agent.strip()}\n"
    return f"{block.rstrip()}\n"


def _deterministic_review_block(
    ctx: ToolContext,
    *,
    packet: Any,
    rejection_reason: str | None = None,
    run_outcome: RunOutcome | None = None,
    verdict_diagnostic: VerdictDiagnostic | str | None = None,
) -> str:
    from mergecraft.findings.ledger import render_deterministic_review_block
    from mergecraft.utils.status_checks import _run_url

    tool_state = ctx.tool_state
    analyzer_run = tool_state.analyzer_run
    analyzer_summary = analyzer_run.pre_merge_summary if analyzer_run is not None else None
    submission = tool_state.terminal_submission
    agent_summary = submission.summary if submission is not None else None
    attempt_count = len(tool_state.usage_entries) if tool_state.usage_entries else None
    token_bits: list[str] = []
    for usage in tool_state.usage_entries or []:
        total = getattr(usage, "total_tokens", None)
        if total:
            token_bits.append(str(total))
    token_summary = ", ".join(token_bits) if token_bits else None
    return render_deterministic_review_block(
        packet=packet,
        rejection_reason=rejection_reason,
        run_url=_run_url(ctx),
        run_outcome=run_outcome,
        verdict_diagnostic=verdict_diagnostic,
        analyzer_summary=analyzer_summary,
        agent_summary=agent_summary,
        trust_tier=ctx.trust_tier,
        attempt_count=attempt_count,
        token_summary=token_summary,
        publication_entrypoint=tool_state.review_publication_entrypoint,
        inline_comments_demoted=tool_state.review_inline_comments_demoted,
    )


class PublicationScopeError(ValueError):
    """A review mutation targeted a PR or commit outside the bound run scope."""


def format_analyzer_inline_body(
    finding: Finding,
    *,
    short_id: str | None = None,
    effort: str = "Quick win",
    verification_note: str | None = None,
) -> str:
    """Format an analyzer-sourced inline comment with tool citation and confidence (W7.6)."""
    tag = f"_{finding.category}_ | _{finding.severity}_ | _{effort}_ | _{finding.confidence}_"
    citation = f"`{finding.tool}` `{finding.rule_id}`"
    lines: list[str] = []
    if short_id:
        lines.append(f"**{short_id}**")
    lines.extend([tag, "", f"{finding.message}", "", f"Source: {citation}."])
    if verification_note:
        lines.extend(["", verification_note.strip()])
    return "\n".join(lines)


def enrich_analyzer_comment_body(body: str) -> str:
    """Return review comment bodies unchanged (formatting is upstream)."""
    return body


_SHORT_ID_LINE_RE = re.compile(
    rf"^\*\*{re.escape(FINDING_SHORT_ID_PREFIX)}[0-9a-f]{{6,}}\*\*\s*\n?",
    re.MULTILINE,
)


def _body_without_short_id_line(body: str) -> str:
    """Strip a leading publication short-id line before content fingerprinting."""
    return _SHORT_ID_LINE_RE.sub("", body, count=1).lstrip()


def _comment_fingerprint(comment: dict[str, Any]) -> str:
    """Return the stable fingerprint for one inline comment row."""
    explicit = str(comment.get("fingerprint") or "").strip()
    if explicit:
        return explicit
    finding = comment.get("finding")
    if isinstance(finding, dict):
        nested = str(finding.get("fingerprint") or "").strip()
        if nested:
            return nested
    path = str(comment.get("path", ""))
    body = str(comment.get("body") or "")
    return finding_fingerprint(path=path, body=_body_without_short_id_line(body))


def _comment_fingerprints(comments: list[dict[str, Any]]) -> list[str]:
    return [_comment_fingerprint(comment) for comment in comments]


def _analyzer_publish_fingerprints(ctx: ToolContext) -> list[str]:
    """Return analyzer-run finding fingerprints merged into the review body."""
    analyzer_run = ctx.tool_state.analyzer_run
    if analyzer_run is None:
        return []
    fingerprints: list[str] = []
    for row in analyzer_run.findings:
        if isinstance(row, dict):
            fp = str(row.get("fingerprint", "")).strip()
            if fp:
                fingerprints.append(fp)
    return fingerprints


def _publish_fingerprint_batch(
    comments: list[dict[str, Any]],
    ctx: ToolContext,
) -> list[str]:
    """Collect inline and body-appended fingerprints for one publish batch."""
    return _comment_fingerprints(comments) + _analyzer_publish_fingerprints(ctx)


def _publish_fingerprint_paths(
    comments: list[dict[str, Any]],
    ctx: ToolContext,
) -> dict[str, str]:
    """Map each publish-batch fingerprint to a path, so a skip warning can name it."""
    paths: dict[str, str] = {}
    for comment in comments:
        fingerprint = _comment_fingerprint(comment)
        if fingerprint:
            paths.setdefault(fingerprint, str(comment.get("path") or "unknown"))
    analyzer_run = ctx.tool_state.analyzer_run
    if analyzer_run is not None:
        for row in analyzer_run.findings:
            if not isinstance(row, dict):
                continue
            fingerprint = str(row.get("fingerprint", "")).strip()
            if fingerprint:
                paths.setdefault(fingerprint, str(row.get("path") or "unknown"))
    return paths


def _body_has_short_id_line(body: str) -> bool:
    first_line = body.lstrip().split("\n", 1)[0]
    return bool(
        re.fullmatch(
            rf"\*\*{re.escape(FINDING_SHORT_ID_PREFIX)}[0-9a-f]{{6,}}\*\*",
            first_line,
        )
    )


def _prepend_short_id(body: str, short_id: str) -> str:
    """Stamp or refresh the publication short-id line with batch-resolved ``short_id``."""
    marker = f"**{short_id}**"
    if not body.strip():
        return marker
    if _body_has_short_id_line(body):
        content = _body_without_short_id_line(body)
        if content.strip():
            return f"{marker}\n\n{content}"
        return marker
    title_match = re.match(
        rf"^\*\*{re.escape(FINDING_SHORT_ID_PREFIX)}[0-9a-f]{{6,}}\*\*(\s*\([^)]+\))\s*\n?",
        body.lstrip(),
    )
    if title_match:
        rest = body.lstrip()[title_match.end() :].lstrip()
        first_line = f"{marker}{title_match.group(1)}"
        if rest:
            return f"{first_line}\n\n{rest}"
        return first_line
    return f"{marker}\n\n{body}"


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
        "consider capturing this run as a case via `mergecraft eval add` "
        "(never auto-added; #44, W12.4)",
    )


async def _resolve_fixed_finding_threads(
    ctx: ToolContext, *, pull_number: int, posted_bodies: list[str]
) -> int:
    """Close threads for findings the new commits fixed (C4).

    Runs only on a re-review that knows which paths moved since the last reviewed
    commit. A thread is closed when mergeCraft raised it, nobody else replied, its
    file was touched by the new commits, and the review just posted did not raise
    it again — i.e. the code the finding pointed at changed and the finding is
    gone. Everything here is advisory: a failure logs and the review still stands.
    """
    if ctx.tool_state.selected_mode != INCREMENTAL_REVIEW_MODE:
        return 0
    primary = primary_repo_state(ctx.tool_state)
    changed_paths = set(primary.incremental_changed_paths or ())
    if not changed_paths:
        return 0
    current: set[str] = set()
    for body in posted_bodies:
        current |= finding_fingerprints_in(body)
    try:
        threads = await fetch_review_threads(ctx, pull_number)
    except Exception as err:  # advisory cleanup; never fails a posted review
        logger.info("finding resolution: listing review threads soft-failed: {}", err)
        return 0
    targets = resolvable_thread_ids(
        threads, current_fingerprints=frozenset(current), changed_paths=changed_paths
    )
    resolved = 0
    for thread_id in targets:
        try:
            await resolve_review_thread(ctx, thread_id)
        except Exception as err:  # one bad thread must not stop the rest
            logger.info("finding resolution: resolving thread {} soft-failed: {}", thread_id, err)
            continue
        resolved += 1
    if resolved:
        logger.info(
            "resolved {} review thread(s) on PR #{} whose findings are gone from the new commits",
            resolved,
            pull_number,
        )
    return resolved


def _comments_to_findings(comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map legacy inline comments to terminal-submission finding dicts."""
    findings: list[dict[str, Any]] = []
    for comment in comments:
        path = str(comment["path"])
        body = str(comment.get("body") or "")
        row: dict[str, Any] = {
            "path": path,
            "body": body,
            "severity": "Major",
        }
        if path and body:
            row["fingerprint"] = finding_fingerprint(path=path, body=body)
        if "line" in comment:
            row["line"] = int(comment["line"])
        findings.append(row)
    return findings


def _legacy_params_to_submission(params: dict[str, Any]) -> dict[str, Any] | None:
    """Map ``create_pull_request_review`` params onto the terminal-verdict shape.

    A plain COMMENT (no ``approved`` / ``request_changes`` and no inline
    comments) is not a terminal verdict. Explicit ``approved: false`` must
    not fall through to ``approve``. ``request_changes`` with no findings
    is left empty so ``validate_submission`` can apply D9 rather than
    fabricating a ``path="."`` row.
    """
    approved = bool(params.get("approved"))
    request_changes = bool(params.get("request_changes"))
    body = str(params.get("body") or "")
    comments = list(params.get("comments") or [])

    if approved and request_changes:
        msg = "approved and request_changes are mutually exclusive"
        raise ValueError(msg)

    if approved:
        return {"verdict": "approve", "summary": body or "Approve", "findings": []}
    findings = _comments_to_findings(comments)
    if request_changes:
        return {
            "verdict": "request_changes",
            "summary": body or "Request changes",
            "findings": findings,
        }
    if findings:
        return {
            "verdict": "request_changes",
            "summary": body or "Review findings",
            "findings": findings,
        }
    if "approved" in params:
        return {
            "verdict": "request_changes",
            "summary": body or "Review comment",
            "findings": [],
        }
    return None


def _requested_publication_verdict(params: dict[str, Any]) -> str | None:
    if bool(params.get("approved")):
        return "approve"
    if bool(params.get("request_changes")):
        return "request_changes"
    return None


def _reject_mismatched_publication(submission: Any, params: dict[str, Any]) -> None:
    wanted = _requested_publication_verdict(params)
    if wanted is None or wanted == submission.verdict:
        return
    msg = f"publication {wanted} does not match recorded terminal verdict {submission.verdict}"
    raise ValueError(msg)


def _terminal_publication_body(submission: Any, params: dict[str, Any]) -> str:
    """Return the terminal submission body; refuse bare agent body overrides (D4)."""
    expected = str(submission.summary)
    supplied = params.get("body")
    if supplied is not None and str(supplied) != expected and "comments" not in params:
        msg = (
            "refusing publication: create_pull_request_review body parameter "
            "does not match terminal submission summary"
        )
        raise ValueError(msg)
    return expected


def _existing_publication_response(
    ctx: ToolContext,
    *,
    pull_number: int,
    commit_id: str | None,
) -> dict[str, Any] | None:
    """Short-circuit when this run already published for ``(pull_number, commit_id)`` (D5)."""
    review = ctx.tool_state.review
    if review is None or not commit_id or review.reviewed_sha != commit_id:
        return None
    return {
        "success": True,
        "skipped": True,
        "reason": (f"review {review.id} already submitted for sha {commit_id} this session"),
        "reviewId": review.id,
    }


def _maybe_revalidate_before_publish(ctx: ToolContext) -> None:
    """Re-run terminal validation before publish unless already graded at submit."""
    submission = ctx.tool_state.terminal_submission
    if submission is None:
        return
    if ctx.tool_state.review_phase == ReviewPhase.SUBMIT.value:
        validation = validate_submission(
            recorded_submission_payload(submission),
            state=validation_state_from_tool_context(ctx),
        )
        if (
            not validation.accepted
            and validation.rejection_reason == REJECTION_REQUEST_CHANGES_NO_FINDINGS
        ):
            return
    revalidate_recorded_submission(ctx)


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


def _bound_commit_id(ctx: ToolContext) -> str | None:
    """Return the checkout SHA this review run is bound to, if any."""
    return primary_repo_state(ctx.tool_state).checkout_sha


def _resolve_bound_pull_number(ctx: ToolContext, params: dict[str, Any]) -> int:
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


def _resolve_bound_commit_id(ctx: ToolContext, params: dict[str, Any]) -> str | None:
    bound_sha = _bound_commit_id(ctx)
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


def _assert_publication_scope(
    ctx: ToolContext,
    *,
    pull_number: int,
    commit_id: str | None = None,
) -> None:
    bound = _bound_pull_number(ctx)
    if bound is not None and pull_number != bound:
        msg = (
            f"create_pull_request_review targeted PR #{pull_number} but this run is "
            f"bound to PR #{bound}; refusing to publish"
        )
        raise PublicationScopeError(msg)
    bound_sha = _bound_commit_id(ctx)
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


def _payload_signature(payload: dict[str, Any]) -> tuple[str, int, int]:
    """Cheap structural signature for anchor-recovery progress checks (D1)."""
    comments = payload.get("comments") or []
    return (
        str(payload.get("event") or ""),
        len(str(payload.get("body") or "")),
        len(comments),
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


async def _create_github_review_with_anchor_recovery(
    ctx: ToolContext,
    *,
    pull_number: int,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Post a review, recovering APPROVE and inline-anchor 422 rejections (D8, #530)."""
    scm = ctx.scm
    current = dict(payload)
    approve_fallback = False
    attempt = 0

    while True:
        try:
            result = await scm.create_review(
                ctx.repo.owner,
                ctx.repo.name,
                pull_number,
                **current,
            )
            return result, approve_fallback
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 422:
                raise

            attempt += 1
            if attempt > ANCHOR_RECOVERY_RETRY_CEILING:
                raise

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

                if _payload_signature(current) == prior_sig:
                    logger.error(
                        "anchor recovery on PR #{} made no progress after attempt {} "
                        "(signature unchanged: event/body_len/comments_len={})",
                        pull_number,
                        attempt,
                        prior_sig,
                    )
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
                        "(signature unchanged: event/body_len/comments_len={})",
                        pull_number,
                        attempt,
                        prior_sig,
                    )
                continue

            raise


async def _publish_github_review(
    ctx: ToolContext,
    params: dict[str, Any],
    *,
    entrypoint: str = "create_pull_request_review",
) -> dict[str, Any]:
    """Post a GitHub review after a validated terminal submission exists (V6)."""
    primary = primary_repo_state(ctx.tool_state)
    pull_number = _resolve_bound_pull_number(ctx, params)
    commit_id = _resolve_bound_commit_id(ctx, params)
    _assert_publication_scope(ctx, pull_number=pull_number, commit_id=commit_id)

    existing = _existing_publication_response(
        ctx,
        pull_number=pull_number,
        commit_id=commit_id,
    )
    if existing is not None:
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
    if approved and ctx.pr_approve_enabled and ctx.authority_trust == "trusted":
        event = "APPROVE"
    elif request_changes:
        event = "REQUEST_CHANGES"

    publish_sets = recall_publish_sets(ctx)
    enforce_recall_deferred_lane_at_publish(ctx, publish_sets=publish_sets)

    from mergecraft.config.settings_snapshot import repo_settings_from_context

    review_settings = repo_settings_from_context(ctx).review

    publish_short_ids = try_resolve_finding_short_ids(
        _publish_fingerprint_batch(comments, ctx),
        path_by_fingerprint=_publish_fingerprint_paths(comments, ctx),
    )
    analyzer_run = ctx.tool_state.analyzer_run
    if analyzer_run is not None:
        refresh_analyzer_sections_for_publish(
            analyzer_run,
            short_ids=publish_short_ids,
            inline_comment_fingerprints=set(_comment_fingerprints(comments)),
        )

    payload: dict[str, Any] = {"event": event}
    from mergecraft.evidence.run_packet import resolve_prepared_run_packet

    run_succeeded = True
    packet = resolve_prepared_run_packet(ctx, run_succeeded=run_succeeded)
    deterministic_block = _deterministic_review_block(
        ctx,
        packet=packet,
    )
    await ensure_learnings_review_delta(ctx.tool_state)
    body_with_delta = merge_learnings_delta_into_review_body(ctx.tool_state, str(body or ""))
    body_with_sections = merge_analyzer_sections_into_review_body(ctx, body_with_delta)
    if ctx.tool_state.dispatched_lens_ids:
        from mergecraft.modes._pr_summary_format import (
            merge_dispatched_lenses_into_review_metadata,
        )

        body_with_sections = merge_dispatched_lenses_into_review_metadata(
            body_with_sections,
            dispatched_lens_ids=ctx.tool_state.dispatched_lens_ids,
        )
    body_with_preamble = merge_deterministic_preamble_into_review_body(
        agent_body=body_with_sections,
        deterministic_block=deterministic_block,
    )
    payload["body"] = add_footer(ctx, body_with_preamble)
    if commit_id:
        payload["commit_id"] = commit_id

    incremental_diff_text: str | None = None
    if ctx.tool_state.selected_mode == INCREMENTAL_REVIEW_MODE:
        incremental_path = primary.incremental_diff_path
        if incremental_path:
            from pathlib import Path

            incremental_diff_text = Path(incremental_path).read_text(encoding="utf-8")

    collateral_map = collateral_by_fingerprint(ctx)
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
        raw_fingerprint = _comment_fingerprint(c)
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
            item["body"] = _prepend_short_id(item["body"], short_id)
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
        payload["body"] = add_footer(
            ctx,
            append_demoted_inline_comments(str(payload.get("body") or ""), demoted_bodies),
        )
    if inline:
        payload["comments"] = inline
    else:
        payload.pop("comments", None)

    from mergecraft.findings.ledger import (
        persist_finding_ledger_to_progress_comment,
        record_published_findings_in_ledger,
    )

    record_published_findings_in_ledger(ctx.tool_state, inline)

    result, approve_fallback = await _create_github_review_with_anchor_recovery(
        ctx,
        pull_number=pull_number,
        payload=payload,
    )
    review_id = int(result["id"])
    ctx.tool_state.review = ReviewRecord(
        id=review_id,
        node_id=str(result.get("node_id") or ""),
        reviewed_sha=payload.get("commit_id"),
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
    resolved = await _resolve_fixed_finding_threads(
        ctx,
        pull_number=pull_number,
        posted_bodies=[str(item.get("body") or "") for item in inline],
    )
    if resolved:
        response["resolvedThreads"] = resolved
    await persist_finding_ledger_to_progress_comment(ctx)
    return response


async def publish_pull_request_review(ctx: ToolContext) -> dict[str, Any]:
    """Publish the validated terminal submission to GitHub (internal, not an MCP tool)."""
    if ctx.tool_state.terminal_submission is None:
        msg = "no validated terminal submission available for publication"
        raise ValueError(msg)

    pull_number = _bound_pull_number(ctx)
    if pull_number is None:
        msg = "no pull number available for validated terminal submission publication"
        raise ValueError(msg)
    commit_id = _bound_commit_id(ctx)
    existing = _existing_publication_response(
        ctx,
        pull_number=pull_number,
        commit_id=commit_id,
    )
    if existing is not None:
        return existing

    pending = ctx.tool_state.pending_review_publication
    if pending is None:
        submission = ctx.tool_state.terminal_submission
        pending = {
            "pull_number": pull_number,
            "body": submission.summary,
            "comments": [],
            "approved": submission.verdict == "approve",
            "request_changes": submission.verdict == "request_changes",
        }
    if commit_id:
        pending = dict(pending)
        pending["commit_id"] = commit_id

    ctx.tool_state.review_phase = ReviewPhase.PUBLISH.value
    stamp_review_phase_on_active_span(ReviewPhase.PUBLISH)
    result = await _publish_github_review(
        ctx,
        pending,
        entrypoint="publish_pull_request_review",
    )
    ctx.tool_state.review_phase = ReviewPhase.COMPLETE.value
    stamp_review_phase_on_active_span(ReviewPhase.COMPLETE)
    return result


def _wants_approve_review(params: dict[str, Any]) -> bool:
    if bool(params.get("approved")):
        return True
    event = params.get("event")
    return isinstance(event, str) and event.upper() == "APPROVE"


def _normalize_review_params(params: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(params)
    event = normalized.get("event")
    if isinstance(event, str) and event.upper() == "APPROVE" and "approved" not in normalized:
        normalized["approved"] = True
    return normalized


def create_pull_request_review_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        params = _normalize_review_params(params)
        if _wants_approve_review(params) and ctx.authority_trust != "trusted":
            msg = (
                "APPROVE is not permitted on this run: authority trust is untrusted "
                "(trust.selfReview must be full with explicit operator confirmation)"
            )
            raise ValueError(msg)

        approved = bool(params.get("approved"))
        request_changes = bool(params.get("request_changes"))
        if approved and request_changes:
            msg = "approved and request_changes are mutually exclusive"
            raise ValueError(msg)

        body = params.get("body")
        comments = list(params.get("comments") or [])
        if not body and not comments:
            return {
                "success": True,
                "skipped": True,
                "reason": "empty review (no body and no comments)",
            }

        pull_number = _resolve_bound_pull_number(ctx, params)
        commit_id = _resolve_bound_commit_id(ctx, params)
        _assert_publication_scope(ctx, pull_number=pull_number, commit_id=commit_id)

        primary = primary_repo_state(ctx.tool_state)
        primary.issue_number = pull_number

        existing = _existing_publication_response(
            ctx,
            pull_number=pull_number,
            commit_id=commit_id,
        )
        if existing is not None:
            return existing

        ensure_review_scope_for_terminal(ctx.tool_state, "create_pull_request_review")

        if ctx.tool_state.terminal_submission is None:
            submission_payload = _legacy_params_to_submission(params)
            if submission_payload is not None:
                recorded = record_validated_terminal_submission(ctx, submission_payload)
                after_terminal_submission_recorded(ctx, recorded, replayed=False)
        else:
            _reject_mismatched_publication(ctx.tool_state.terminal_submission, params)
            _maybe_revalidate_before_publish(ctx)

        publication_params = dict(params)
        publication_params["pull_number"] = pull_number
        bound_commit = _bound_commit_id(ctx)
        if bound_commit:
            publication_params["commit_id"] = bound_commit
        submission = ctx.tool_state.terminal_submission
        if submission is not None:
            publication_params["body"] = submission.summary
        ctx.tool_state.pending_review_publication = publication_params

        ctx.tool_state.review_phase = ReviewPhase.PUBLISH.value
        stamp_review_phase_on_active_span(ReviewPhase.PUBLISH)
        from mergecraft.mcp.verification import emit_published_findings

        emit_published_findings(ctx)
        result = await _publish_github_review(
            ctx,
            publication_params,
            entrypoint="create_pull_request_review",
        )
        ctx.tool_state.review_phase = ReviewPhase.COMPLETE.value
        stamp_review_phase_on_active_span(ReviewPhase.COMPLETE)
        return result

    return tool(
        name="create_pull_request_review",
        tool_class=ToolClass.REVIEW_WRITE,
        mutates=True,
        description=(
            "Submit a review for an existing pull request. "
            "Set approved:true to approve, request_changes:true to block, or neither "
            "for a plain comment review."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "body": {"type": "string"},
                "approved": {"type": "boolean"},
                "request_changes": {"type": "boolean"},
                "comments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "line": {"type": "number"},
                            "side": {"type": "string", "enum": ["LEFT", "RIGHT"]},
                            "body": {"type": "string"},
                            "suggestion": {
                                "type": "string",
                                "description": (
                                    "Complete replacement text for the anchored line range, "
                                    "correctly indented, no diff markers and no prose. Wrapped "
                                    "server-side in a GitHub ```suggestion fence so the author "
                                    "gets a one-click Commit suggestion button. Omit when the fix "
                                    "spans multiple hunks or files, or when you cannot produce "
                                    "the exact replacement text — a suggestion that does not "
                                    "apply cleanly is worse than none."
                                ),
                            },
                            "start_line": {"type": "number"},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [],
            "additionalProperties": False,
        },
        execute=execute(_run, "create_pull_request_review"),
    )
