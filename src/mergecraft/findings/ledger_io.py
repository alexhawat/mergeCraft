"""Read finding history and update the sticky progress comment through SCM.

Module: mergecraft.findings.ledger_io
Depends: mergecraft.findings.ledger_model, mergecraft.findings.record_render, loguru

Exports:
    Functions:
        configured_publisher_login — Read the configured App identity.
        fetch_review_ledger — Fold trusted review bodies and legacy comments into a ledger.
        fetch_review_record_bodies — Read deterministic review bodies from trusted publishers.
        fetch_sticky_progress_comment — Load a selected sticky comment.
        fetch_sticky_progress_comment_body — Load the selected sticky comment's body.
        hydrate_finding_ledger_from_progress_comment — Restore the run's ledger history.
        is_sticky_progress_comment — Recognize the progress-comment body shape.
        is_trusted_sticky_author — Check the comment author's publisher identity.
        publisher_logins_from_approval_checks — Derive App identities from approval checks.
        run_bound_sticky_id — Read the trusted run's sticky comment ID.
        run_sticky_scope — Bind sticky selection to the run's author evidence.
        select_sticky_progress_comment — Select a sticky under the run's authorship rule.
        sticky_progress_comment — Select a sticky from a list of comments.
        sticky_progress_comment_body — Select a sticky body from a list of comments.
        upsert_sticky_progress_comment — Write the run record and any ledger rows.
"""

from __future__ import annotations

import contextvars
from collections.abc import Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.findings.ledger_model import (
    LEDGER_MARKER_PREFIX,
    LEDGER_MARKER_V2_PREFIX,
    FindingLedger,
    ensure_finding_ledger,
    merge_ledger_into_comment,
)
from mergecraft.findings.record_render import (
    DETERMINISTIC_RECORD_MARKER,
    PROGRESS_HEADING,
    merge_deterministic_record_into_comment,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from mergecraft.mcp.context import ToolContext
    from mergecraft.scm.protocol import ScmProvider


_VIA_MERGECRAFT_MARKER = "*via mergecraft*"

_ISSUE_COMMENT_PAGE_SIZE = 100
# GitHub issue comments are paginated at 100/page; cap total scanned comments
# at 1000 (10 pages) to bound API cost on very chatty PRs.
_MAX_ISSUE_COMMENT_PAGES = 10
_REVIEW_PAGE_SIZE = 100
_MAX_REVIEW_PAGES = 10


def is_sticky_progress_comment(body: str) -> bool:
    """Return whether ``body`` looks like the mergeCraft sticky progress comment.

    This is a body-only shape test: it answers "could this text be our
    comment?", not "is this comment ours?". Author trust is decided by
    :func:`select_sticky_progress_comment` (HS1: run-bound id, then the
    expected-publisher set, then create-new), which never accepts a Bot-type
    match on its own.
    """
    lowered = body.lower()
    return (
        DETERMINISTIC_RECORD_MARKER in body
        or LEDGER_MARKER_PREFIX in body
        or LEDGER_MARKER_V2_PREFIX in body
        or PROGRESS_HEADING in body
        or _VIA_MERGECRAFT_MARKER in lowered
    )


_DEFAULT_PUBLISHER_LOGIN = "github-actions[bot]"
_APPROVAL_CHECK_NAME = "mergecraft-approval"
_publisher_login_from_config: str | None = None
_publisher_logins_override: contextvars.ContextVar[frozenset[str] | None] = contextvars.ContextVar(
    "mergecraft_publisher_logins",
    default=None,
)


def _publisher_login_from_repo_config() -> str:
    """Return ``reviewerBotLogin`` from repo config, or ``""`` when unset.

    Cached for the process. The Action env wins over this; the cache only
    serves read-side CLI and carryover, which do not set that env.
    """
    global _publisher_login_from_config
    if _publisher_login_from_config is not None:
        return _publisher_login_from_config
    loaded = ""
    try:
        from mergecraft.config.settings import load_repo_settings

        settings = load_repo_settings(load_learnings_files=False)
        loaded = (settings.reviewer_bot_login or "").strip()
    except Exception as err:
        logger.warning("finding ledger: could not read reviewerBotLogin from repo config: {}", err)
    _publisher_login_from_config = loaded
    return loaded


def _allowed_publisher_logins() -> frozenset[str]:
    """Logins that may own a formal review or legacy sticky comment."""
    from mergecraft.config.env import ReviewEnv

    configured = ReviewEnv().reviewer_bot_login or ""
    if configured:
        return frozenset({configured})
    override = _publisher_logins_override.get()
    if override:
        return override
    from_config = _publisher_login_from_repo_config()
    return frozenset({from_config or _DEFAULT_PUBLISHER_LOGIN})


def configured_publisher_login() -> str:
    """Return the reviewer App bot login configured for this checkout, or ``""``.

    The read-only operator view (``findings ledger``) has no run context, so it
    cannot resolve a run-bound comment id or a publisher set from credentials.
    It uses the configured App slug when one is set — ``MERGECRAFT_REVIEWER_BOT_LOGIN``
    or ``reviewerBotLogin`` from repo config — and otherwise reads a Bot-type
    comment and says the result is unauthenticated. The shared Actions job bot is
    not an App identity, so it counts as unconfigured.
    """
    from mergecraft.config.env import ReviewEnv

    declared = ReviewEnv().reviewer_bot_login or ""
    if declared:
        if declared.casefold() == _DEFAULT_PUBLISHER_LOGIN.casefold():
            return ""
        return declared
    configured = _publisher_login_from_repo_config().strip()
    if configured.casefold() == _DEFAULT_PUBLISHER_LOGIN.casefold():
        return ""
    return configured


def _check_run_rows(payload: object) -> list[Mapping[str, object]]:
    raw: object
    if isinstance(payload, Mapping):
        raw = payload.get("check_runs")
        if not isinstance(raw, list):
            raw = payload.get("items")
    else:
        raw = getattr(payload, "items", None)
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, Mapping)]


