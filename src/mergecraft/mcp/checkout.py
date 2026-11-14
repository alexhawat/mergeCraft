"""checkout_pr tool — fetch PR branch and write formatted diff."""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from mergecraft.analyzers.impact import resolve_ast_grep_binary, write_impact
from mergecraft.analyzers.trust import analyzers_enabled
from mergecraft.config.trust_policy import is_fork_pull_request
from mergecraft.diff import changed_paths_in_diff
from mergecraft.mcp.checkout_state import invalidate_checkout_review_state
from mergecraft.mcp.git import _git_env, _is_auth_failure, _is_shallow_repository, _run_git
from mergecraft.mcp.shared import JsonSchema, ToolClass, execute, tool
from mergecraft.mcp.tool_call import normalize_pull_number_aliases
from mergecraft.mcp.tool_state import StoredPushDest, primary_repo_state
from mergecraft.modes._api_only_scope import API_ONLY_SCOPE, degraded_checkout_reason
from mergecraft.review_policy.ignore_paths import ReviewIgnore, filter_diff, rename_sources
from mergecraft.scm.pull_files import list_pull_files
from mergecraft.utils.blocking import run_blocking, run_blocking_cleanup
from mergecraft.utils.gha_log import warning
from mergecraft.utils.git_hardening import read_remote_origin_url
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import ToolSpec
    from mergecraft.xrepo.review import BaseManifestLookup

__all__ = [
    "GitHubClient",
    "IncrementalDiffResult",
    "RunBoundReviewState",
    "checkout_pr_tool",
    "ensure_local_base_branch_alias",
    "get_git_status",
    "list_mergecraft_reviews",
    "recover_run_bound_review_state",
]


@dataclass(slots=True)
class IncrementalDiffResult:
    """Outcome of trying to materialise a re-review's incremental range.

    ``status`` is closed: ``ok`` (``path`` is set), ``empty`` (the checkpoint
    is reachable but nothing changed), or ``unavailable`` (no checkpoint, or it
    could not be turned into a diff). ``reason`` is human-readable and is
    surfaced in the tool result for the non-``ok`` cases.
    """

    status: str
    prior_sha: str
    path: str | None = None
    changed_paths: tuple[str, ...] = ()
    reason: str | None = None


def _rebaseline_config_after_checkout(ctx: ToolContext) -> None:
    """Re-baseline the config hash and review tree hash after PR checkout (D14)."""
    from mergecraft.config.settings_snapshot import rebaseline_repo_settings_snapshot

    rebaseline_repo_settings_snapshot(ctx)
    if ctx.tool_state.review_tree_baseline is not None:
        ctx.tool_state.review_tree_baseline.after_checkout()


def _manifest_exists_at_ref(*, cwd: str, ref: str, rel_path: str) -> bool:
    """Return True when ``ref:rel_path`` names an object in the checkout (TB-D11).

    ``git_show_text`` returns ``None`` both for a path that is absent at the ref
    and for a blob it cannot decode. Probing existence separately keeps "newly
    added at the head" (absent at the base) distinct from "exists but unreadable
    at the base" — the latter is an omission, not a silent zero-finding report.
    """
    try:
        _run_git(["cat-file", "-e", f"{ref}:{rel_path}"], cwd=cwd)
    except Exception:
        # Any git failure means "cannot prove it exists" — treat as absent.
        return False
    return True


def _base_ref_resolves(*, cwd: str, ref: str) -> bool:
    """Return True when ``ref`` resolves to a commit object in the checkout (TB6).

    ``git cat-file -e <ref>:<path>`` fails identically for "the ref is
    missing" and "the path is absent at a present ref". Probing the ref first
    keeps those two apart before :func:`_base_linked_repo_manifest` decides
    whether an absent manifest is benign.
    """
    try:
        _run_git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=cwd)
    except Exception:
        return False
    return True


def _base_linked_repo_manifest(
    *,
    cwd: str,
    base_ref: str,
    base_fetch_failure: str | None = None,
) -> BaseManifestLookup:
    """Read the linked-repo manifest at ``origin/<base>`` (TB-D11).

    The review path diffs pins between the base and head manifests, so it needs
    the base manifest. Four outcomes:

    * no base ref is known — every head entry is newly added and contributes
      no change;
    * the base ref **did not resolve** (its fetch soft-failed, so
      ``origin/<base>`` is missing) — the movement baseline is unknown, not
      empty: a manifest the PR added is indistinguishable from one we could
      not reach, so an omission with a reason is recorded for every
      otherwise-reviewable entry, never a silent zero-finding report
      (TB-D11/TB-D12, P-8);
    * the manifest is genuinely **absent** at a resolved base ref — every head
      entry is newly added and contributes no change;
    * the manifest **exists but cannot be decoded or parsed** — an omission
      with a reason, never a silent zero-finding report (TB-D11/TB-D12).

    Never a whole-index fallback, which would report contracts the PR did not
    change.
    """
    from mergecraft.context.repo_paths import git_show_text
    from mergecraft.xrepo.linked_repos import LinkedReposManifest, parse_manifest_text
    from mergecraft.xrepo.review import MANIFEST_REL, BaseManifestLookup

    empty = LinkedReposManifest(repos=())
    if not base_ref:
        return BaseManifestLookup(manifest=empty)
    ref = f"origin/{base_ref}"
    if not _base_ref_resolves(cwd=cwd, ref=ref):
        # The base ref never resolved. When the base fetch soft-failed the
        # movement baseline is unknown, not empty: an "absent" manifest here
        # may just be a ref we could not fetch, so each otherwise-reviewable
        # entry becomes an omission with a reason (TB-D11/TB-D12, P-8).
        reason = f"base ref {ref} could not be resolved"
        if base_fetch_failure:
            reason = f"{reason}: {base_fetch_failure}"
        return BaseManifestLookup(manifest=empty, unreadable_reason=reason)
    if not _manifest_exists_at_ref(cwd=cwd, ref=ref, rel_path=str(MANIFEST_REL)):
        return BaseManifestLookup(manifest=empty)
    unreadable_reason = f"base manifest unreadable at {ref}"
    text = git_show_text(Path(cwd), ref, str(MANIFEST_REL))
    if text is None:
        return BaseManifestLookup(manifest=empty, unreadable_reason=unreadable_reason)
    try:
        return BaseManifestLookup(manifest=parse_manifest_text(text))
    except ValueError:
        return BaseManifestLookup(manifest=empty, unreadable_reason=unreadable_reason)


# A review authored by mergeCraft carries the run footer, or (for a review whose
# body was suppressed) at least one finding marker. Reviews from humans and other
# bots carry neither, and their commit ids must never be mistaken for "the head
# mergeCraft last reviewed". The marker check lives in ``review.authorship``
# (P-17 / TB-D7) so the checkpoint and the history filter share one rule.
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
# TB-D5 — the review scope recorded when the diff came from the GitHub files
# API after a successful checkout. Not ``api-only``: the head *is* checked out,
# so head-side file reads work; only the local diff failed.
FILES_API_DIFF_SCOPE = "files-api-diff"
_CHECKOUT_PR_INPUT_SCHEMA: JsonSchema = {
    "type": "object",
    "properties": {"pull_number": {"type": "number"}},
    "required": ["pull_number"],
    "additionalProperties": False,
}


def ensure_local_base_branch_alias(*, cwd: str, base_ref: str) -> None:
    """Create ``refs/heads/<base_ref>`` pointing at ``origin/<base_ref>``.

    Agents often run ``git show <base_ref>:path`` using the bare PR base branch
    name (e.g. ``pre-0.0.1``). ``checkout_pr`` already fetches
    ``refs/remotes/origin/<base_ref>``; this local alias makes bare-name rev
    syntax work in shallow GHA checkouts too.
    """
    if not base_ref:
        return
    try:
        _run_git(["rev-parse", "--verify", f"{base_ref}^{{commit}}"], cwd=cwd)
        return
    except RuntimeError:
        pass
    _run_git(["branch", "-f", base_ref, f"origin/{base_ref}"], cwd=cwd)


def _is_authored_review(review: Mapping[str, Any], publishers: frozenset[str] | None) -> bool:
    """Return True when ``review`` is a mergeCraft review for this run.

    ``publishers=None`` keeps the legacy marker-only match for callers whose
    history is already filtered by :func:`list_mergecraft_reviews`; every
    production checkpoint passes the run's expected-publisher set so the marker
    alone can never move it (P-17 / TB-D7).
    """
    from mergecraft.review.authorship import has_mergecraft_marker, is_mergecraft_authored

    if publishers is None:
        return has_mergecraft_marker(review)
    return is_mergecraft_authored(review, publishers=publishers)


