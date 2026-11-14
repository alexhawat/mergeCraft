"""Resolve pull request metadata and review policy declarations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.requirements.ingest import ScopeDeclaration, parse_scope_paths
from mergecraft.review_policy.fix_labels import resolve_fix_labels
from mergecraft.review_policy.red_green import read_red_green_declaration

if TYPE_CHECKING:
    from mergecraft.action.review_state import RunContext


def _pull_snapshot_key(
    owner: str, repo: str, number: int, pull: dict[str, Any]
) -> tuple[str, str, int, str, str] | None:
    head, base = pull.get("head"), pull.get("base")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    base_sha = base.get("sha") if isinstance(base, dict) else None
    if (
        not isinstance(head_sha, str)
        or not head_sha
        or not isinstance(base_sha, str)
        or not base_sha
    ):
        return None
    return owner, repo, number, head_sha.lower(), base_sha.lower()


def _remember_pull_request(
    ctx: RunContext, owner: str, repo: str, number: int, pull: dict[str, Any]
) -> None:
    """Keep the initial API payload as author data, outside the trust-binding event."""
    snapshots = getattr(ctx, "pull_request_snapshots", None)
    key = _pull_snapshot_key(owner, repo, number, pull)
    if snapshots is not None and key is not None and pull.get("number") == number:
        snapshots[key] = deepcopy(pull)


async def _fetch_pull_request(
    ctx: RunContext, pull: dict[str, Any], *, what: str
) -> dict[str, Any]:
    """Reuse the run's bound PR snapshot or read it once through the SCM.

    *what* names the field the caller is after, for the error. Raises when the
    read fails or there is no SCM to read with, so the caller records what it
    could not see rather than silently reading an empty value.
    """
    scm = getattr(ctx, "scm", None)
    tool_context = getattr(ctx, "tool_context", None)
    if scm is None and tool_context is not None:
        scm = getattr(tool_context, "scm", None)
    repo = getattr(getattr(ctx, "run_context", None), "repo", None)
    if repo is None and tool_context is not None:
        repo = getattr(tool_context, "repo", None)
    raw_number = pull.get("number")
    number = raw_number if isinstance(raw_number, int) else ctx.pr_number
    if scm is None or repo is None or number is None:
        msg = f"the pull request {what} is not in the event and cannot be read"
        raise RuntimeError(msg)
    key = _pull_snapshot_key(repo.owner, repo.name, int(number), pull)
    snapshots = getattr(ctx, "pull_request_snapshots", {})
    if key is not None and key in snapshots:
        return deepcopy(snapshots[key])
    fetched = await scm.get_pull(repo.owner, repo.name, int(number))
    if not isinstance(fetched, dict):
        return {}
    _remember_pull_request(ctx, repo.owner, repo.name, int(number), fetched)
    return fetched


async def _fetch_pull_request_body(ctx: RunContext, pull: dict[str, Any]) -> str | None:
    """Read the pull request's description through the SCM (one ``get_pull``).

    Raises when the read fails or there is no SCM to read with, so the caller
    records the scope as unknown rather than skipping a body it could not see.
    """
    body = (await _fetch_pull_request(ctx, pull, what="body")).get("body")
    return body if isinstance(body, str) else None


async def _resolve_run_pull_request_metadata(ctx: RunContext) -> None:
    """Record the pull request's title and label names on the run state (#1056 part 5).

    A ``pull_request`` the run bound itself (the comment trigger, a PR-naming
    ``workflow_dispatch``) carries only ``number``/``head``/``base``, and a dispatch
    payload has no title either, so fix detection would see neither a ``fix:`` title
    nor a ``bug`` label and an unproven fix would pass as ``fix.not-required``. The
    title and labels are taken from the raw event when it has them
    (``pull_request.*``, or ``issue.*`` on a comment on a pull request) and read
    through the SCM once otherwise, onto ``ToolState.pull_request_title`` and
    ``ToolState.pull_request_labels``. Never fails the run: a read that fails leaves
    both ``None`` and is logged, so detection falls back to whatever the payload
    carries. Author inputs only ever add the requirement.
    """
    if ctx.tool_state is None:
        return
    from mergecraft.evidence.run_packet import (
        event_pull_request_labels,
        event_pull_request_title,
    )

    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    title = event_pull_request_title(event)
    labels = event_pull_request_labels(event)
    if title is None or labels is None:
        pull = event.get("pull_request")
        if not isinstance(pull, dict):
            return
        try:
            fetched = await _fetch_pull_request(ctx, pull, what="title and labels")
        except Exception as err:  # fix detection keeps the payload's inputs, never crashes the run
            logger.warning(
                "fix_labels: the pull request's title and labels could not be read; "
                "fix detection uses the event's inputs only: {}",
                err,
            )
            return
        read = {"pull_request": fetched}
        if title is None:
            title = event_pull_request_title(read)
        if labels is None:
            labels = event_pull_request_labels(read)
        if title is None and labels is None:
            logger.warning(
                "fix_labels: the pull request read carries neither title nor labels; "
                "fix detection uses the event's inputs only"
            )
            return
    if title is not None:
        ctx.tool_state.pull_request_title = title
    if labels is not None:
        ctx.tool_state.pull_request_labels = tuple(labels)


async def _pull_request_body(ctx: RunContext) -> str | None:
    """The pull request's own description, never a comment body.

    Read from the raw event: ``pull_request.body`` on pull-request and review
    comment events, ``issue.body`` on a comment on a pull request. A
    ``pull_request`` the run bound itself (the comment trigger, a PR-naming
    ``workflow_dispatch``) carries no ``body`` key, so the pull request is read
    through the SCM once; a failed read raises. The resolved payload's
    ``event.body`` is the comment for comment triggers, so it is used only for a
    pull-request trigger.
    """
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    pull = event.get("pull_request")
    if isinstance(pull, dict):
        if "body" not in pull:
            return await _fetch_pull_request_body(ctx, pull)
        body = pull.get("body")
        return body if isinstance(body, str) else None
    issue = event.get("issue")
    if isinstance(issue, dict) and issue.get("pull_request") is not None:
        body = issue.get("body")
        return body if isinstance(body, str) else None
    resolved = ctx.ctx_payload
    if resolved is not None and resolved.event.is_pr:
        trigger = resolved.event.trigger
        if trigger.startswith("pull_request") and "comment" not in trigger:
            return resolved.event.body
    return None


async def _resolve_run_fix_labels(ctx: RunContext) -> None:
    """Record ``review.fixLabels`` from the operator's side of the pull request (#1056).

    Stored on ``ToolState.fix_labels`` before any tier can skip the agent, so the
    packet and the verification tool decide "is this a fix?" from base-side labels
    only. Never fails the run: any doubt leaves the defaults (``bug``, ``fix``).
    """
    if ctx.settings is None or ctx.tool_state is None or ctx.tool_context is None:
        return
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    repo = ctx.tool_context.repo
    try:
        labels = await resolve_fix_labels(
            ctx.tool_context.scm,
            repo.owner,
            repo.name,
            event=event,
            run_start_review=ctx.settings.review,
            operator_owned=ctx.settings_snapshot_operator_owned,
        )
    except Exception as err:  # fix detection falls back to the defaults, never off
        logger.warning("fix_labels: could not resolve review.fixLabels, using defaults: {}", err)
        from mergecraft.ci.red_green import DEFAULT_FIX_LABELS

        labels = DEFAULT_FIX_LABELS
    ctx.tool_state.fix_labels = labels


async def _resolve_run_red_green_declaration(ctx: RunContext) -> None:
    """Record the base-side ``ciEvidence.redGreen`` before any CI ingest (#1056).

    Stored on ``ToolState.red_green_declaration``; with none declared,
    ``ToolState.red_green`` records ``not-declared`` so a fix pull request is told
    which setting is missing. A pull request's own config never declares its
    receipt. Never fails the run: any doubt declares nothing.
    """
    if ctx.settings is None or ctx.tool_state is None or ctx.tool_context is None:
        return
    event = ctx.gh_event if isinstance(ctx.gh_event, dict) else {}
    repo = ctx.tool_context.repo
    unreadable: str | None
    try:
        declaration, unreadable = await read_red_green_declaration(
            ctx.tool_context.scm,
            repo.owner,
            repo.name,
            event=event,
            run_start_ci_evidence=ctx.settings.ci_evidence,
            operator_owned=ctx.settings_snapshot_operator_owned,
        )
    except Exception as err:  # an unresolvable declaration declares nothing, never fails
        logger.warning("red_green: could not resolve ciEvidence.redGreen: {}", err)
        declaration = None
        unreadable = f"the PR base config could not be read ({type(err).__name__})"
    ctx.tool_state.red_green_declaration = declaration
    if declaration is None:
        from mergecraft.ci.red_green import undeclared_red_green_evidence

        ctx.tool_state.red_green = undeclared_red_green_evidence(unreadable)


async def _record_scope_declaration(ctx: RunContext) -> None:
    """Record the run's ``Scope paths:`` declaration on ``ToolState.scope_declaration``.

    Sources in order, first declaration wins: the pull request body
    (``source_ref="pr_description"``), then the body of each issue the pull
    request closes (``ToolState.linked_issues``, ``source_ref="linked_issue#<n>"``).
    A body without a block is skipped; a block that is empty or broke a bound
    still wins, so a later source never widens it. No block anywhere records an
    undeclared scope. The bodies are untrusted data and never open a file. Any
    failure, including a pull request body that had to be fetched and could not
    be, leaves ``None`` (unknown) and never raises into the run: a closing
    issue's block never stands in for a body that might declare a narrower scope.
    """
    tool_state = ctx.tool_state
    if tool_state is None:
        return
    try:
        sources: list[tuple[str, str | None]] = [("pr_description", await _pull_request_body(ctx))]
        sources.extend(
            (f"linked_issue#{issue.number}", issue.body) for issue in tool_state.linked_issues or ()
        )
        declaration = ScopeDeclaration(declared=False, globs=(), source_ref="", rejected=())
        for source_ref, body in sources:
            if not body:
                continue
            parsed = parse_scope_paths(body)
            if parsed.declared:
                declaration = replace(parsed, source_ref=source_ref)
                break
    except Exception as exc:  # unknown, never an error: the scope gate stays null
        logger.warning("scope declaration could not be read; the scope stays unknown: {}", exc)
        tool_state.scope_declaration = None
        return
    tool_state.scope_declaration = declaration
    if declaration.declared:
        logger.info(
            "» scope declared in {}: {} glob(s), {} rejected",
            declaration.source_ref,
            len(declaration.globs),
            len(declaration.rejected),
        )