async def publisher_logins_from_approval_checks(
    scm: ScmProvider, owner: str, repo: str, pull_number: int
) -> frozenset[str]:
    """Derive ``{app-slug}[bot]`` from ``mergecraft-approval`` checks on the head.

    The review workflow mints that check with the same token that publishes
    the formal review. Read-side CLI and carryover have no Action env, so the
    check's app slug is the publisher identity. No slug means no derivation.
    """
    get_pull = getattr(scm, "get_pull", None)
    list_checks = getattr(scm, "list_check_runs_for_ref", None)
    if get_pull is None or list_checks is None:
        return frozenset()
    try:
        pull = await get_pull(owner, repo, pull_number)
        head = pull.get("head") if isinstance(pull, Mapping) else None
        sha = str(head.get("sha") or "") if isinstance(head, Mapping) else ""
        if not sha:
            return frozenset()
        # Do not pass check_name=: GitHubClient.list_check_runs_for_ref forwards
        # leftover keywords to get(), which only accepts params/json/headers.
        payload = await list_checks(owner, repo, sha)
    except Exception as err:
        logger.warning("finding ledger: could not derive publisher from approval checks: {}", err)
        return frozenset()
    logins: set[str] = set()
    for run in _check_run_rows(payload):
        if str(run.get("name") or _APPROVAL_CHECK_NAME) != _APPROVAL_CHECK_NAME:
            continue
        app = run.get("app")
        if not isinstance(app, Mapping):
            continue
        slug = str(app.get("slug") or "").strip()
        if slug:
            logins.add(f"{slug}[bot]")
    return frozenset(logins)