def expected_publisher_logins(ctx: ToolContext) -> frozenset[str]:
    """Return the run's expected-publisher logins (P-17 / TB-D7).

    Thin module-level seam over :func:`mergecraft.review.authorship.expected_publisher_logins`:
    imported lazily because ``mergecraft.review``'s package ``__init__`` pulls
    in the agent registry, which imports this module — a top-level import would
    cycle. Exposed as a module attribute so callers and tests can pin it.
    """
    from mergecraft.review.authorship import expected_publisher_logins as _impl

    return _impl(ctx)


def last_reviewed_sha(
    reviews: list[dict[str, Any]],
    *,
    head_sha: str,
    publishers: frozenset[str] | None = None,
) -> str | None:
    """Return the head SHA of the most recent mergeCraft review, if one is recoverable.

    Args:
        reviews: Raw review objects as returned by ``GET /pulls/{n}/reviews``,
            oldest first (GitHub's documented order).
        head_sha: The PR head this run is about to review.
        publishers: The run's expected-publisher logins (``TB-D7``). When given,
            a review must carry the marker **and** be authored by one of them;
            when ``None`` the caller's history is already filtered, so the
            marker alone is matched.

    Returns:
        The ``commit_id`` of the newest mergeCraft-authored review that names a
        different commit than ``head_sha``, or ``None`` when no such review
        exists. A review by anyone else, a review with no ``commit_id``, and a
        review of the current head are all ignored — the first would scope the
        incremental diff to someone else's checkpoint, and the last two cannot
        produce a usable range.
    """
    for review in reversed(reviews or []):
        commit_id = str(review.get("commit_id") or "").strip().lower()
        if not commit_id or not _SHA_RE.match(commit_id):
            continue
        if head_sha and commit_id == head_sha.strip().lower():
            continue
        if not _is_authored_review(review, publishers):
            continue
        return commit_id
    return None


def review_round_index(
    reviews: list[dict[str, Any]],
    *,
    publishers: frozenset[str] | None = None,
) -> int:
    """Return the 1-based review round from prior mergeCraft-authored PR reviews (RC12).

    Counts prior reviews that pass the same authorship rule ``last_reviewed_sha``
    uses, and adds one for the run about to start. This is the single source of
    truth for round-aware budgets (W9.2c).
    """
    prior_rounds = sum(1 for review in reviews or [] if _is_authored_review(review, publishers))
    return prior_rounds + 1


# ``pulls/{n}/reviews`` is paginated at 100 per page; a PR with a longer review
# history would hide the newest mergeCraft review behind the first page.
_REVIEWS_PAGE_SIZE = 100
# A history longer than this is pathological; stop paging and warn rather than
# loop unbounded against a paginating API.
_REVIEWS_MAX_PAGES = 30


async def list_mergecraft_reviews(ctx: ToolContext, *, pull_number: int) -> list[dict[str, Any]]:
    """Return the PR's mergeCraft-authored reviews, oldest first (TB-D7).

    Paginates through the review history (not just the first page), filters it
    through the P-17 authorship rule (marker **and** an expected publisher), and
    warns when the page cap truncates the history. A listing failure returns
    ``[]`` — a missing review history is advisory, never fatal.
    """
    raw: list[dict[str, Any]] = []
    try:
        for page in range(1, _REVIEWS_MAX_PAGES + 1):
            batch = list(
                await ctx.scm.list_reviews(
                    ctx.repo.owner,
                    ctx.repo.name,
                    pull_number,
                    params={"per_page": _REVIEWS_PAGE_SIZE, "page": page},
                )
                or []
            )
            raw.extend(batch)
            if len(batch) < _REVIEWS_PAGE_SIZE:
                break
        else:
            logger.warning(
                "mergeCraft review history: stopped after {} pages for #{}; "
                "the history may be incomplete",
                _REVIEWS_MAX_PAGES,
                pull_number,
            )
    except Exception as err:  # advisory; a missing review history is not fatal
        logger.info("incremental diff: listing prior reviews soft-failed: {}", err)
        return []
    # A review without the marker cannot be mergeCraft's, so skip the publisher
    # lookup entirely when there is nothing to attribute.
    from mergecraft.review.authorship import has_mergecraft_marker, is_mergecraft_authored

    if not any(has_mergecraft_marker(review) for review in raw):
        return []
    publishers = expected_publisher_logins(ctx)
    return [review for review in raw if is_mergecraft_authored(review, publishers=publishers)]


# HS8 — the trusted self-review workflow whose runs carry the run-bound
# checkpoint. The Actions API resolves ``{workflow_id}`` by numeric workflow id
# or by workflow *file name* only — the repo-relative path spelling is answered
# with 404 (#1082) — so the file name is tried first and the path is kept as a
# fallback for recorded doubles that still serve it.
_WORKFLOW_PATH = ".github/workflows/mergecraft.yml"
_WORKFLOW_FILE = _WORKFLOW_PATH.rsplit("/", 1)[-1]
_TRUSTED_RUN_EVENT = "pull_request_target"
# A self-review run that requests changes finishes ``failure`` (its gate step fails
# when mergeCraft would not approve), and it is still a review. Trust comes from the
# event and the workflow path, not from the conclusion; ``cancelled``, ``skipped``,
# ``timed_out`` and runs still in progress carry no completed review.
_TRUSTED_RUN_CONCLUSIONS = frozenset({"success", "failure"})
# How many of the newest trusted runs are probed for a usable evidence artefact
# before the reader gives up (each probe is an Actions API round trip).
_RUN_BOUND_MAX_RUN_PROBES = 5
# The evidence artefact each review rung uploads. ``mergecraft.yml`` names it
# ``mergecraft-evidence-<rung>`` and stores the rung's packet at the artefact
# root as ``packet-<rung>.json`` (``tests/mcp/test_checkout_run_bound_checkpoint.py``
# pins the reader to the workflow's own upload steps). Rungs are listed in the
# order the reader tries them: the last rung that ran is the one whose verdict
# the run recorded, so it goes first.
_EVIDENCE_ARTIFACT_PREFIX = "mergecraft-evidence-"
# ``nous`` stays last so a checkpoint from a run made before the Nous rung was
# replaced by OpenCode Go (2026-10-16) is still readable.
_EVIDENCE_RUNGS = ("claude", "codex", "opencode-go", "nous")


def _packet_member_for(rung: str) -> str:
    """Return the packet file name the ``rung``'s evidence artefact carries (HS8)."""
    return f"packet-{rung}.json"


@dataclass(frozen=True)
class RunBoundReviewState:
    """The run-bound review identity read from trusted workflow runs (HS8).

    ``reviewed_head_sha`` is ``""`` and ``round_index`` is ``0`` when no trusted
    run's evidence was readable — the fail-closed answers. ``progress_comment_id``
    is ``None`` then, so the sticky selector never mistakes an unread checkpoint
    for a fresh one.
    """

    reviewed_head_sha: str = ""
    round_index: int = 0
    progress_comment_id: int | None = None


_UNAVAILABLE_RUN_BOUND_STATE = RunBoundReviewState()


def _as_mapping(value: object) -> Mapping[str, Any]:
    """Return ``value`` when it is a mapping, else an empty one (total coercion)."""
    return value if isinstance(value, Mapping) else {}


def _filter_trusted_runs(runs: object, *, pull_number: int) -> list[dict[str, Any]]:
    """Return the trusted runs for ``pull_number``, newest first (HS8).

    Trusted means a ``pull_request_target`` run that completed (``success`` or
    ``failure``) and names this PR. ``pull_request_target`` always runs the default branch's
    workflow definition, so a workflow added or edited on the PR branch cannot
    produce one — that is the property the checkpoint relies on.
    """
    if not isinstance(runs, list):
        return []
    trusted: list[dict[str, Any]] = []
    for run in runs:
        row = _as_mapping(run)
        if row.get("event") != _TRUSTED_RUN_EVENT:
            continue
        if row.get("conclusion") not in _TRUSTED_RUN_CONCLUSIONS:
            continue
        pull_numbers = {
            _as_mapping(entry).get("number") for entry in row.get("pull_requests") or []
        }
        if pull_number not in pull_numbers:
            continue
        trusted.append(dict(row))
    trusted.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    return trusted


def _describe_run_api_error(err: BaseException) -> str:
    """Return a one-line description of an Actions-API failure (#1082).

    ``str(httpx.HTTPStatusError)`` appends httpx's own docs hint on a second
    line (``For more information check: https://developer.mozilla.org/...``);
    in a job log it reads as if mergeCraft were pointing an Actions 404 at
    web-fetch documentation. Name the status and the request instead.
    """
    if isinstance(err, httpx.HTTPStatusError):
        response = err.response
        reason = response.reason_phrase or "error"
        try:
            request = err.request
        except RuntimeError:
            return f"HTTP {response.status_code} {reason}"
        return f"HTTP {response.status_code} {reason} for {request.method} {request.url}"
    return str(err)


