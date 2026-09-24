"""P-17 — mergeCraft authorship is the marker AND an expected publisher (TB-D7).

Wave plan: ``.ignorelocal/waves/40-trust-boundaries-wave-plan.md`` (TB3).

A review body that carries ``*via mergecraft*`` (or a ``mergecraft-finding:v1:``
marker) proves nothing on its own: anyone who can leave a PR review can paste
it. mergeCraft authorship is that marker **and** an author login the run is
known to publish as:

* the configured reviewer App's bot login (``<app-slug>[bot]``) — read from
  ``GET /app`` and, inside the Action, from the ``MERGECRAFT_REVIEWER_BOT_LOGIN``
  the review step declares;
* a caller PAT's login (``GET /user``) **only** when the run publishes with a
  PAT.

The shared Actions job bot (``github-actions[bot]``) is **never** accepted. It is
a shared identity, not an App identity: any same-repo collaborator with workflow
permissions can add a ``pull_request`` workflow on their branch that posts a
marker-bearing review as that login, moving the checkpoint to a commit of their
choosing. No marker, run id, or header can distinguish that forged review from a
real one, so job-token publication proves **nothing**. A run with no App and no
PAT therefore publishes no attributable identity at all: the expected-publisher
set is empty (fail-closed, P-6) and the withholding is stated once at ``warning``
naming the identity and the consequence (P-8). Configure the reviewer App or a
PAT to restore incremental checkpoints.

The set is built once per run and cached on the context. A lookup failure drops
that login; it never widens the match (P-6).
"""

from __future__ import annotations

import asyncio
import inspect
import os
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.mcp.context import ToolContext

__all__ = [
    "GITHUB_ACTIONS_BOT_LOGIN",
    "MERGECRAFT_REVIEW_MARKERS",
    "expected_publisher_logins",
    "has_mergecraft_marker",
    "is_mergecraft_authored",
]

# A mergeCraft-authored review carries the run footer, or — for a review whose
# body was suppressed — at least one finding marker.
MERGECRAFT_REVIEW_MARKERS: tuple[str, ...] = ("*via mergecraft*", "mergecraft-finding:v1:")

# The login the Actions job token publishes as. It is a **shared** identity that
# any same-repo collaborator can forge, so it is never added to the
# expected-publisher set; it is named only in the withheld-reason warning.
GITHUB_ACTIONS_BOT_LOGIN = "github-actions[bot]"


def has_mergecraft_marker(item: Mapping[str, Any]) -> bool:
    """Return True when ``item``'s body carries a mergeCraft marker."""
    body = str(item.get("body") or "")
    return any(marker in body for marker in MERGECRAFT_REVIEW_MARKERS)


def _author_login(item: Mapping[str, Any]) -> str:
    """Return the casefolded author login of ``item``, or ``""`` when unnamed."""
    user = item.get("user")
    if not isinstance(user, dict):
        return ""
    return str(user.get("login") or "").strip().casefold()


def is_mergecraft_authored(item: Mapping[str, Any], *, publishers: frozenset[str]) -> bool:
    """Return True when ``item`` is a mergeCraft review by an expected publisher.

    Both halves are required (P-17 / TB-D7): the body must carry a mergeCraft
    marker **and** the author login must be in ``publishers``. An empty
    ``publishers`` set authorizes nothing, and an item with no named author is
    not attributable.
    """
    if not publishers:
        return False
    login = _author_login(item)
    if not login:
        return False
    if login not in {publisher.casefold() for publisher in publishers}:
        return False
    return has_mergecraft_marker(item)


def expected_publisher_logins(ctx: ToolContext) -> frozenset[str]:
    """Return the logins a mergeCraft review may be authored by on this run.

    Built once per run and cached on ``ctx`` (TB-D7). Synchronous by contract so
    the pure callers (``last_reviewed_sha`` / ``review_round_index``) and the
    review-history filter can use it without a running loop; the single
    ``ctx.scm.get`` lookup is driven to completion internally.
    """
    cached = ctx.publisher_logins
    if cached is None:
        cached = _collect_publisher_logins(ctx)
        ctx.publisher_logins = cached
    return cached