def is_trusted_sticky_author(comment: Mapping[str, object]) -> bool:
    """Trust a comment or review only when this run's publisher bot wrote it.

    A PR participant can quote the heading, the footer or a ledger marker, so a
    body shape test alone lets a human win selection. ``user.type == "Bot"`` is
    not enough either: another App, or ``github-actions[bot]`` from a different
    workflow, can post the same public marker. The login must belong to the set returned by
    :func:`_allowed_publisher_logins`.

    When the workflow has no App token, the expected login stays
    ``github-actions[bot]``. That login is shared by every workflow in the
    repo, so a same-repo collaborator workflow can still post as it.
    """
    user = comment.get("user")
    if not isinstance(user, Mapping):
        return False
    if str(user.get("type") or "") != "Bot":
        return False
    return str(user.get("login") or "") in _allowed_publisher_logins()


# ── HS1 — one authorship rule for the sticky comment (P-17) ──────────────────
#
# The run-scoped ledger paths (``persist`` / ``upsert`` / ``hydrate``) set these
# for the duration of their sticky lookup. When ``_run_scope_publishers`` is not
# ``None`` — even when it is the empty set — selection follows HS1's three-step
# order and never falls back to a Bot-type match. Callers with no run scope (the
# read-only operator view and the progress-comment writers that predate the
# scope) keep the body-shape + Bot-type fallback below.
_run_scope_publishers: contextvars.ContextVar[frozenset[str] | None] = contextvars.ContextVar(
    "mergecraft_sticky_publishers",
    default=None,
)
_run_scope_progress_comment_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "mergecraft_sticky_run_bound_comment_id",
    default=None,
)


def _comment_author_login(comment: Mapping[str, object]) -> str:
    """Return the casefolded author login of ``comment``, or ``""`` when unnamed."""
    user = comment.get("user")
    if not isinstance(user, Mapping):
        return ""
    return str(user.get("login") or "").strip().casefold()


def _comment_author_is_bot(comment: Mapping[str, object]) -> bool:
    """Return whether ``comment``'s author is GitHub-typed as a bot."""
    user = comment.get("user")
    if not isinstance(user, Mapping):
        return False
    return str(user.get("type") or "") == "Bot"


def _carries_ledger_marker(body: str) -> bool:
    """Return whether ``body`` carries a mergeCraft ledger or record marker."""
    return (
        DETERMINISTIC_RECORD_MARKER in body
        or LEDGER_MARKER_PREFIX in body
        or LEDGER_MARKER_V2_PREFIX in body
    )


def _step_one_run_bound(
    comments: Sequence[Mapping[str, object]],
    run_bound_comment_id: int | None,
    *,
    return_body: bool,
) -> str | dict[str, Any] | None:
    """HS1 step 1 — the trusted run's own artefact names the sticky by id.

    The id proves which comment the trusted run owns, so a job-token-only run
    keeps its cross-run ledger even though no publisher identity resolves. The
    comment must still be a Bot and still carry a marker: an id alone is not
    permission to trust a human comment or a markerless body.
    """
    if run_bound_comment_id is None:
        return None
    target = str(run_bound_comment_id)
    for comment in comments:
        if str(comment.get("id") or "") != target:
            continue
        body = str(comment.get("body") or "")
        if not _comment_author_is_bot(comment):
            return None
        if not _carries_ledger_marker(body):
            return None
        return body if return_body else dict(comment)
    return None


def _step_two_publisher(
    comments: Sequence[Mapping[str, object]],
    publishers: frozenset[str],
    *,
    return_body: bool,
) -> str | dict[str, Any] | None:
    """HS1 step 2 — the expected-publisher set.

    A sticky is this run's only when a login the run publishes as wrote it. An
    empty set authorizes nothing. Ledger-marker preference is applied inside the
    set (LG-D4): a marker-bearing publisher comment beats a heading-only one.
    """
    if not publishers:
        return None
    allowed = {login.casefold() for login in publishers}
    progress_body = ""
    progress: dict[str, Any] | None = None
    for comment in comments:
        body = str(comment.get("body") or "")
        if not is_sticky_progress_comment(body):
            continue
        if _comment_author_login(comment) not in allowed:
            continue
        if _carries_ledger_marker(body):
            return body if return_body else dict(comment)
        if return_body:
            progress_body = body
        else:
            progress = dict(comment)
    return progress_body if return_body else progress


