"""checkout_pr tool — fetch PR branch and write formatted diff."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.git import _git_env, _run_git
from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import StoredPushDest, primary_repo_state
from mergecraft.types import INCREMENTAL_REVIEW_MODE

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

# A review authored by mergeCraft carries the run footer, or (for a review whose
# body was suppressed) at least one finding marker. Reviews from humans and other
# bots carry neither, and their commit ids must never be mistaken for "the head
# mergeCraft last reviewed".
_MERGECRAFT_REVIEW_MARKERS = ("*via mergecraft*", "mergecraft-finding:v1:", "pullfrog-finding:v1:")

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_DIFF_FILE_RE = re.compile(r"^diff --git a/(?P<path>.+?) b/(?P<to>.+)$", re.MULTILINE)


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


def last_reviewed_sha(reviews: list[dict[str, Any]], *, head_sha: str) -> str | None:
    """Return the head SHA of the most recent mergeCraft review, if one is recoverable.

    Args:
        reviews: Raw review objects as returned by ``GET /pulls/{n}/reviews``,
            oldest first (GitHub's documented order).
        head_sha: The PR head this run is about to review.

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
        body = str(review.get("body") or "")
        if not any(marker in body for marker in _MERGECRAFT_REVIEW_MARKERS):
            continue
        return commit_id
    return None


def changed_paths_in_diff(diff_text: str) -> list[str]:
    """Return the post-image paths named by a unified diff, in first-seen order."""
    seen: dict[str, None] = {}
    for match in _DIFF_FILE_RE.finditer(diff_text):
        seen.setdefault(match.group("to"), None)
    return list(seen)


async def _recover_last_reviewed_sha(ctx: ToolContext, *, pull_number: int, head_sha: str) -> str:
    """Fetch prior reviews and return the last mergeCraft-reviewed SHA (``""`` if none)."""
    try:
        reviews = await ctx.github.list_reviews(
            ctx.repo.owner, ctx.repo.name, pull_number, params={"per_page": 100}
        )
    except Exception as err:  # advisory; a missing review history is not fatal
        logger.info("incremental diff: listing prior reviews soft-failed: {}", err)
        return ""
    return last_reviewed_sha(reviews, head_sha=head_sha) or ""


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
        try:
            _run_git(
                ["fetch", "--no-tags", "--depth=1000", "origin", prior_sha],
                cwd=cwd,
                env=_git_env(git_token),
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


def checkout_pr_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        pull_number = int(params["pull_number"])
        state = primary_repo_state(ctx.tool_state)
        cwd = state.dir

        dirty = _run_git(["status", "--porcelain"], cwd=cwd).strip()
        if dirty:
            msg = (
                f"cannot checkout PR #{pull_number} while the working tree has "
                f"uncommitted changes. dirty paths:\n{dirty}"
            )
            raise RuntimeError(msg)

        pr = await ctx.github.get_pull(ctx.repo.owner, ctx.repo.name, pull_number)
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        head_ref = head.get("ref") or ""
        head_sha = head.get("sha") or ""
        base_ref = base.get("ref") or ""
        is_fork = (head.get("repo") or {}).get("full_name") != (
            (base.get("repo") or {}).get("full_name")
        )
        local_branch = f"pr-{pull_number}"

        # Fetch PR head via GitHub's pull/<n>/head ref
        _run_git(
            ["fetch", "--no-tags", "origin", f"pull/{pull_number}/head:{local_branch}"],
            cwd=cwd,
            env=_git_env(ctx.git_token),
        )
        _run_git(["checkout", local_branch], cwd=cwd)
        # Ensure base is available for merge-base diffs
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
                env=_git_env(ctx.git_token),
            )
        except Exception as err:
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
        if is_fork and head.get("repo"):
            clone_url = (head["repo"].get("clone_url") or "").rstrip("/")
            state.push_url = clone_url if clone_url.endswith(".git") else f"{clone_url}.git"
        else:
            state.push_url = f"https://github.com/{ctx.repo.owner}/{ctx.repo.name}.git"

        # Write a basic diff file for reviewers
        temp = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
        diff_path = str(Path(temp) / f"pr-{pull_number}.diff")
        try:
            diff = _run_git(
                ["diff", "--merge-base", f"origin/{base_ref}", "HEAD"],
                cwd=cwd,
            )
        except Exception:
            files = await ctx.github.get(
                f"/repos/{ctx.repo.owner}/{ctx.repo.name}/pulls/{pull_number}/files"
            )
            parts: list[str] = []
            for f in files or []:
                parts.append(f"diff --git a/{f.get('filename')} b/{f.get('filename')}\n")
                if f.get("patch"):
                    parts.append(f.get("patch") + "\n")
            diff = "".join(parts)
        Path(diff_path).write_text(diff, encoding="utf-8")

        result: dict[str, Any] = {
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

        # A re-review should pay for the new commits, not the whole PR. The key is
        # emitted only when the range is real: the prompt tells the reviewer to
        # read this path first, so advertising a path that does not resolve is
        # worse than not advertising one at all.
        if ctx.tool_state.selected_mode == INCREMENTAL_REVIEW_MODE:
            prior_sha = await _recover_last_reviewed_sha(
                ctx, pull_number=pull_number, head_sha=state.checkout_sha or ""
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

        logger.info("checked out PR #{} -> {}", pull_number, local_branch)
        return result

    return tool(
        name="checkout_pr",
        mutates=True,
        timeout_ms=600_000,
        description=(
            "Checkout a pull request branch locally. Returns diffPath pointing to the "
            "formatted diff file, plus incrementalDiffPath (changes since the last "
            "mergeCraft review) on a re-review when a prior reviewed commit is "
            "recoverable and the range is non-empty."
        ),
        input_schema={
            "type": "object",
            "properties": {"pull_number": {"type": "number"}},
            "required": ["pull_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "checkout_pr"),
    )