async def _list_mergecraft_workflow_runs(ctx: ToolContext) -> object:
    """List this repo's trusted-event ``mergecraft.yml`` runs (HS8).

    The Actions API resolves ``{workflow_id}`` by numeric workflow id or by
    workflow *file name*; the repo-relative path spelling is answered with 404
    (#1082). The file name is tried first, the path spelling kept as a
    fallback, and a 404 on either form falls through to the next instead of
    aborting the listing. Returns the raw ``workflow_runs`` list; when every
    spelling 404s it warns once naming the real cause (workflow not resolvable
    through the Actions API for this token), and when no spelling yields the
    expected shape it warns once naming the repo — never a silent fallback.
    """
    saw_not_found = False
    for workflow_ref in (_WORKFLOW_FILE, _WORKFLOW_PATH):
        endpoint = f"/repos/{ctx.repo.owner}/{ctx.repo.name}/actions/workflows/{workflow_ref}/runs"
        try:
            payload = await ctx.scm.get(
                endpoint,
                params={"event": _TRUSTED_RUN_EVENT, "per_page": _REVIEWS_PAGE_SIZE},
            )
        except httpx.HTTPStatusError as err:
            if err.response.status_code != 404:
                raise
            saw_not_found = True
            continue
        if isinstance(payload, Mapping) and isinstance(payload.get("workflow_runs"), list):
            return payload["workflow_runs"]
    if saw_not_found:
        # 404 on every ``{workflow_id}`` spelling means the workflow is not
        # resolvable through the Actions API for this token: the file is absent
        # from the repository's default branch (a consumer renamed it) or the
        # run token lacks ``actions: read``. Named once here, not per spelling,
        # and the checkpoint stays fail-closed (HS8 / P-8).
        logger.warning(
            "run-bound checkpoint: listing runs for {}/{} workflow {} returned 404 "
            "Not Found for every Actions-API workflow-id spelling; the workflow "
            "must exist on the repository's default branch and the run token "
            "needs actions: read — checkpoint reuse is skipped",
            ctx.repo.owner,
            ctx.repo.name,
            _WORKFLOW_FILE,
        )
        return None
    # Neither ``{workflow_id}`` spelling produced a mapping carrying a
    # ``workflow_runs`` list. That is an unexpected Actions API shape, not the
    # benign "this PR has no trusted runs" case (which returns an empty list),
    # so it is named once here rather than falling back silently (HS8 / P-8).
    logger.warning(
        "run-bound checkpoint: workflow runs listing for {}/{} returned no "
        "`workflow_runs` list; falling back",
        ctx.repo.owner,
        ctx.repo.name,
    )
    return None


def _packet_from_artifact_zip(
    blob: bytes, *, member: str, artifact_id: int | None = None
) -> dict[str, Any] | None:
    """Return the evidence packet stored as ``member`` inside an artefact zip, or ``None``.

    Total and fail-closed: an unreadable zip, a zip with no ``member``, and a
    member that does not decode to a JSON object each log one warning naming
    the artefact and the reason, then return ``None``. A malformed payload
    degrades to a missing checkpoint, never an exception into the run (HS8 / P-8).
    """
    where = f"artefact {artifact_id}" if artifact_id is not None else "evidence artefact"
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as archive:
            for name in archive.namelist():
                if name.rsplit("/", 1)[-1] != member:
                    continue
                payload = json.loads(archive.read(name))
                if isinstance(payload, dict):
                    return payload
                logger.warning(
                    "run-bound checkpoint: {} member {} is not a JSON object; falling back",
                    where,
                    member,
                )
                return None
    except (OSError, ValueError, zipfile.BadZipFile) as err:
        logger.warning("run-bound checkpoint: {} unreadable: {}; falling back", where, err)
        return None
    # Every loop iteration either returned the packet or returned ``None`` above,
    # so reaching here means no ``member`` was present.
    logger.warning(
        "run-bound checkpoint: {} contains no {} member; falling back",
        where,
        member,
    )
    return None


async def _read_run_evidence_packet(ctx: ToolContext, *, run_id: int) -> dict[str, Any] | None:
    """Read one trusted run's evidence packet from its ``mergecraft-evidence-*`` artefacts.

    A run uploads one artefact per rung that emitted a packet. They are tried
    in ``_EVIDENCE_RUNGS`` order (the last rung that ran first), and the first
    readable packet wins; an unreadable one is named and the next is tried.
    """
    endpoint = f"/repos/{ctx.repo.owner}/{ctx.repo.name}/actions/runs/{run_id}/artifacts"
    listing = await ctx.scm.get(endpoint)
    if not isinstance(listing, Mapping):
        logger.warning(
            "run-bound checkpoint: run {} artefacts listing was not an object; falling back",
            run_id,
        )
        return None
    artifacts = listing.get("artifacts")
    if not isinstance(artifacts, list):
        logger.warning(
            "run-bound checkpoint: run {} artefacts listing has no `artifacts` list; falling back",
            run_id,
        )
        return None
    by_rung: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        row = _as_mapping(artifact)
        name = str(row.get("name") or "")
        rung = name.removeprefix(_EVIDENCE_ARTIFACT_PREFIX)
        if rung == name or rung not in _EVIDENCE_RUNGS or row.get("expired"):
            continue
        by_rung.setdefault(rung, dict(row))
    candidates = [(rung, by_rung[rung]) for rung in _EVIDENCE_RUNGS if rung in by_rung]
    if not candidates:
        logger.warning(
            "run-bound checkpoint: run {} has no unexpired {} artefact; falling back",
            run_id,
            _EVIDENCE_ARTIFACT_PREFIX,
        )
        return None
    for rung, candidate in candidates:
        artifact_id = _coerce_int(candidate.get("id"))
        if artifact_id is None:
            logger.warning(
                "run-bound checkpoint: run {} {} evidence artefact names no id; skipping",
                run_id,
                rung,
            )
            continue
        try:
            blob = await ctx.scm.download_artifact_zip(ctx.repo.owner, ctx.repo.name, artifact_id)
        except Exception as err:
            logger.warning(
                "run-bound checkpoint: artefact {} could not be downloaded: {}",
                artifact_id,
                _describe_run_api_error(err),
            )
            continue
        packet = _packet_from_artifact_zip(
            blob, member=_packet_member_for(rung), artifact_id=artifact_id
        )
        if packet is not None:
            return packet
    return None


def _coerce_int(raw: object) -> int | None:
    """Return ``raw`` as an int when it names one, else ``None`` (total coercion).

    Artefact ids, run ids and the sticky comment id all arrive from JSON, so a
    value a caller mirrored as ``"555"`` is still the id it names.
    """
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw)
    return None


async def recover_run_bound_review_state(
    ctx: ToolContext, *, pull_number: int
) -> RunBoundReviewState:
    """Read the run-bound checkpoint and sticky id from trusted workflow runs (HS8).

    A trusted run is a completed (``success`` or ``failure``)
    ``pull_request_target`` run of ``.github/workflows/mergecraft.yml`` for this PR
    whose evidence artefact names a ``reviewed_head_sha``. The newest such run's
    evidence packet supplies ``reviewed_head_sha`` and ``progress_comment_id``; the
    round index counts that run and every older trusted run. Anything unavailable — an unreadable artefact, an Actions API
    error, no trusted run — is fail-closed (``""`` / ``0`` / ``None``) with one
    warning naming the reason, never a fabricated checkpoint.
    """
    try:
        runs = await _list_mergecraft_workflow_runs(ctx)
    except Exception as err:
        logger.warning(
            "run-bound checkpoint: listing workflow runs failed: {}",
            _describe_run_api_error(err),
        )
        return _UNAVAILABLE_RUN_BOUND_STATE
    trusted = _filter_trusted_runs(runs, pull_number=pull_number)
    if not trusted:
        return _UNAVAILABLE_RUN_BOUND_STATE
    # Newest first: a run that carries no usable evidence artefact (it failed before
    # uploading one, or the artefact expired) is not a round and is skipped; the next
    # older run is tried, up to a bound. One warning is emitted at the fallback, and
    # it names the last probe error so the cause is not lost.
    last_probe_error: str | None = None
    for index, run in enumerate(trusted[:_RUN_BOUND_MAX_RUN_PROBES]):
        run_id = _coerce_int(run.get("id"))
        if run_id is None:
            continue
        try:
            packet = await _read_run_evidence_packet(ctx, run_id=run_id)
        except Exception as err:
            last_probe_error = _describe_run_api_error(err)
            logger.debug(
                "run-bound checkpoint: reading run {} failed: {}", run_id, last_probe_error
            )
            continue
        reviewed_head_sha = str(packet.get("reviewed_head_sha") or "") if packet else ""
        if not reviewed_head_sha:
            if packet is not None:
                logger.warning(
                    "run-bound checkpoint: run {} evidence names no reviewed_head_sha; skipping",
                    run_id,
                )
            continue
        return RunBoundReviewState(
            reviewed_head_sha=reviewed_head_sha,
            # Runs skipped above carried no review; this one and every older one count.
            round_index=len(trusted) - index,
            progress_comment_id=_coerce_int(packet.get("progress_comment_id")) if packet else None,
        )
    detail = f"; last error: {last_probe_error}" if last_probe_error else ""
    logger.warning(
        "run-bound checkpoint: none of the {} newest trusted run(s) for PR #{} carried a "
        "usable evidence artefact; falling back{}",
        min(len(trusted), _RUN_BOUND_MAX_RUN_PROBES),
        pull_number,
        detail,
    )
    return _UNAVAILABLE_RUN_BOUND_STATE