def _warn_no_publisher_identity() -> None:
    """Log the one HS1 step-3 warning naming why no existing sticky was trusted."""
    logger.warning(
        "finding ledger: no publisher identity resolved for this run and no "
        "run-bound progress-comment id, so no existing sticky progress comment "
        "can be trusted as this run's; creating a new progress comment. Configure "
        "the reviewer App or publish with a PAT to restore the cross-run ledger."
    )


def _select_hs1(
    comments: Sequence[Mapping[str, object]],
    *,
    publishers: frozenset[str],
    run_bound_comment_id: int | None,
    return_body: bool,
) -> str | dict[str, Any] | None:
    """Apply HS1's three-step order; step 3 creates-new (never Bot-type)."""
    bound = _step_one_run_bound(comments, run_bound_comment_id, return_body=return_body)
    if bound is not None:
        return bound
    publisher_match = _step_two_publisher(comments, publishers, return_body=return_body)
    if publisher_match is not None:
        return publisher_match
    _warn_no_publisher_identity()
    return "" if return_body else None


def select_sticky_progress_comment(
    ctx: ToolContext,
    comments: Sequence[Mapping[str, object]],
    *,
    run_bound_comment_id: int | None = None,
) -> dict[str, Any] | None:
    """Select the run's sticky progress comment under HS1's three-step order.

    The publisher set is resolved from the run's own credentials
    (:func:`mergecraft.review.authorship.expected_publisher_logins`), never from
    a PR-forgeable comment body. ``run_bound_comment_id`` is the id the trusted
    workflow run's own artefact names (HS8); it outranks the publisher scan and
    is the only path that selects on a job-token-only run. When neither is
    available the writer creates a new comment and one warning names why — this
    selector never falls back to a Bot-type match.
    """
    from mergecraft.review.authorship import expected_publisher_logins

    selected = _select_hs1(
        comments,
        publishers=expected_publisher_logins(ctx),
        run_bound_comment_id=run_bound_comment_id,
        return_body=False,
    )
    return selected if isinstance(selected, dict) else None


def run_bound_sticky_id(ctx: ToolContext) -> int | None:
    """Return the run-bound sticky id HS8 records, when the run state carries one."""
    raw = getattr(ctx.tool_state, "run_bound_progress_comment_id", None)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


@contextmanager
def run_sticky_scope(ctx: ToolContext) -> Iterator[None]:
    """Scope a sticky lookup to the run's publisher set and run-bound id (HS1)."""
    from mergecraft.review.authorship import expected_publisher_logins

    publisher_token = _run_scope_publishers.set(expected_publisher_logins(ctx))
    id_token = _run_scope_progress_comment_id.set(run_bound_sticky_id(ctx))
    try:
        yield
    finally:
        _run_scope_progress_comment_id.reset(id_token)
        _run_scope_publishers.reset(publisher_token)


def _select_sticky_progress_comment(
    comments: Sequence[Mapping[str, object]],
    *,
    return_body: bool,
) -> str | dict[str, Any] | None:
    """Select the sticky progress comment; ledger markers win over heading heuristics.

    Under a run scope (``run_sticky_scope``) this applies HS1's order. Without
    one — the read-only operator view and the pre-scope progress-comment writers
    — it keeps the legacy body-shape + Bot-type fallback, which is
    unauthenticated by construction: ``github-actions[bot]`` is shared and
    forgeable, so a caller that needs identity must run inside the scope.
    """
    publishers = _run_scope_publishers.get()
    if publishers is not None:
        return _select_hs1(
            comments,
            publishers=publishers,
            run_bound_comment_id=_run_scope_progress_comment_id.get(),
            return_body=return_body,
        )
    progress_body = ""
    progress: dict[str, Any] | None = None
    for comment in comments:
        body = str(comment.get("body") or "")
        if not is_sticky_progress_comment(body):
            continue
        if not is_trusted_sticky_author(comment):
            logger.warning(
                "finding ledger: ignoring comment {} as a sticky progress comment: "
                "author is not a bot",
                comment.get("id"),
            )
            continue
        if LEDGER_MARKER_PREFIX in body or LEDGER_MARKER_V2_PREFIX in body:
            return body if return_body else dict(comment)
        if return_body:
            progress_body = body
        else:
            progress = dict(comment)
    return progress_body if return_body else progress