def _collect_publisher_logins(ctx: ToolContext) -> frozenset[str]:
    """Resolve the expected-publisher set, dropping every failed lookup.

    Only an App or PAT publisher proves mergeCraft authorship. The shared
    Actions job bot is withheld — never added from the declared login or from
    the publication token — so a run that publishes as it yields an empty set,
    warned once with the reason (P-8).
    """
    logins: set[str] = set()
    job_bot_only = False

    # (1) The reviewer App's bot login. ``mergecraft.yml`` declares it in
    # ``MERGECRAFT_REVIEWER_BOT_LOGIN`` (``<app-slug>[bot]``, or an empty string
    # when no App minted); a client authenticated with the App JWT can instead
    # read it from ``GET /app``. Both are authorities the PR cannot write — as
    # long as the declared login is not the shared job bot itself.
    declared = os.environ.get("MERGECRAFT_REVIEWER_BOT_LOGIN", "").strip()
    if declared:
        if declared.casefold() == GITHUB_ACTIONS_BOT_LOGIN:
            # A no-App workflow historically declared the shared job bot here.
            # It is not an app identity, so it is withheld, never trusted.
            job_bot_only = True
        else:
            logins.add(declared)
    app_slug = _app_bot_slug(ctx)
    if app_slug:
        logins.add(f"{app_slug}[bot]")

    # (2) With no App declared, the publication token names the publisher. A
    # caller PAT answers ``GET /user`` with a login; the Actions job token
    # cannot be told apart from another workflow's, so it is never trusted — a
    # job-token run publishes no attributable identity at all (P-6). A
    # configured App whose login could not be read is the publisher, so the job
    # bot must not be trusted for it — fail closed.
    if not declared and not app_slug and not _app_configured():
        token = str(ctx.github_installation_token or "").strip()
        if token:
            if _is_job_token(token):
                # The job token is a shared identity, and ``GET /user`` answers
                # ``github-actions[bot]`` for it — a truthy viewer that would be
                # added before any withholding could happen (MC-e4a36e). Do not
                # consult it at all.
                job_bot_only = True
            else:
                viewer = _viewer_login(ctx)
                if viewer and viewer.casefold() != GITHUB_ACTIONS_BOT_LOGIN:
                    logins.add(viewer)
                elif viewer:
                    # Defensive: a viewer that answers with the shared bot proves
                    # nothing, whatever the token was.
                    job_bot_only = True

    # The shared Actions bot is a shared identity, so **no** path above may put
    # it in the set — declared login, ``GET /app`` slug, or ``/user`` viewer
    # (MC-e4a36e). Enforce the invariant once, over every source, instead of
    # trusting each path to withhold it: ``_app_bot_slug`` would also yield
    # ``github-actions`` if ``GET /app`` ever answered for a job token.
    shared_bot = {login for login in logins if login.casefold() == GITHUB_ACTIONS_BOT_LOGIN}
    if shared_bot:
        logins -= shared_bot
        job_bot_only = True

    if not logins and job_bot_only:
        logger.warning(
            "mergeCraft authorship withheld: the only identity this run can publish as is "
            "the shared Actions login {!r}, which any same-repo collaborator can forge. "
            "Incremental checkpoints and round counting are unavailable; configure the "
            "reviewer App (secrets MERGECRAFT_APP_ID / MERGECRAFT_APP_PRIVATE_KEY) or "
            "publish with a PAT.",
            GITHUB_ACTIONS_BOT_LOGIN,
        )

    logger.debug("expected mergeCraft publisher logins for this run: {}", sorted(logins))
    return frozenset(logins)


def _app_configured() -> bool:
    """True when this process holds reviewer-App credentials it could publish with."""
    return bool(
        os.environ.get("GITHUB_APP_ID", "").strip()
        and os.environ.get("GITHUB_APP_PRIVATE_KEY", "").strip()
    )


def _app_bot_slug(ctx: ToolContext) -> str:
    """Return the reviewer App's bot slug from ``GET /app``, or ``""``."""
    try:
        payload = _scm_get_sync(ctx, "/app")
    except Exception as err:  # advisory; a failed lookup must not widen the set
        logger.debug("reviewer App lookup failed; dropping its bot login: {}", err)
        return ""
    if isinstance(payload, dict):
        slug = str(payload.get("slug") or "").strip()
        if slug:
            return slug
    return ""


def _viewer_login(ctx: ToolContext) -> str:
    """Return the login the publication token acts as (``GET /user``), or ``""``."""
    try:
        payload = _scm_get_sync(ctx, "/user")
    except Exception as err:  # advisory; drop it, never widen
        logger.debug("PAT viewer lookup failed; dropping its login: {}", err)
        return ""
    if isinstance(payload, dict):
        return str(payload.get("login") or "").strip()
    return ""


def _is_job_token(token: str) -> bool:
    """Return True when ``token`` is the Actions job token this process sees."""
    for name in ("INPUT_TOKEN", "GITHUB_TOKEN"):
        candidate = os.environ.get(name, "").strip()
        if candidate and candidate == token:
            return True
    return False


def _scm_get_sync(ctx: ToolContext, path: str) -> Any:
    """Drive ``ctx.scm.get(path)`` from sync code and return its result."""
    result = ctx.scm.get(path)
    if not inspect.isawaitable(result):
        return result
    return _await_sync(result)


def _await_sync(awaitable: Any) -> Any:
    """Run ``awaitable`` to completion from either a sync or async caller."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _run_coroutine(awaitable)
    # A loop is already running: give the lookup its own loop in a worker so the
    # sync contract holds without blocking the caller's loop.
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run_coroutine, awaitable).result()


def _run_coroutine(awaitable: Any) -> Any:
    """Run one awaitable to completion on a fresh event loop."""
    return asyncio.run(awaitable)