def _is_trusted_self_review_run(ctx: ToolContext) -> bool:
    """Return whether this run is the trusted ``pull_request_target`` self-review (HS8).

    ``PayloadEvent.trigger`` names the PR *action* the workflow ran for
    (``pull_request_synchronize``, ``pull_request_opened``, …), never the
    workflow event itself, so it cannot tell a ``pull_request_target`` run apart
    from a ``pull_request`` one. The ambient ``GITHUB_EVENT_NAME`` is the signal
    the rest of the codebase uses for that distinction (``main`` reads it for the
    operator-owned settings snapshot), and the MCP server runs in-process on the
    run that has it set. A payload that already spells ``pull_request_target`` is
    honoured too, so a recorded payload can drive the trusted path directly.
    """
    if ctx.payload.event.trigger == _TRUSTED_RUN_EVENT:
        return True
    return os.environ.get("GITHUB_EVENT_NAME", "") == _TRUSTED_RUN_EVENT


async def _consume_run_bound_review_state(
    ctx: ToolContext, *, pull_number: int
) -> RunBoundReviewState:
    """Read and record the run-bound checkpoint on the run's tool state (HS8).

    Only the trusted self-review event (``pull_request_target``) consumes it: a
    run that is not the trusted self-review must not adopt another run's
    checkpoint or sticky, so it keeps the fail-closed answer and the
    publisher-set fallback.
    """
    if not _is_trusted_self_review_run(ctx):
        return _UNAVAILABLE_RUN_BOUND_STATE
    state = await recover_run_bound_review_state(ctx, pull_number=pull_number)
    ctx.tool_state.run_bound_progress_comment_id = state.progress_comment_id
    return state


def _round_index(
    run_bound: RunBoundReviewState,
    prior_reviews: list[dict[str, Any]],
    *,
    publishers: frozenset[str],
) -> int:
    """Return the 1-based review round, preferring the run-bound count (HS8).

    The run-bound ``round_index`` counts prior trusted runs, so this run's own
    round is that plus one. With no trusted checkpoint it falls back to the
    publisher-set count (``review_round_index``).
    """
    if run_bound.round_index > 0:
        return run_bound.round_index + 1
    return review_round_index(prior_reviews, publishers=publishers)


def _remote_url_for_cwd(cwd: str) -> str:
    try:
        return read_remote_origin_url(cwd)
    except RuntimeError:
        return ""


def _git_env_for_cwd(cwd: str, token: str) -> tuple[dict[str, str], str]:
    remote_url = _remote_url_for_cwd(cwd)
    return _git_env(token, remote_url=remote_url), remote_url


# GitHub caps ``pulls/{n}/files`` at 100 per page and defaults to 30. This diff
# is the degraded ``api-only`` scope's only view of the change, and a run may
# still reach an approvable verdict from it, so a silently short page would
# approve a PR whose later files were never seen.
_PULL_FILES_PAGE_SIZE = 100
# A PR larger than this is beyond what a review can meaningfully cover; stop
# paging rather than loop unbounded against a paginating API.
_PULL_FILES_MAX_PAGES = 30


async def pull_request_path_expectations(
    ctx: ToolContext, *, pull_number: int, renames: dict[str, str] | None = None
) -> tuple[set[str], set[str]]:
    """Return ``(required, allowed)`` paths for the PR as GitHub reports them.

    The authority a caller-supplied diff is checked against before it may
    establish review scope. ``required`` is the post-image name of every changed
    file — a diff omitting one does not describe this PR. ``allowed`` adds
    rename pre-image names, because ``git diff`` writes a rename as
    ``a/<old> b/<new>`` and only ``<new>`` is the post-image path; counting
    ``<old>`` as required would reject an honest rename. ``renames``, when given,
    is filled with each renamed post-image path's source.
    """
    listing = await list_pull_files(
        ctx.scm,
        ctx.repo.owner,
        ctx.repo.name,
        pull_number,
        page_size=_PULL_FILES_PAGE_SIZE,
        max_pages=_PULL_FILES_MAX_PAGES,
    )
    required: set[str] = set()
    allowed: set[str] = set()
    for f in listing.items:
        filename = str(f.get("filename") or "")
        if filename:
            required.add(filename)
            allowed.add(filename)
        previous = str(f.get("previous_filename") or "")
        if previous:
            allowed.add(previous)
            if renames is not None and filename:
                renames[filename] = previous
    return required, allowed


class _FilesApiDiff(str):
    """Unified diff text plus the omissions the files API forced (TB-D6).

    Subclasses ``str`` so the diff keeps working everywhere a plain ``str`` is
    expected (writing the file, impact extraction), while the checkout callers
    read the recorded omissions off it via ``unreviewable_paths`` and
    ``truncated``.
    """

    unreviewable_paths: list[str]
    truncated: bool

    __slots__ = ("truncated", "unreviewable_paths")

    def __new__(
        cls,
        text: str,
        *,
        unreviewable_paths: list[str],
        truncated: bool,
    ) -> _FilesApiDiff:
        obj = super().__new__(cls, text)
        obj.unreviewable_paths = unreviewable_paths
        obj.truncated = truncated
        return obj


def _quote_diff_path(path: str) -> str:
    """C-quote paths that could split or inject a synthetic Git header."""
    if (
        path == path.strip()
        and " b/" not in path
        and all(32 <= ord(char) < 127 and char not in '\\"' for char in path)
    ):
        return path
    escaped: list[str] = []
    for byte in path.encode("utf-8"):
        if byte < 32 or byte >= 127:
            escaped.append(f"\\{byte:03o}")
        elif chr(byte) in '\\"':
            escaped.append("\\" + chr(byte))
        else:
            escaped.append(chr(byte))
    return '"' + "".join(escaped) + '"'


async def _diff_from_pull_files(ctx: ToolContext, *, pull_number: int) -> _FilesApiDiff:
    """Build a unified diff from the PR files API, following pagination.

    Returns the diff text carrying ``unreviewable_paths`` and ``truncated``
    (TB-D6):

    * ``unreviewable_paths`` — files GitHub reports line changes for but sends
      no ``patch`` for (a text diff too large to inline); the header alone
      cannot be reviewed.
    * ``truncated`` — the page cap was reached, so later files were never seen.

    A file with no ``patch`` **and** no line changes is a binary (or empty)
    header, written as today and not flagged.
    """
    listing = await list_pull_files(
        ctx.scm,
        ctx.repo.owner,
        ctx.repo.name,
        pull_number,
        page_size=_PULL_FILES_PAGE_SIZE,
        max_pages=_PULL_FILES_MAX_PAGES,
    )
    parts: list[str] = []
    unreviewable: list[str] = []
    truncated = listing.incomplete
    for f in listing.items:
        filename = str(f.get("filename") or "")
        # A rename keeps its source on the ``a/`` side, as ``git diff`` writes it, so
        # the pre-image is never lost to readers of the header.
        previous = str(f.get("previous_filename") or "") or filename
        old_image = _quote_diff_path(f"a/{previous}")
        new_image = _quote_diff_path(f"b/{filename}")
        parts.append(f"diff --git {old_image} {new_image}\n")
        if previous != filename:
            parts.append(f"rename from {_quote_diff_path(previous)}\n")
            parts.append(f"rename to {_quote_diff_path(filename)}\n")
        patch = f.get("patch")
        if patch:
            parts.append(patch + "\n")
        elif filename and _line_change_count(f) > 0:
            # GitHub omits ``patch`` for binary files *and* for text diffs
            # too large to inline; the line counts tell them apart.
            unreviewable.append(filename)
    if truncated:
        logger.warning(
            "api-only diff: stopped after {} pages of pull files for #{}; "
            "the diff may be incomplete",
            _PULL_FILES_MAX_PAGES,
            pull_number,
        )
    return _FilesApiDiff("".join(parts), unreviewable_paths=unreviewable, truncated=truncated)