def sticky_progress_comment_body(comments: Sequence[Mapping[str, object]]) -> str:
    """Select the sticky progress comment body from issue comments (ledger wins)."""
    selected = _select_sticky_progress_comment(comments, return_body=True)
    return selected if isinstance(selected, str) else ""


def sticky_progress_comment(comments: Sequence[Mapping[str, object]]) -> dict[str, Any] | None:
    """Select the sticky progress comment from issue comments (ledger markers win)."""
    selected = _select_sticky_progress_comment(comments, return_body=False)
    return selected if isinstance(selected, dict) else None


async def _list_issue_comments_paginated(
    scm: ScmProvider,
    owner: str,
    repo: str,
    issue_number: int,
) -> list[dict[str, Any]]:
    """Fetch issue comments across pages, capped at ``_MAX_ISSUE_COMMENT_PAGES``."""
    collected: list[dict[str, Any]] = []
    for page in range(1, _MAX_ISSUE_COMMENT_PAGES + 1):
        comments = await scm.list_issue_comments(
            owner,
            repo,
            issue_number,
            params={"per_page": _ISSUE_COMMENT_PAGE_SIZE, "page": page},
        )
        collected.extend(comments)
        if len(comments) < _ISSUE_COMMENT_PAGE_SIZE:
            break
    return collected


async def fetch_sticky_progress_comment(
    scm: ScmProvider,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    known_comment_id: int | None = None,
) -> dict[str, Any] | None:
    """Load the sticky progress comment dict by id or from paginated issue comments."""
    if known_comment_id is not None:
        comment = await scm.get_issue_comment(owner, repo, known_comment_id)
        return dict(comment)
    comments = await _list_issue_comments_paginated(scm, owner, repo, issue_number)
    return sticky_progress_comment(comments)


async def fetch_sticky_progress_comment_body(
    scm: ScmProvider,
    owner: str,
    repo: str,
    issue_number: int,
    *,
    known_comment_id: int | None = None,
) -> str:
    """Load the sticky progress comment body by id or from paginated issue comments."""
    sticky = await fetch_sticky_progress_comment(
        scm,
        owner,
        repo,
        issue_number,
        known_comment_id=known_comment_id,
    )
    return str(sticky.get("body") or "") if sticky is not None else ""


def _review_author_login(review: Mapping[str, object]) -> str:
    user = review.get("user")
    if not isinstance(user, Mapping):
        return ""
    return str(user.get("login") or "")


