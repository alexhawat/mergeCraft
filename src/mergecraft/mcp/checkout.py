"""checkout_pr tool — fetch PR branch and write formatted diff."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.impact import resolve_ast_grep_binary, write_impact
from mergecraft.analyzers.trust import analyzers_enabled
from mergecraft.config.settings import load_repo_settings
from mergecraft.config.trust_policy import is_fork_pull_request
from mergecraft.mcp.git import _git_env, _is_auth_failure, _run_git
from mergecraft.mcp.shared import JsonSchema, ToolClass, execute, tool
from mergecraft.mcp.tool_call import normalize_pull_number_aliases
from mergecraft.mcp.tool_state import StoredPushDest, primary_repo_state
from mergecraft.modes._api_only_scope import API_ONLY_SCOPE, degraded_checkout_reason
from mergecraft.types import INCREMENTAL_REVIEW_MODE
from mergecraft.utils.gha_log import warning
from mergecraft.utils.git_hardening import read_remote_origin_url
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.mcp.context import ToolContext
    from mergecraft.xrepo.review import BaseManifestLookup

__all__ = [
    "GitHubClient",
    "checkout_pr_tool",
    "ensure_local_base_branch_alias",
    "get_git_status",
    "list_mergecraft_reviews",
]


def _rebaseline_config_after_checkout(ctx: ToolContext) -> None:
    """Re-baseline the config hash after PR checkout (D14)."""
    from mergecraft.config.settings_snapshot import rebaseline_repo_settings_snapshot

    rebaseline_repo_settings_snapshot(ctx)


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
_DIFF_FILE_RE = re.compile(r"^diff --git a/(?P<path>.+?) b/(?P<to>.+)$", re.MULTILINE)
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


async def _recover_last_reviewed_sha(ctx: ToolContext, *, pull_number: int, head_sha: str) -> str:
    """Fetch prior reviews and return the last mergeCraft-reviewed SHA (``""`` if none)."""
    reviews = await list_mergecraft_reviews(ctx, pull_number=pull_number)
    return last_reviewed_sha(reviews, head_sha=head_sha) or ""


def changed_paths_in_diff(diff_text: str) -> list[str]:
    """Return the post-image paths named by a unified diff, in first-seen order."""
    seen: dict[str, None] = {}
    for match in _DIFF_FILE_RE.finditer(diff_text):
        seen.setdefault(match.group("to"), None)
    return list(seen)


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
    ctx: ToolContext, *, pull_number: int
) -> tuple[set[str], set[str]]:
    """Return ``(required, allowed)`` paths for the PR as GitHub reports them.

    The authority a caller-supplied diff is checked against before it may
    establish review scope. ``required`` is the post-image name of every changed
    file — a diff omitting one does not describe this PR. ``allowed`` adds
    rename pre-image names, because ``git diff`` writes a rename as
    ``a/<old> b/<new>`` and only ``<new>`` is the post-image path; counting
    ``<old>`` as required would reject an honest rename.
    """
    endpoint = f"/repos/{ctx.repo.owner}/{ctx.repo.name}/pulls/{pull_number}/files"
    required: set[str] = set()
    allowed: set[str] = set()
    for page in range(1, _PULL_FILES_MAX_PAGES + 1):
        files = await ctx.scm.get(
            endpoint, params={"per_page": _PULL_FILES_PAGE_SIZE, "page": page}
        )
        batch = list(files or [])
        for f in batch:
            filename = str(f.get("filename") or "").strip()
            if filename:
                required.add(filename)
                allowed.add(filename)
            previous = str(f.get("previous_filename") or "").strip()
            if previous:
                allowed.add(previous)
        if len(batch) < _PULL_FILES_PAGE_SIZE:
            break
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
    parts: list[str] = []
    unreviewable: list[str] = []
    truncated = False
    endpoint = f"/repos/{ctx.repo.owner}/{ctx.repo.name}/pulls/{pull_number}/files"
    for page in range(1, _PULL_FILES_MAX_PAGES + 1):
        files = await ctx.scm.get(
            endpoint, params={"per_page": _PULL_FILES_PAGE_SIZE, "page": page}
        )
        batch = list(files or [])
        for f in batch:
            filename = str(f.get("filename") or "").strip()
            parts.append(f"diff --git a/{filename} b/{filename}\n")
            if f.get("patch"):
                parts.append(f.get("patch") + "\n")
            elif filename and _line_change_count(f) > 0:
                # GitHub omits ``patch`` for binary files *and* for text diffs
                # too large to inline; the line counts tell them apart.
                unreviewable.append(filename)
        if len(batch) < _PULL_FILES_PAGE_SIZE:
            break
    else:
        truncated = True
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
    *, cwd: str, temp: str, pull_number: int, prior_sha: str, git_token: str
) -> tuple[str, list[str]] | None:
    """Write the diff since ``prior_sha`` and return its path plus changed paths.

    Returns ``None`` — so the caller omits ``incrementalDiffPath`` entirely rather
    than advertising a file that does not exist — when the prior commit is not
    reachable in this checkout or the range turns out to be empty.
    """
    try:
        _run_git(["cat-file", "-e", f"{prior_sha}^{{commit}}"], cwd=cwd)
    except RuntimeError:
        env, remote_url = _git_env_for_cwd(cwd, git_token)
        try:
            _run_git(
                ["fetch", "--no-tags", "--depth=1000", "origin", prior_sha],
                cwd=cwd,
                env=env,
                remote_url=remote_url or None,
            )
            _run_git(["cat-file", "-e", f"{prior_sha}^{{commit}}"], cwd=cwd)
        except RuntimeError as err:
            logger.info("incremental diff: prior sha {} unreachable: {}", prior_sha, err)
            return None
    try:
        diff = _run_git(["diff", "--merge-base", prior_sha, "HEAD"], cwd=cwd)
    except RuntimeError as err:
        logger.info("incremental diff: range diff soft-failed: {}", err)
        return None
    if not diff.strip():
        logger.info("incremental diff: no changes since {}; omitting path", prior_sha)
        return None
    path = str(Path(temp) / f"pr-{pull_number}-incremental.diff")
    Path(path).write_text(diff, encoding="utf-8")
    return path, changed_paths_in_diff(diff)


def get_git_status(cwd: str) -> str:
    """Return porcelain status for *cwd* (monkeypatch hook for tests and callers)."""
    return _run_git(["status", "--porcelain"], cwd=cwd).strip()


def checkout_pr_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        params = normalize_pull_number_aliases(params, _CHECKOUT_PR_INPUT_SCHEMA)
        pull_number = int(params["pull_number"])
        state = primary_repo_state(ctx.tool_state)
        cwd = state.dir
        prior_reviews: list[dict[str, Any]] = []

        dirty = get_git_status(cwd)
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
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        head_ref = head.get("ref") or ""
        head_sha = head.get("sha") or ""
        base_ref = base.get("ref") or ""
        # TB-D3 — one fork predicate. The ``full_name`` comparison stops being a
        # decision input; ``is_fork_pull_request`` reads the same ``head.repo.fork``
        # shape every other fork decision reads.
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

        local_branch = f"pr-{pull_number}"

        # Fetch PR head into local_branch. checkout_pr can run more than once
        # against the same shared workspace within a single job (e.g. a Nous
        # review, then a Codex fallback both calling checkout_pr against
        # /github/workspace). When a prior call left HEAD on local_branch,
        # ``_fetch_head_with_retry`` detaches before retrying on the
        # "refusing to fetch into branch" error — safe because the dirty check
        # above already guarantees no uncommitted work to lose.
        fetched, fetch_err = _fetch_head_with_retry(
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
            fetch_diff = await _diff_from_pull_files(ctx, pull_number=pull_number)
            fetch_unreviewable = fetch_diff.unreviewable_paths
            fetch_truncated = fetch_diff.truncated
            fetch_degraded = _append_diff_degradations(
                fetch_degraded, truncated=fetch_truncated, unreviewable=fetch_unreviewable
            )
            warning(fetch_degraded)
            Path(diff_path).write_text(fetch_diff, encoding="utf-8")
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
            _rebaseline_config_after_checkout(ctx)
            prior_reviews = await list_mergecraft_reviews(ctx, pull_number=pull_number)
            publishers = expected_publisher_logins(ctx) if prior_reviews else frozenset()
            round_index = review_round_index(prior_reviews, publishers=publishers)
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
            }
            if fetch_unreviewable:
                result["unreviewablePaths"] = fetch_unreviewable
            if fetch_truncated:
                result["diffTruncated"] = True

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

        _run_git(["checkout", local_branch], cwd=cwd)
        # Ensure base is available for merge-base diffs
        base_env, base_remote_url = _git_env_for_cwd(cwd, ctx.git_token)
        base_fetch_failure: str | None = None
        try:
            _run_git(
                [
                    "fetch",
                    "--no-tags",
                    "--depth=1000",
                    "origin",
                    f"{base_ref}:refs/remotes/origin/{base_ref}",
                ],
                cwd=cwd,
                env=base_env,
                remote_url=base_remote_url or None,
            )
        except Exception as err:
            base_fetch_failure = str(err).splitlines()[0] if str(err) else "git fetch failed"
            logger.info("base fetch soft-failed: {}", err)
        if base_ref:
            try:
                ensure_local_base_branch_alias(cwd=cwd, base_ref=base_ref)
            except Exception as err:
                logger.info("base branch alias soft-failed: {}", err)

        state.issue_number = pull_number
        state.checkout_sha = head_sha or _run_git(["rev-parse", "HEAD"], cwd=cwd).strip()
        state.push_dest = StoredPushDest(
            remote_name="origin",
            remote_branch=head_ref,
            local_branch=local_branch,
        )
        try:
            state.push_url = read_remote_origin_url(cwd)
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
            diff = _run_git(
                ["diff", "--merge-base", f"origin/{base_ref}", "HEAD"],
                cwd=cwd,
            )
        except Exception as err:
            diff_failure = str(err).splitlines()[0] if str(err) else "git diff failed"
            files_diff = await _diff_from_pull_files(ctx, pull_number=pull_number)
            diff = files_diff
            unreviewable = files_diff.unreviewable_paths
            diff_truncated = files_diff.truncated
        Path(diff_path).write_text(diff, encoding="utf-8")
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
            register_review_scope(ctx.tool_state, diff_path=diff_path, provenance="checkout")
        _rebaseline_config_after_checkout(ctx)

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

        prior_reviews = await list_mergecraft_reviews(ctx, pull_number=pull_number)
        publishers = expected_publisher_logins(ctx) if prior_reviews else frozenset()
        round_index = review_round_index(prior_reviews, publishers=publishers)
        ctx.tool_state.review_round_index = round_index

        # A re-review should pay for the new commits, not the whole PR. The key is
        # emitted only when the range is real: the prompt tells the reviewer to
        # read this path first, so advertising a path that does not resolve is
        # worse than not advertising one at all.
        if ctx.tool_state.selected_mode == INCREMENTAL_REVIEW_MODE:
            prior_sha = (
                last_reviewed_sha(
                    prior_reviews,
                    head_sha=state.checkout_sha or "",
                    publishers=publishers,
                )
                or ""
            )
            if prior_sha:
                written = _write_incremental_diff(
                    cwd=cwd,
                    temp=temp,
                    pull_number=pull_number,
                    prior_sha=prior_sha,
                    git_token=ctx.git_token,
                )
                if written is not None:
                    incremental_path, changed = written
                    state.last_reviewed_sha = prior_sha
                    state.incremental_diff_path = incremental_path
                    state.incremental_changed_paths = changed
                    result["incrementalDiffPath"] = incremental_path
                    result["lastReviewedSha"] = prior_sha
                    logger.info(
                        "incremental diff for PR #{} since {} -> {} ({} file(s))",
                        pull_number,
                        prior_sha,
                        incremental_path,
                        len(changed),
                    )

        # S6 #94 — impact-path extraction (default off behind analyzers.impact).
        # Emitted only when enabled; returns None (-> no key) when the diff
        # has zero declarations, matching the incrementalDiffPath convention.
        # The analyzers.impact toggle is read from the PR's own checkout (fine —
        # repo config is safe to *read* regardless of trust tier), but gated
        # behind analyzers_enabled(ctx) first so the operator's effective
        # policy (analyzers: off, or analyzers.enabled: false) always wins over
        # whatever a PR sets in its own config — mirrors run_analyzers_tool's
        # gate (mcp/analyzers.py). ast-grep execution itself is further gated
        # on ctx.trust_tier inside write_impact, which fails closed (omits
        # impactPath) when sandbox isolation for an untrusted checkout isn't
        # available (D7).
        try:
            repo_root = Path(cwd)
            settings_obj = load_repo_settings(root=repo_root, load_learnings_files=False)
            if analyzers_enabled(ctx) and settings_obj.analyzers.impact:
                ast_grep_binary = resolve_ast_grep_binary()
                if ast_grep_binary is None:
                    logger.info(
                        "impactPath skipped for PR #{}: managed ast-grep binary unavailable",
                        pull_number,
                    )
                else:
                    impact_result = write_impact(
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
                attach_linked_repo_review,
                operator_authorized_linked_repos,
            )

            base_lookup = _base_linked_repo_manifest(
                cwd=cwd, base_ref=base_ref, base_fetch_failure=base_fetch_failure
            )
            linked = attach_linked_repo_review(
                Path(cwd),
                authorized_repos=operator_authorized_linked_repos(),
                base_manifest=base_lookup.manifest,
                base_manifest_error=base_lookup.unreadable_reason,
            )
            if linked is not None:
                result.update(linked)
        except Exception as xrepo_err:
            logger.info("linked-repo review soft-failed: {}", xrepo_err)

        logger.info("checked out PR #{} -> {}", pull_number, local_branch)
        from mergecraft.mcp.review_context import hydrate_review_context

        await hydrate_review_context(
            ctx,
            round_index=round_index,
            incremental_changed_paths=state.incremental_changed_paths,
        )
        return result

    return tool(
        name="checkout_pr",
        tool_class=ToolClass.SCOPE,
        mutates=True,
        timeout_ms=600_000,
        description=(
            "Checkout a pull request branch locally. Returns diffPath pointing to the "
            "formatted diff file, plus incrementalDiffPath (changes since the last "
            "mergeCraft review) on a re-review when a prior reviewed commit is "
            "recoverable and the range is non-empty. When the repo config enables "
            "analyzers.impact, also returns impactPath pointing to a JSON file listing "
            "declaration-level reference leads for the changed files."
        ),
        input_schema=_CHECKOUT_PR_INPUT_SCHEMA,
        execute=execute(_run, "checkout_pr"),
    )