def _line_change_count(file: Mapping[str, Any]) -> int:
    """Return ``additions + deletions`` for a files-API entry, tolerating junk."""
    total = 0
    for key in ("additions", "deletions"):
        try:
            total += int(file.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return total


def _append_diff_degradations(reason: str, *, truncated: bool, unreviewable: list[str]) -> str:
    """Append recorded files-API omissions (TB-D6) to a degradation reason."""
    notes = [reason.rstrip().removesuffix(".")]
    if truncated:
        notes.append(f"the files-API diff was truncated at the {_PULL_FILES_MAX_PAGES}-page cap")
    if unreviewable:
        notes.append(f"{len(unreviewable)} file(s) had no inline patch and are unreviewable")
    return "; ".join(notes) + "."


def _files_api_diff_reason(
    *,
    diff_detail: str,
    base_fetch_failure: str | None,
    truncated: bool,
    unreviewable: list[str],
) -> str:
    """Reason naming a git-diff failure and the base-fetch state (TB-D5/TB-D6)."""
    if base_fetch_failure is None:
        base_state = "the base fetch had succeeded, so the base ref was available"
    else:
        base_state = f"the base fetch had already failed ({base_fetch_failure})"
    reason = (
        f"the local `git diff` failed ({diff_detail}) while {base_state}; the "
        f"review diff is built from the GitHub files API ({FILES_API_DIFF_SCOPE}), "
        "not from the local checkout"
    )
    return _append_diff_degradations(reason, truncated=truncated, unreviewable=unreviewable)


def _depth_flags(cwd: str) -> list[str]:
    """``--depth=1000`` for a shallow clone only; a full clone must stay full."""
    return ["--depth=1000"] if _is_shallow_repository(cwd) else []


def _stale_base_reason(base_fetch_failure: str) -> str:
    """Reason for a local diff taken against a base ref that could not be refreshed."""
    return (
        f"the base fetch failed ({base_fetch_failure}), so the local diff was "
        "computed against a possibly stale base ref and may include unrelated "
        "base-branch changes"
    )


def _fetch_head_with_retry(
    *,
    cwd: str,
    pull_number: int,
    local_branch: str,
    git_token: str,
) -> tuple[bool, str | None]:
    """Fetch PR head; retry once on transient failure, never on auth-class (D3)."""
    env, remote_url = _git_env_for_cwd(cwd, git_token)
    refspec = f"pull/{pull_number}/head:{local_branch}"
    last_err: str | None = None
    detached = False
    for attempt in range(2):
        try:
            _run_git(
                ["fetch", "--no-tags", "origin", refspec],
                cwd=cwd,
                env=env,
                remote_url=remote_url or None,
            )
            return True, None
        except RuntimeError as err:
            last_err = str(err)
            if _is_auth_failure(last_err):
                break
            lowered = last_err.lower()
            if not detached and "refusing to fetch into branch" in lowered:
                # A prior checkout_pr may have left HEAD on local_branch; detach
                # before retrying so the fetch target is not the current HEAD.
                detached = True
                try:
                    _run_git(["checkout", "--detach", "HEAD"], cwd=cwd)
                except RuntimeError as detach_err:
                    last_err = str(detach_err)
                continue
            if attempt == 1:
                break
    return False, last_err


def _write_incremental_diff(
    *,
    cwd: str,
    temp: str,
    pull_number: int,
    prior_sha: str,
    git_token: str,
    ignore: ReviewIgnore | None = None,
    pr_changed_paths: list[str] | None = None,
) -> IncrementalDiffResult:
    """Write the diff since ``prior_sha`` and report an explicit status.

    The caller advertises ``incrementalDiffPath`` only when ``status == "ok"``,
    so a promised file always exists. ``empty`` and ``unavailable`` come with a
    reason the tool result carries verbatim — a reviewer that is told *why*
    there is no incremental range can decide whether to fall back to the full
    diff, instead of guessing from an absent key.
    """
    try:
        _run_git(["cat-file", "-e", f"{prior_sha}^{{commit}}"], cwd=cwd)
    except RuntimeError:
        env, remote_url = _git_env_for_cwd(cwd, git_token)
        try:
            _run_git(
                ["fetch", "--no-tags", *_depth_flags(cwd), "origin", prior_sha],
                cwd=cwd,
                env=env,
                remote_url=remote_url or None,
            )
            _run_git(["cat-file", "-e", f"{prior_sha}^{{commit}}"], cwd=cwd)
        except RuntimeError as err:
            logger.info("incremental diff: prior sha {} unreachable: {}", prior_sha, err)
            return IncrementalDiffResult(
                status="unavailable",
                prior_sha=prior_sha,
                reason=(
                    f"the last reviewed commit {prior_sha[:12]} is not reachable in this "
                    "checkout (shallow clone or rewritten history)"
                ),
            )
    try:
        diff = _run_git(["diff", "--merge-base", prior_sha, "HEAD"], cwd=cwd)
    except RuntimeError as err:
        logger.info("incremental diff: range diff soft-failed: {}", err)
        return IncrementalDiffResult(
            status="unavailable",
            prior_sha=prior_sha,
            reason=f"git diff against {prior_sha[:12]} failed: {err}",
        )
    if not diff.strip():
        logger.info("incremental diff: no changes since {}; omitting path", prior_sha)
        return IncrementalDiffResult(
            status="empty",
            prior_sha=prior_sha,
            reason=f"no changes since the last reviewed commit {prior_sha[:12]}",
        )
    if ignore is not None and ignore.active:
        # Judge against the whole PR, not just this range: a generator config reviewed
        # in an earlier round still keeps its generated output in scope now.
        diff = filter_diff(diff, ignore, changed_paths=pr_changed_paths).text
        if not diff.strip():
            return IncrementalDiffResult(
                status="empty",
                prior_sha=prior_sha,
                reason=(
                    f"every change since the last reviewed commit {prior_sha[:12]} is in "
                    "files ignored by config"
                ),
            )
    path = str(Path(temp) / f"pr-{pull_number}-incremental.diff")
    Path(path).write_text(diff, encoding="utf-8")
    return IncrementalDiffResult(
        status="ok",
        prior_sha=prior_sha,
        path=path,
        changed_paths=tuple(changed_paths_in_diff(diff)),
    )


def _apply_diff_budget(
    ctx: ToolContext, diff_text: str, *, unreviewable: list[str]
) -> tuple[str, list[str]]:
    """Bound the delivered diff by whole files and retain every omitted path.

    Args:
        ctx (ToolContext): Run context carrying the trusted budget snapshot.
        diff_text (str): Diff after ignore-path filtering.
        unreviewable (list[str]): Existing files whose patches were unavailable.

    Returns:
        tuple[str, list[str]]: Bounded diff and all files still unreviewable.
    """
    from mergecraft.config.settings_snapshot import repo_settings_from_context
    from mergecraft.utils.run_bounds import apply_diff_line_budget, resolve_run_bounds

    bounds = (
        ctx.budget_tracker.bounds
        if ctx.budget_tracker is not None
        else resolve_run_bounds(settings=repo_settings_from_context(ctx))
    )
    reduced, omission = apply_diff_line_budget(diff_text, max_lines=bounds.max_diff_lines)
    if omission is None:
        return diff_text, unreviewable
    ctx.tool_state.diff_budget_reason = omission.reason
    return reduced, list(dict.fromkeys([*unreviewable, *omission.omitted_paths]))


def _record_delivered_diff(
    ctx: ToolContext, diff_text: str, *, unreviewable: list[str], truncated: bool
) -> None:
    """Record the diff this checkout built and what the files API could not deliver.

    The coverage accounting at the end of the run reads it: the hunks in ``diff_text``
    are the universe, ``unreviewable`` files had line changes but no patch, and
    ``truncated`` means later files were never listed.
    """
    record = ctx.tool_state.coverage
    record.authoritative_diff = str(diff_text)
    record.unreviewable_paths = list(unreviewable)
    record.diff_truncated = truncated


def _apply_review_ignore(
    ctx: ToolContext, diff_text: str, *, unreviewable: list[str], truncated: bool
) -> tuple[str, list[str], list[str]]:
    """Drop files ignored by config from the reviewer's diff (#1109).

    Returns ``(diff, unreviewable, ignored)``: the diff without the ignored file
    sections, the unreviewable paths that are still in scope, and the ignored paths.
    The filtered diff is what the coverage gate accounts against, so an ignored file
    is out of scope rather than unread. The ignored paths are recorded on the tool
    state for the review body.

    A filter that would leave nothing in scope never yields an empty review that can
    approve. When the diff is complete, every changed file is provably ignored: the
    run records the ``skip (ignorePaths)`` triage tier, which keeps
    ``mergecraft-approval`` neutral whatever the agent submits. When the files-API
    listing was truncated, the change set is unknown, so nothing is filtered.
    """
    ignore = ctx.tool_state.review_ignore
    if not isinstance(ignore, ReviewIgnore) or not ignore.active:
        return str(diff_text), list(unreviewable), []
    filtered = filter_diff(str(diff_text), ignore, changed_paths=unreviewable)
    changed = [*filtered.changed_paths, *unreviewable]
    sources = rename_sources(str(diff_text))
    ignored = list(filtered.ignored_paths)
    kept_unreviewable: list[str] = []
    for path in unreviewable:
        named = [path, sources[path]] if path in sources else [path]
        if ignore.all_ignored(named, changed_paths=changed):
            ignored.append(path)
        else:
            kept_unreviewable.append(path)
    ignored = list(dict.fromkeys(ignored))
    if ignored and not filtered.text.strip() and not kept_unreviewable:
        if truncated:
            logger.warning(
                "ignore_paths: every listed file is ignored but the listing was truncated; "
                "reviewing the unfiltered diff"
            )
            return str(diff_text), list(unreviewable), []
        _record_all_ignored_skip(ctx, ignored)
    if ignored:
        ctx.tool_state.ignored_review_paths = list(
            dict.fromkeys([*ctx.tool_state.ignored_review_paths, *ignored])
        )
        logger.info(
            "ignore_paths: {} changed file(s) left out of the review diff: {}",
            len(ignored),
            ", ".join(ignored[:10]),
        )
    return filtered.text, kept_unreviewable, ignored


def _record_all_ignored_skip(ctx: ToolContext, ignored: list[str]) -> None:
    """Record the ``skip (ignorePaths)`` tier: nothing in scope, so approval stays neutral."""
    from mergecraft.classify.triage import TriageDecision

    current = ctx.tool_state.triage
    if getattr(current, "tier", None) == "skip":
        return
    reason = f"nothing to review: all {len(ignored)} changed file(s) are ignored by config"
    ctx.tool_state.triage = TriageDecision(tier="skip", recognizer="ignorePaths", reason=reason)
    logger.warning("» Tier: skip (ignorePaths) — {}", reason)


_IGNORED_PATHS_NOTE = (
    "These changed files match the operator's ignore_paths / review.ignorePaths and were "
    "left out of diffPath. They are not reviewed (ignored by config): do not read them or "
    "report findings on them."
)


def _annotate_review_round(
    result: dict[str, Any],
    *,
    round_index: int,
    ctx: ToolContext,
) -> None:
    """Expose round index and cap metadata for the reviewing agent (#1166)."""
    from mergecraft.config.settings_snapshot import repo_settings_from_context
    from mergecraft.review.round_cap import max_review_rounds, review_round_cap_exceeded

    settings = repo_settings_from_context(ctx)
    cap = max_review_rounds(settings)
    result["reviewRoundIndex"] = round_index
    result["maxReviewRounds"] = cap
    result["reviewRoundCapExceeded"] = review_round_cap_exceeded(round_index=round_index, cap=cap)


def _annotate_ignored(result: dict[str, Any], ignored: list[str]) -> None:
    if ignored:
        result["ignoredPaths"] = ignored
        result["ignoredPathsNote"] = _IGNORED_PATHS_NOTE


def get_git_status(cwd: str) -> str:
    """Return porcelain status for *cwd* (monkeypatch hook for tests and callers)."""
    return _run_git(["status", "--porcelain"], cwd=cwd).strip()


async def _verify_files_api_head(ctx: ToolContext, *, pull_number: int, head_sha: str) -> None:
    """The files endpoint follows a moving PR, so verify its head after reading."""
    current = await ctx.scm.get_pull(ctx.repo.owner, ctx.repo.name, pull_number)
    current_sha = (current.get("head") or {}).get("sha") or ""
    if not head_sha or current_sha.lower() != head_sha.lower():
        msg = (
            f"PR #{pull_number} head changed or could not be verified while reading "
            "its files; retry checkout before reviewing this revision."
        )
        raise RuntimeError(msg)


def checkout_pr_tool(ctx: ToolContext) -> ToolSpec:
    async def _preflight(params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        params = normalize_pull_number_aliases(params, _CHECKOUT_PR_INPUT_SCHEMA)
        pull_number = int(params["pull_number"])
        state = primary_repo_state(ctx.tool_state)
        cwd = state.dir

        dirty = await run_blocking(get_git_status, cwd)
        if dirty:
            msg = (
                f"cannot checkout PR #{pull_number} while the working tree has "
                f"uncommitted changes. dirty paths:\n{dirty}"
            )
            raise RuntimeError(msg)
        # TB-D4 — refuse a PR the run was not bound to. The bound number lives on
        # the run's **bound** event (``_resolve_credentials`` writes the fetched
        # ``pull_request`` onto ``ctx.gh_event``); the resolved payload therefore
        # is empty for a comment-on-PR and a PR-naming ``workflow_dispatch``,
        # whose ``issue_number`` is never set — reading the payload alone left
        # the guard inert for dispatches. Prefer the bound event, then fall back
        # to the payload so a run with no bound number is unchanged.
        bound_pr = ctx.gh_event.get("pull_request") if isinstance(ctx.gh_event, dict) else None
        bound_number: int | None = (
            bound_pr.get("number")
            if isinstance(bound_pr, dict) and isinstance(bound_pr.get("number"), int)
            else None
        )
        if bound_number is None:
            bound_number = ctx.payload.event.issue_number
        if bound_number is not None and pull_number != bound_number:
            msg = (
                f"refusing to check out PR #{pull_number}: this run is bound to "
                f"PR #{bound_number}, the pull request under review."
            )
            raise RuntimeError(msg)

        pr = await ctx.scm.get_pull(ctx.repo.owner, ctx.repo.name, pull_number)
        # Use the same head/base repository identity comparison as preflight.
        is_fork = is_fork_pull_request({"pull_request": pr})

        # TB-D4 — refuse a fork PR on a run that holds trusted execution or
        # authority trust. Downgrading mid-run cannot un-run setup or un-mint
        # credentials, so this must refuse, not merely downgrade.
        if is_fork and (ctx.trust_tier == "trusted" or ctx.authority_trust == "trusted"):
            msg = (
                f"refusing to check out PR #{pull_number}: it is a fork pull request "
                "but this run holds trusted execution or authority trust."
            )
            raise RuntimeError(msg)

        return pull_number, pr

    async def _checkout(pull_number: int, pr: dict[str, Any]) -> dict[str, Any]:
        state = primary_repo_state(ctx.tool_state)
        cwd = state.dir
        prior_reviews: list[dict[str, Any]] = []
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        head_ref = head.get("ref") or ""
        head_sha = head.get("sha") or ""
        base_ref = base.get("ref") or ""
        is_fork = is_fork_pull_request({"pull_request": pr})

        # HS8 — read the run-bound checkpoint once and record the sticky id on
        # the tool state so HS1's selection can use it. Fail-closed when the
        # trusted evidence is unavailable; the publisher scan below then applies.
        run_bound = await _consume_run_bound_review_state(ctx, pull_number=pull_number)

        local_branch = f"pr-{pull_number}"

        # Fetch PR head into local_branch. checkout_pr can run more than once
        # against the same shared workspace within a single job (e.g. a Nous
        # review, then a Codex fallback both calling checkout_pr against
        # /github/workspace). When a prior call left HEAD on local_branch,
        # ``_fetch_head_with_retry`` detaches before retrying on the
        # "refusing to fetch into branch" error — safe because the dirty check
        # above already guarantees no uncommitted work to lose.
        fetched, fetch_err = await run_blocking(
            _fetch_head_with_retry,
            cwd=cwd,
            pull_number=pull_number,
            local_branch=local_branch,
            git_token=ctx.git_token,
        )
        temp = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
        diff_path = str(Path(temp) / f"pr-{pull_number}.diff")

        if not fetched:
            fetch_degraded = degraded_checkout_reason(
                detail=(fetch_err or "git fetch failed").splitlines()[0]
            )
            fetch_files_diff = await _diff_from_pull_files(ctx, pull_number=pull_number)
            await _verify_files_api_head(ctx, pull_number=pull_number, head_sha=head_sha)
            fetch_truncated = fetch_files_diff.truncated
            fetch_diff, fetch_unreviewable, fetch_ignored = _apply_review_ignore(
                ctx,
                fetch_files_diff,
                unreviewable=fetch_files_diff.unreviewable_paths,
                truncated=fetch_truncated,
            )
            fetch_diff, fetch_unreviewable = _apply_diff_budget(
                ctx, fetch_diff, unreviewable=fetch_unreviewable
            )
            fetch_degraded = _append_diff_degradations(
                fetch_degraded, truncated=fetch_truncated, unreviewable=fetch_unreviewable
            )
            warning(fetch_degraded)
            Path(diff_path).write_text(fetch_diff, encoding="utf-8")
            _record_delivered_diff(
                ctx, fetch_diff, unreviewable=fetch_unreviewable, truncated=fetch_truncated
            )
            state.issue_number = pull_number
            state.checkout_sha = head_sha
            from mergecraft.mcp.review_context import hydrate_review_context
            from mergecraft.mcp.verdict import ReviewPhase, register_review_scope

            register_review_scope(
                ctx.tool_state,
                diff_path=diff_path,
                provenance="api",
                review_scope=API_ONLY_SCOPE,
            )
            await run_blocking_cleanup(_rebaseline_config_after_checkout, ctx)
            prior_reviews = await list_mergecraft_reviews(ctx, pull_number=pull_number)
            publishers = expected_publisher_logins(ctx) if prior_reviews else frozenset()
            round_index = _round_index(run_bound, prior_reviews, publishers=publishers)
            ctx.tool_state.review_round_index = round_index
            result: dict[str, Any] = {
                "pullNumber": pull_number,
                "remoteBranch": head_ref,
                "base": base_ref,
                "headSha": head_sha,
                "checkoutSha": head_sha,
                "isFork": is_fork,
                "diffPath": diff_path,
                "title": pr.get("title"),
                "url": pr.get("html_url"),
                "scope": API_ONLY_SCOPE,
                "degraded": fetch_degraded,
                "reviewPhase": ReviewPhase.ESTABLISH_SCOPE.value,
                "incrementalDiffStatus": "unavailable",
                "incrementalDiffReason": (
                    "the PR head could not be fetched locally, so no incremental "
                    "range can be computed in api-only scope"
                ),
            }
            if fetch_unreviewable:
                result["unreviewablePaths"] = fetch_unreviewable
            if fetch_truncated:
                result["diffTruncated"] = True
            _annotate_ignored(result, fetch_ignored)
            _annotate_review_round(
                result,
                round_index=round_index,
                ctx=ctx,
            )

            await hydrate_review_context(
                ctx,
                round_index=round_index,
                incremental_changed_paths=None,
            )
            logger.warning(
                "checked out PR #{} in {} scope (head fetch failed)",
                pull_number,
                API_ONLY_SCOPE,
            )
            return result

        # The API lookup and refs/pull/N/head fetch can straddle a push. Bind
        # the checkout to the verified immutable object before exposing scope.
        checkout_sha = (
            await run_blocking(
                _run_git, ["rev-parse", "--verify", f"{local_branch}^{{commit}}"], cwd=cwd
            )
        ).strip()
        if head_sha and checkout_sha.lower() != head_sha.lower():
            msg = (
                f"PR #{pull_number} head changed between the API lookup and fetch; "
                "retry checkout before reviewing this revision."
            )
            raise RuntimeError(msg)
        try:
            await run_blocking(_run_git, ["checkout", "-B", local_branch, checkout_sha], cwd=cwd)
        except BaseException:
            # Cancellation can arrive after Git changes the tree but before its
            # worker returns. Join the boundary re-pin while retaining the lock;
            # the outer handler still invalidates all authoritative review proof.
            try:
                await run_blocking_cleanup(_rebaseline_config_after_checkout, ctx)
            except BaseException as cleanup_error:
                logger.warning(
                    "checkout rebaseline cleanup failed ({}); preserving checkout failure",
                    type(cleanup_error).__name__,
                )
            raise
        # Configuration and tree bytes may change at this controlled boundary.
        # Re-pin their hashes before later API calls can fail or be cancelled;
        # the run's trusted settings/policy values remain pinned across retries.
        await run_blocking_cleanup(_rebaseline_config_after_checkout, ctx)
        # Ensure base is available for merge-base diffs
        base_env, base_remote_url = await run_blocking(_git_env_for_cwd, cwd, ctx.git_token)
        base_fetch_failure: str | None = None
        try:
            (
                await run_blocking(
                    _run_git,
                    [
                        "fetch",
                        "--no-tags",
                        *(await run_blocking(_depth_flags, cwd)),
                        "origin",
                        f"{base_ref}:refs/remotes/origin/{base_ref}",
                    ],
                    cwd=cwd,
                    env=base_env,
                    remote_url=base_remote_url or None,
                )
            )
        except Exception as err:
            base_fetch_failure = str(err).splitlines()[0] if str(err) else "git fetch failed"
            logger.info("base fetch soft-failed: {}", err)
        if base_ref:
            try:
                await run_blocking(ensure_local_base_branch_alias, cwd=cwd, base_ref=base_ref)
            except Exception as err:
                logger.info("base branch alias soft-failed: {}", err)

        state.issue_number = pull_number
        state.checkout_sha = checkout_sha
        state.push_dest = StoredPushDest(
            remote_name="origin",
            remote_branch=head_ref,
            local_branch=local_branch,
        )
        try:
            state.push_url = await run_blocking(read_remote_origin_url, cwd)
        except RuntimeError:
            if is_fork and head.get("repo"):
                clone_url = (head["repo"].get("clone_url") or "").rstrip("/")
                state.push_url = clone_url or f"https://github.com/{ctx.repo.owner}/{ctx.repo.name}"
            else:
                state.push_url = f"https://github.com/{ctx.repo.owner}/{ctx.repo.name}"

        # Write a basic diff file for reviewers. A failed ``git diff`` falls back
        # to the GitHub files API; that fallback is labelled as exactly what it
        # is (TB-D5) and its omissions are recorded on the result (TB-D6).
        diff_failure: str | None = None
        unreviewable: list[str] = []
        diff_truncated = False
        try:
            from mergecraft.classify.triage import trusted_check_apps
            from mergecraft.config.settings_snapshot import repo_settings_from_context

            queue_apps = repo_settings_from_context(ctx).review.merge_queue.trusted_check_apps
            if trusted_check_apps(queue_apps):
                merge_base = (
                    await run_blocking(
                        _run_git,
                        ["merge-base", "--all", f"origin/{base_ref}", checkout_sha],
                        cwd=cwd,
                    )
                ).strip()
                if re.fullmatch(r"[0-9a-f]{40}", merge_base):
                    state.reviewed_merge_base = merge_base
            diff_args = (
                ["diff", state.reviewed_merge_base, checkout_sha]
                if state.reviewed_merge_base
                else ["diff", "--merge-base", f"origin/{base_ref}", "HEAD"]
            )
            diff = await run_blocking(_run_git, diff_args, cwd=cwd)
        except Exception as err:
            state.reviewed_merge_base = None
            diff_failure = str(err).splitlines()[0] if str(err) else "git diff failed"
            files_diff = await _diff_from_pull_files(ctx, pull_number=pull_number)
            await _verify_files_api_head(ctx, pull_number=pull_number, head_sha=checkout_sha)
            diff = files_diff
            unreviewable = files_diff.unreviewable_paths
            diff_truncated = files_diff.truncated
        pr_changed_paths = list(
            dict.fromkeys([*filter_diff(diff, None).changed_paths, *unreviewable])
        )
        diff, unreviewable, ignored_paths = _apply_review_ignore(
            ctx, diff, unreviewable=unreviewable, truncated=diff_truncated
        )
        diff, unreviewable = _apply_diff_budget(ctx, diff, unreviewable=unreviewable)
        Path(diff_path).write_text(diff, encoding="utf-8")
        _record_delivered_diff(ctx, diff, unreviewable=unreviewable, truncated=diff_truncated)
        from mergecraft.mcp.verdict import register_review_scope

        degraded_reason: str | None = None
        if diff_failure is not None:
            degraded_reason = _files_api_diff_reason(
                diff_detail=diff_failure,
                base_fetch_failure=base_fetch_failure,
                truncated=diff_truncated,
                unreviewable=unreviewable,
            )
            warning(degraded_reason)
            register_review_scope(
                ctx.tool_state,
                diff_path=diff_path,
                provenance="api",
                review_scope=FILES_API_DIFF_SCOPE,
            )
        else:
            if base_fetch_failure is not None:
                # The diff ran, but against whatever ``origin/<base>`` was already
                # local; a stale merge-base can pull base commits into the review.
                degraded_reason = _stale_base_reason(base_fetch_failure)
                warning(degraded_reason)
            register_review_scope(ctx.tool_state, diff_path=diff_path, provenance="checkout")
        await run_blocking_cleanup(_rebaseline_config_after_checkout, ctx)

        result = {
            "pullNumber": pull_number,
            "localBranch": local_branch,
            "remoteBranch": head_ref,
            "base": base_ref,
            "headSha": state.checkout_sha,
            "isFork": is_fork,
            "diffPath": diff_path,
            "title": pr.get("title"),
            "url": pr.get("html_url"),
        }
        if degraded_reason is not None:
            result["degraded"] = degraded_reason
        if unreviewable:
            result["unreviewablePaths"] = unreviewable
        if diff_truncated:
            result["diffTruncated"] = True
        _annotate_ignored(result, ignored_paths)

        prior_reviews = await list_mergecraft_reviews(ctx, pull_number=pull_number)
        publishers = expected_publisher_logins(ctx) if prior_reviews else frozenset()
        round_index = _round_index(run_bound, prior_reviews, publishers=publishers)
        ctx.tool_state.review_round_index = round_index

        # A re-review should pay for the new commits, not the whole PR. Compute
        # the range whenever a prior reviewed sha is recoverable — regardless of
        # whether ``select_mode`` has run yet, because #1017 showed a reviewer
        # that never calls ``select_mode`` still needs the checkpointed scope.
        # The run-bound checkpoint (HS8, read from the trusted persisted packet)
        # outranks the publisher scan when a trusted run named a head.
        prior_sha = run_bound.reviewed_head_sha or (
            last_reviewed_sha(
                prior_reviews,
                head_sha=state.checkout_sha or "",
                publishers=publishers,
            )
            or ""
        )
        if prior_sha:
            incremental = await run_blocking(
                _write_incremental_diff,
                cwd=cwd,
                temp=temp,
                pull_number=pull_number,
                prior_sha=prior_sha,
                git_token=ctx.git_token,
                ignore=(
                    ctx.tool_state.review_ignore
                    if isinstance(ctx.tool_state.review_ignore, ReviewIgnore)
                    else None
                ),
                pr_changed_paths=pr_changed_paths,
            )
            result["lastReviewedSha"] = prior_sha
            result["incrementalDiffStatus"] = incremental.status
            if incremental.status == "ok" and incremental.path is not None:
                incremental_text = Path(incremental.path).read_text(encoding="utf-8")
                incremental_text, incremental_omitted = _apply_diff_budget(
                    ctx, incremental_text, unreviewable=[]
                )
                Path(incremental.path).write_text(incremental_text, encoding="utf-8")
                if incremental_omitted:
                    unreviewable = list(dict.fromkeys([*unreviewable, *incremental_omitted]))
                    ctx.tool_state.coverage.unreviewable_paths = unreviewable
                    result["unreviewablePaths"] = unreviewable
                state.last_reviewed_sha = prior_sha
                state.incremental_diff_path = incremental.path
                state.incremental_changed_paths = list(incremental.changed_paths)
                result["incrementalDiffPath"] = incremental.path
                logger.info(
                    "incremental diff for PR #{} since {} -> {} ({} file(s))",
                    pull_number,
                    prior_sha,
                    incremental.path,
                    len(incremental.changed_paths),
                )
            else:
                result["incrementalDiffReason"] = incremental.reason or "no incremental range"
                logger.info(
                    "incremental diff for PR #{} since {}: {} ({})",
                    pull_number,
                    prior_sha,
                    incremental.status,
                    incremental.reason,
                )
        else:
            result["incrementalDiffStatus"] = "unavailable"
            result["incrementalDiffReason"] = (
                "no prior mergeCraft review checkpoint is recoverable for this PR"
            )

        # S6 #94 — impact-path extraction (default off behind analyzers.impact).
        # Emitted only when enabled; returns None (-> no key) when the diff
        # has zero declarations, matching the incrementalDiffPath convention.
        # The analyzers.impact toggle is read from the PR's pinned (base-side) settings,
        # never the head checkout (#942). Impact requires the pinned toggle and
        # the effective analyzer policy, mirroring run_analyzers_tool's gate
        # (mcp/analyzers.py). ast-grep execution itself is further gated
        # on ctx.trust_tier inside write_impact, which fails closed (omits
        # impactPath) when sandbox isolation for an untrusted checkout isn't
        # available (D7).
        try:
            repo_root = Path(cwd)
            from mergecraft.analyzers.settings_pin import resolve_pinned_analyzer_settings_async

            pinned_settings = (
                await resolve_pinned_analyzer_settings_async(ctx, repo_root)
            ).settings
            if pinned_settings.impact and analyzers_enabled(ctx):
                ast_grep_binary = await run_blocking(resolve_ast_grep_binary)
                if ast_grep_binary is None:
                    logger.info(
                        "impactPath skipped for PR #{}: managed ast-grep binary unavailable",
                        pull_number,
                    )
                else:
                    impact_result = await run_blocking(
                        write_impact,
                        diff,
                        cwd,
                        temp,
                        pull_number,
                        ast_grep_binary=ast_grep_binary,
                        tier=ctx.trust_tier,
                    )
                    if impact_result is not None:
                        result["impactPath"] = impact_result["impactPath"]
                        result["impactTruncated"] = impact_result["impactTruncated"]
                        result["impactDeclarationCount"] = impact_result["impactDeclarationCount"]
                        logger.info(
                            "impactPath for PR #{} -> {} ({} declarations, truncated={})",
                            pull_number,
                            impact_result["impactPath"],
                            impact_result["impactDeclarationCount"],
                            impact_result["impactTruncated"],
                        )
        except Exception as imp_err:
            logger.info("impact extraction soft-failed: {}", imp_err)

        try:
            from mergecraft.review.linked_repos import (
                linked_repo_review_with_payload,
                operator_authorized_linked_repos,
            )

            base_lookup = await run_blocking(
                _base_linked_repo_manifest,
                cwd=cwd,
                base_ref=base_ref,
                base_fetch_failure=base_fetch_failure,
            )
            # Recorded for the ``xrepo`` policy evidence producer, which reads
            # what this checkout computed instead of walking git a second time.
            ctx.tool_state.linked_repo_base_manifest = base_lookup
            ctx.tool_state.linked_repo_review = None
            linked = linked_repo_review_with_payload(
                Path(cwd),
                authorized_repos=operator_authorized_linked_repos(),
                base_manifest=base_lookup.manifest,
                base_manifest_error=base_lookup.unreadable_reason,
            )
            if linked is not None:
                ctx.tool_state.linked_repo_review = linked[0]
                result.update(linked[1])
        except Exception as xrepo_err:
            logger.info("linked-repo review soft-failed: {}", xrepo_err)

        _annotate_review_round(
            result,
            round_index=round_index,
            ctx=ctx,
        )
        logger.info("checked out PR #{} -> {}", pull_number, local_branch)
        from mergecraft.mcp.review_context import hydrate_review_context

        await hydrate_review_context(
            ctx,
            round_index=round_index,
            incremental_changed_paths=state.incremental_changed_paths,
        )
        return result

    async def _run_locked(params: dict[str, Any]) -> dict[str, Any]:
        if ctx.tool_state.review is not None:
            msg = "cannot restart checkout after this run has published a review"
            raise RuntimeError(msg)
        # Read-only refusals preserve the last valid review. From the first
        # workspace mutation onward, every error invalidates partial evidence.
        pull_number, pr = await _preflight(params)
        # Publication can complete while the API lookup above is awaiting.
        if ctx.tool_state.review is not None:
            msg = "cannot restart checkout after this run has published a review"
            raise RuntimeError(msg)
        baseline = ctx.tool_state.review_tree_baseline
        if baseline is not None:
            await run_blocking(baseline.before_checkout)
            # Publication may also complete during the offloaded integrity hash.
            # Refuse before invalidating its receipt or changing the checkout.
            if ctx.tool_state.review is not None:
                msg = "cannot restart checkout after this run has published a review"
                raise RuntimeError(msg)
        invalidate_checkout_review_state(ctx.tool_state)
        try:
            result = await _checkout(pull_number, pr)
            # Reads that arrived while the workspace was changing cannot attest
            # the newly established scope. Keep their audit records only.
            ctx.tool_state.review_scope_tool_call_start = len(ctx.tool_state.tool_calls)
            return result
        except BaseException:
            # Errors and cancellation can happen after HEAD or partial scope
            # state changed. Neither the previous nor partial new proof is valid.
            invalidate_checkout_review_state(ctx.tool_state)
            raise

    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        async with ctx.tool_state.checkout_operation_lock:
            return await _run_locked(params)

    return tool(
        name="checkout_pr",
        tool_class=ToolClass.SCOPE,
        mutates=True,
        timeout_ms=600_000,
        description=(
            "Checkout a pull request branch locally. Returns diffPath pointing to the "
            "formatted diff file. On a re-review — a PR that already has a mergeCraft "
            "review on an earlier head — also reports incrementalDiffStatus "
            "(ok|empty|unavailable) and, when ok, incrementalDiffPath (changes since "
            "that review) plus lastReviewedSha; incrementalDiffReason explains empty or "
            "unavailable. When the repo config enables analyzers.impact, also returns "
            "impactPath pointing to a JSON file listing declaration-level reference "
            "leads for the changed files."
        ),
        input_schema=_CHECKOUT_PR_INPUT_SCHEMA,
        execute=execute(_run, "checkout_pr"),
    )