async def fetch_review_record_bodies(
    scm: ScmProvider,
    owner: str,
    repo: str,
    pull_number: int,
    *,
    publishers: frozenset[str] | None = None,
) -> list[str]:
    """Read mergeCraft review bodies in publication order across GitHub pages.

    A review contributes only when its body is a deterministic record **and**
    its author is an expected publisher — the same rule as
    ``review/authorship.py``: the reviewer App's bot or the PAT the run
    publishes with (a PAT review is ``type == "User"``, so the account type is
    not consulted), never the shared ``github-actions[bot]``. ``publishers``
    defaults to the read-side identity (``MERGECRAFT_REVIEWER_BOT_LOGIN``,
    ``reviewerBotLogin`` or the approval-check slug). An empty set folds in
    nothing (fail-closed) and says so once.
    """
    from mergecraft.review_resolution import effective_publishers, is_publisher_login

    trusted = effective_publishers(
        publishers if publishers is not None else _allowed_publisher_logins()
    )
    if not trusted:
        logger.warning(
            "finding ledger: no expected publisher identity for PR #{}, so no earlier "
            "review's ledger rows are trusted; configure the reviewer App "
            "(MERGECRAFT_REVIEWER_BOT_LOGIN / reviewerBotLogin) or publish with a PAT",
            pull_number,
        )
        return []
    bodies: list[str] = []
    for page in range(1, _MAX_REVIEW_PAGES + 1):
        reviews = await scm.list_reviews(
            owner, repo, pull_number, params={"per_page": _REVIEW_PAGE_SIZE, "page": page}
        )
        for review in reviews:
            body = str(review.get("body") or "")
            if body.lstrip().startswith(DETERMINISTIC_RECORD_MARKER) and is_publisher_login(
                _review_author_login(review), trusted
            ):
                bodies.append(body)
        if len(reviews) < _REVIEW_PAGE_SIZE:
            break
    return bodies


async def fetch_review_ledger(
    scm: ScmProvider, owner: str, repo: str, pull_number: int
) -> FindingLedger:
    """Fold historical formal reviews and legacy comment state into one ledger."""
    token: contextvars.Token[frozenset[str] | None] | None = None
    from mergecraft.config.env import ReviewEnv

    if not ReviewEnv().reviewer_bot_login:
        derived = set(await publisher_logins_from_approval_checks(scm, owner, repo, pull_number))
        from_config = _publisher_login_from_repo_config()
        if from_config:
            derived.add(from_config)
        if not derived:
            derived.add(_DEFAULT_PUBLISHER_LOGIN)
        token = _publisher_logins_override.set(frozenset(derived))
    try:
        ledger = FindingLedger()
        legacy = await fetch_sticky_progress_comment_body(scm, owner, repo, pull_number)
        for record in FindingLedger.from_comment_body(legacy).records():
            ledger.upsert_if_newer(record)
        for body in await fetch_review_record_bodies(scm, owner, repo, pull_number):
            for record in FindingLedger.from_comment_body(body).records():
                ledger.upsert_if_newer(record)
        return ledger
    finally:
        if token is not None:
            _publisher_logins_override.reset(token)


async def hydrate_finding_ledger_from_progress_comment(ctx: ToolContext) -> FindingLedger:
    """Load the ledger from formal reviews and any legacy progress comment."""
    tool_state = ctx.tool_state
    if tool_state.finding_ledger_loaded:
        return ensure_finding_ledger(tool_state)

    from mergecraft.mcp.tool_state import ProgressComment, primary_repo_state

    ledger = FindingLedger()
    issue_number = primary_repo_state(tool_state).issue_number or tool_state.pr_number
    try:
        progress = tool_state.progress_comment
        if isinstance(progress, ProgressComment):
            comment = await ctx.scm.get_issue_comment(
                ctx.repo.owner, ctx.repo.name, int(progress.id)
            )
            # HS1 step 1: the run-bound id names the comment, and a bot must
            # still have written it before its rows are read.
            legacy = str(comment.get("body") or "") if _comment_author_is_bot(comment) else ""
        elif issue_number is not None:
            with run_sticky_scope(ctx):
                legacy = await fetch_sticky_progress_comment_body(
                    ctx.scm, ctx.repo.owner, ctx.repo.name, int(issue_number)
                )
        else:
            legacy = ""
        if legacy:
            for record in FindingLedger.from_comment_body(legacy).records():
                ledger.upsert_if_newer(record)
        if issue_number is not None and hasattr(ctx.scm, "list_reviews"):
            from mergecraft.review.authorship import resolve_publisher_logins

            for body in await fetch_review_record_bodies(
                ctx.scm,
                ctx.repo.owner,
                ctx.repo.name,
                int(issue_number),
                publishers=await resolve_publisher_logins(ctx),
            ):
                for record in FindingLedger.from_comment_body(body).records():
                    ledger.upsert_if_newer(record)
    except Exception as err:
        logger.warning("finding ledger: could not read review history: {}", err)

    existing = tool_state.finding_ledger
    if existing is not None:
        # When both in-memory and hydrated rows share a fingerprint, keep the
        # newer ``recorded_at`` stamp — progress comments can lag live session
        # updates during the same Action run.
        for record in existing.records():
            ledger.upsert_if_newer(record)

    tool_state.finding_ledger = ledger
    tool_state.finding_ledger_loaded = True
    return ledger


async def upsert_sticky_progress_comment(ctx: ToolContext, record_block: str) -> None:
    """Upsert the sticky progress comment with the deterministic record (D6).

    The record is written over the snapshot the last writer stored, so any
    ledger record added after that snapshot is re-merged here before the footer
    is appended. The snapshot keeps the learnings delta; this merge keeps the
    records; both are pure and need no extra API call (LG-D1).
    """
    from mergecraft.mcp.comment import add_footer
    from mergecraft.mcp.tool_state import ProgressComment, primary_repo_state
    from mergecraft.utils import gha_log

    tool_state = ctx.tool_state
    if tool_state.progress_comment is False:
        return

    issue_number = primary_repo_state(tool_state).issue_number or tool_state.pr_number
    if issue_number is None:
        return

    book = tool_state.finding_ledger
    records = book.records() if book is not None else []

    try:
        base_body = str(tool_state.last_progress_body or "").strip()
        body_with_record = merge_deterministic_record_into_comment(
            base_body,
            record_block=record_block,
        )
        # Re-merge only when the run's in-memory ledger has records: an empty
        # ledger must not strip markers a prior run persisted.
        body_with_ledger = body_with_record
        if records:
            body_with_ledger = merge_ledger_into_comment(body_with_record, records=records)

        if isinstance(tool_state.progress_comment, ProgressComment):
            await ctx.scm.update_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                int(tool_state.progress_comment.id),
                add_footer(ctx, body_with_ledger),
            )
            tool_state.last_progress_body = body_with_ledger
            return

        with run_sticky_scope(ctx):
            sticky = await fetch_sticky_progress_comment(
                ctx.scm,
                ctx.repo.owner,
                ctx.repo.name,
                int(issue_number),
            )
        if sticky is not None:
            existing_body = str(sticky.get("body") or "")
            merged = merge_deterministic_record_into_comment(
                existing_body,
                record_block=record_block,
            )
            if records:
                merged = merge_ledger_into_comment(merged, records=records)
            await ctx.scm.update_issue_comment(
                ctx.repo.owner,
                ctx.repo.name,
                int(sticky["id"]),
                add_footer(ctx, merged),
            )
            tool_state.progress_comment = ProgressComment(
                id=str(sticky["id"]),
                type="issue",
            )
            tool_state.last_progress_body = merged
            return

        result = await ctx.scm.create_issue_comment(
            ctx.repo.owner,
            ctx.repo.name,
            int(issue_number),
            add_footer(ctx, body_with_ledger),
        )
        tool_state.progress_comment = ProgressComment(id=str(result["id"]), type="issue")
        tool_state.last_progress_body = body_with_ledger
    except Exception as err:
        message = f"deterministic record: could not persist progress comment: {err}"
        logger.warning(message)
        gha_log.warning(message)


__all__ = [
    "configured_publisher_login",
    "fetch_review_ledger",
    "fetch_review_record_bodies",
    "fetch_sticky_progress_comment",
    "fetch_sticky_progress_comment_body",
    "hydrate_finding_ledger_from_progress_comment",
    "is_sticky_progress_comment",
    "is_trusted_sticky_author",
    "publisher_logins_from_approval_checks",
    "run_bound_sticky_id",
    "run_sticky_scope",
    "select_sticky_progress_comment",
    "sticky_progress_comment",
    "sticky_progress_comment_body",
    "upsert_sticky_progress_comment",
]
