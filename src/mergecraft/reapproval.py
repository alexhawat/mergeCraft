"""Re-approval I/O: read the evidence a carried-over mergeCraft pass needs, then decide.

:mod:`mergecraft.classify.reapproval` is the pure decision. This module reads, for one
pull request: its current state, the review-policy digest of the base-side config, the
newest mergeCraft review's head, the trusted ``mergecraft-approval`` check run on that
head, three compare-API answers, file modes from Git trees and the head-side text of
the qualifying paths.

Everything fails toward the normal review. A failed or truncated read, an unexpected
shape, a check run from an App the operator did not name, or a summary without a
review stamp is a refusal with the reason stated — never a carried-over verdict.

Exports:
    ReapprovalOutcome: The verdict and the stamp this run records on its own checks.
    review_policy_digest: The digest of the base-side review policy.
    evaluate_reapproval: Read the evidence and decide.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from mergecraft.classify.reapproval import (
    APPROVAL_CHECK_NAME,
    ChangedFile,
    Comparison,
    PriorPass,
    ReapprovalEvidence,
    ReapprovalVerdict,
    ReviewStamp,
    decide_reapproval,
    parse_review_stamp,
    required_mode_paths,
)
from mergecraft.classify.triage import trusted_check_apps

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Collection

    from mergecraft.config.settings import FastPathReapprovalSettings
    from mergecraft.scm.protocol import ScmProvider

_SHA: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}")
# The compare API lists at most 300 files; a listing that reaches the cap may be cut.
_COMPARE_FILE_CAP: Final[int] = 300
_MAX_TREES: Final[int] = 256
_MAX_HEAD_CHARS: Final[int] = 1_000_000
# The base-side files whose content decides how a pull request is reviewed.
POLICY_DIRECTORY: Final[str] = ".mergecraft"


class ReapprovalUnavailableError(Exception):
    """The evidence could not be read completely, so nothing carries over."""


@dataclass(frozen=True, slots=True)
class ReapprovalOutcome:
    """The re-approval verdict, and the stamp this run's own approval check carries.

    ``stamp`` is set whenever the policy digest could be computed, so a run that falls
    through to the normal review still records what a later re-approval checks.
    """

    verdict: ReapprovalVerdict
    stamp: ReviewStamp | None


def _sha(value: object, what: str) -> str:
    if not isinstance(value, str) or _SHA.fullmatch(value) is None:
        msg = f"{what} is not a full commit SHA"
        raise ReapprovalUnavailableError(msg)
    return value


class _Trees:
    """Read immutable Git trees once each, under a fixed budget; never a recursive read."""

    def __init__(self, scm: ScmProvider, root: str) -> None:
        self._scm = scm
        self._root = root
        self._cache: dict[str, dict[str, dict[str, Any]]] = {}

    async def entries(self, sha: str) -> dict[str, dict[str, Any]]:
        if sha not in self._cache:
            if len(self._cache) >= _MAX_TREES:
                raise ReapprovalUnavailableError("the file-mode proof exceeds its tree budget")
            tree = await self._scm.get(f"{self._root}/git/trees/{sha}")
            if not isinstance(tree, dict) or tree.get("truncated") is not False:
                raise ReapprovalUnavailableError("a Git tree was missing or truncated")
            rows = tree.get("tree")
            if not isinstance(rows, list):
                raise ReapprovalUnavailableError("a Git tree had an unexpected shape")
            indexed: dict[str, dict[str, Any]] = {}
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("path"), str):
                    raise ReapprovalUnavailableError("a Git tree entry had an unexpected shape")
                if row["path"] in indexed:
                    raise ReapprovalUnavailableError("a Git tree lists an entry twice")
                indexed[row["path"]] = row
            self._cache[sha] = indexed
        return self._cache[sha]

    async def entry(self, commit_sha: str, path: str) -> dict[str, Any] | None:
        """The tree entry for ``path`` at ``commit_sha``, or ``None`` when absent."""
        parts = path.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            msg = f"invalid path {path!r}"
            raise ReapprovalUnavailableError(msg)
        sha = commit_sha
        for directory in parts[:-1]:
            row = (await self.entries(sha)).get(directory)
            if row is None:
                return None
            child = row.get("sha")
            if row.get("type") != "tree" or not isinstance(child, str):
                return None
            sha = _sha(child, f"the tree of {directory}")
        return (await self.entries(sha)).get(parts[-1])

    async def mode(self, commit_sha: str, path: str) -> str | None:
        row = await self.entry(commit_sha, path)
        if row is None:
            return None
        mode = row.get("mode")
        if not isinstance(mode, str):
            raise ReapprovalUnavailableError(f"no mode for {path}")
        return mode


async def review_policy_digest(
    scm: ScmProvider,
    owner: str,
    repo: str,
    base_sha: str,
    *,
    workflow_path: str | None,
    version: str,
) -> str:
    """The digest of the review policy a pull request is reviewed under.

    It covers the base side's ``.mergecraft`` directory (config, learnings, rules —
    its Git tree id changes with any file in it), the workflow file that runs the
    review (``GITHUB_WORKFLOW_REF``; its Action pin and inputs) and the mergeCraft
    version. Any change to them is a changed review policy.
    """
    trees = _Trees(scm, f"/repos/{owner}/{repo}")
    _sha(base_sha, "the base revision")
    policy = await trees.entry(base_sha, POLICY_DIRECTORY)
    payload: dict[str, Any] = {
        "mergecraft": version,
        POLICY_DIRECTORY: policy.get("sha") if policy is not None else None,
    }
    if workflow_path:
        workflow = await trees.entry(base_sha, workflow_path)
        payload["workflow"] = [workflow_path, workflow.get("sha") if workflow else None]
    blob = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


async def _read_pull(scm: ScmProvider, root: str, pull_number: int, head_sha: str) -> Any:
    pull = await scm.get(f"{root}/pulls/{pull_number}")
    if not isinstance(pull, dict):
        raise ReapprovalUnavailableError("the pull request could not be read")
    head, base = pull.get("head"), pull.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise ReapprovalUnavailableError("the pull request had an unexpected shape")
    if head.get("sha") != head_sha:
        raise ReapprovalUnavailableError("the pull request head moved during the run")
    if pull.get("state") != "open":
        raise ReapprovalUnavailableError("the pull request is not open")
    if not isinstance(base.get("ref"), str) or not base["ref"]:
        raise ReapprovalUnavailableError("the pull request names no target branch")
    _sha(base.get("sha"), "the base revision")
    return pull


async def _prior_head(
    list_reviews: Callable[[], Awaitable[list[dict[str, Any]]]], head_sha: str
) -> str:
    """The head of the newest mergeCraft-authored review, which must not be this head."""
    reviews = await list_reviews()
    for review in reversed(reviews or []):
        commit = str(review.get("commit_id") or "").strip().lower()
        if _SHA.fullmatch(commit) is None:
            continue
        if commit == head_sha:
            raise ReapprovalUnavailableError(
                "a mergeCraft review of this head already exists; it is not replaced"
            )
        return commit
    raise ReapprovalUnavailableError("no prior mergeCraft review of this pull request")


def _app_slug(row: dict[str, Any]) -> str:
    app = row.get("app")
    slug = app.get("slug") if isinstance(app, dict) else None
    return slug.strip().lower() if isinstance(slug, str) else ""


async def _prior_pass(
    scm: ScmProvider, owner: str, repo: str, prior_head: str, *, trusted: frozenset[str]
) -> PriorPass:
    """The newest trusted ``mergecraft-approval`` check on ``prior_head``; it must pass."""
    listing = await scm.list_check_runs_for_ref(owner, repo, prior_head)
    rows = getattr(listing, "items", None)
    if not isinstance(rows, list) or getattr(listing, "incomplete", False):
        raise ReapprovalUnavailableError("the check-run listing was incomplete")
    candidates = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("name") == APPROVAL_CHECK_NAME
        and row.get("head_sha") == prior_head
        and _app_slug(row) in trusted
        and isinstance(row.get("id"), int)
    ]
    if not candidates:
        raise ReapprovalUnavailableError(
            f"no {APPROVAL_CHECK_NAME} check from a trusted App on {prior_head[:12]}"
        )
    latest = max(candidates, key=lambda row: int(row["id"]))
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise ReapprovalUnavailableError(
            f"the newest {APPROVAL_CHECK_NAME} check on {prior_head[:12]} did not pass"
        )
    output = latest.get("output")
    summary = output.get("summary") if isinstance(output, dict) else None
    url = str(latest.get("details_url") or latest.get("html_url") or "")
    if not url:
        raise ReapprovalUnavailableError("the prior pass has no link to its review")
    return PriorPass(
        check_id=int(latest["id"]),
        head_sha=prior_head,
        app_slug=_app_slug(latest),
        url=url,
        stamp=parse_review_stamp(summary) if isinstance(summary, str) else None,
    )


def _int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _changed_file(row: object) -> ChangedFile:
    if not isinstance(row, dict) or not isinstance(row.get("filename"), str):
        raise ReapprovalUnavailableError("a compare file entry had an unexpected shape")
    patch = row.get("patch")
    previous = str(row.get("previous_filename") or "").strip()
    name = row["filename"].strip()
    return ChangedFile(
        path=name,
        status=str(row.get("status") or "").strip().lower(),
        blob_sha=str(row.get("sha") or ""),
        previous_path=previous if previous != name else "",
        patch=patch if isinstance(patch, str) and patch else None,
        changes=_int(row.get("additions")) + _int(row.get("deletions")),
    )


async def _compare(scm: ScmProvider, root: str, base: str, head: str) -> Comparison:
    payload = await scm.get(f"{root}/compare/{base}...{head}")
    if not isinstance(payload, dict):
        raise ReapprovalUnavailableError("a comparison could not be read")
    merge_base = payload.get("merge_base_commit")
    sha = merge_base.get("sha") if isinstance(merge_base, dict) else None
    files = payload.get("files")
    if not isinstance(files, list):
        raise ReapprovalUnavailableError("a comparison listed no files")
    if len(files) >= _COMPARE_FILE_CAP:
        raise ReapprovalUnavailableError("a comparison reached the 300-file listing cap")
    return Comparison(
        merge_base=_sha(sha, "a merge base"),
        files=tuple(_changed_file(row) for row in files),
    )


async def _head_text(scm: ScmProvider, root: str, head_sha: str, path: str) -> str | None:
    payload = await scm.get(f"{root}/contents/{path}", params={"ref": head_sha})
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        return None
    try:
        text = base64.b64decode(str(payload.get("content") or "")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return text if len(text) <= _MAX_HEAD_CHARS else None


async def _modes(
    trees: _Trees, revisions: Collection[str], paths: Collection[str]
) -> dict[str, dict[str, str | None]]:
    return {
        revision: {path: await trees.mode(revision, path) for path in paths}
        for revision in revisions
    }


async def _evidence(
    scm: ScmProvider,
    owner: str,
    repo: str,
    *,
    pull: dict[str, Any],
    pull_number: int,
    head_sha: str,
    prior: PriorPass,
    policy_digest: str,
    qualifying: Collection[str],
) -> ReapprovalEvidence:
    root = f"/repos/{owner}/{repo}"
    base_sha = pull["base"]["sha"]
    reviewed = await _compare(scm, root, base_sha, prior.head_sha)
    current = await _compare(scm, root, base_sha, head_sha)
    interdiff = await _compare(scm, root, prior.head_sha, head_sha)
    wanted = required_mode_paths(reviewed, current, qualifying)
    trees = _Trees(scm, root)
    modes: dict[str, dict[str, str | None]] = {}
    for revisions, paths in (
        (
            (prior.head_sha, head_sha, reviewed.merge_base, current.merge_base),
            wanted["preserved"],
        ),
        ((head_sha, current.merge_base), wanted["qualifying"]),
    ):
        for revision, found in (await _modes(trees, revisions, paths)).items():
            modes.setdefault(revision, {}).update(found)
    head_files: dict[str, str] = {}
    for path in wanted["qualifying"]:
        text = await _head_text(scm, root, head_sha, path)
        if text is not None:
            head_files[path] = text
    return ReapprovalEvidence(
        pull_number=pull_number,
        base_ref=pull["base"]["ref"],
        head_sha=head_sha,
        policy_digest=policy_digest,
        prior=prior,
        reviewed=reviewed,
        current=current,
        interdiff=interdiff,
        modes=modes,
        head_files=head_files,
    )


async def evaluate_reapproval(
    scm: ScmProvider,
    owner: str,
    repo: str,
    pull_number: int,
    head_sha: str,
    *,
    config: FastPathReapprovalSettings,
    list_reviews: Callable[[], Awaitable[list[dict[str, Any]]]],
    workflow_path: str | None,
    version: str,
) -> ReapprovalOutcome:
    """Read the evidence for one pull request and decide whether its prior pass carries over.

    ``list_reviews`` returns the pull request's mergeCraft-authored reviews, oldest
    first (marker **and** expected publisher, see
    :func:`mergecraft.mcp.checkout.list_mergecraft_reviews`). Total: every failure is
    a refusal with its reason, never an exception.
    """
    root = f"/repos/{owner}/{repo}"
    stamp: ReviewStamp | None = None
    try:
        _sha(head_sha, "the head revision")
        pull = await _read_pull(scm, root, pull_number, head_sha)
        digest = await review_policy_digest(
            scm,
            owner,
            repo,
            pull["base"]["sha"],
            workflow_path=workflow_path,
            version=version,
        )
        stamp = ReviewStamp(
            pull_number=pull_number, base_ref=pull["base"]["ref"], policy_digest=digest
        )
        trusted = trusted_check_apps(config.trusted_check_apps)
        if not trusted:
            msg = "review.fastPath.reapproval.trustedCheckApps names no trusted App"
            raise ReapprovalUnavailableError(msg)
        prior_head = await _prior_head(list_reviews, head_sha)
        prior = await _prior_pass(scm, owner, repo, prior_head, trusted=trusted)
        evidence = await _evidence(
            scm,
            owner,
            repo,
            pull=pull,
            pull_number=pull_number,
            head_sha=head_sha,
            prior=prior,
            policy_digest=digest,
            qualifying=config.paths,
        )
        verdict = decide_reapproval(evidence, qualifying_paths=config.paths)
    except Exception as err:  # any read failure is a reason to review, never to carry over
        reason = (
            str(err)
            if isinstance(err, ReapprovalUnavailableError)
            else (f"the re-approval evidence could not be read ({type(err).__name__}: {err})")
        )
        verdict = ReapprovalVerdict(record=None, reason=reason)
    logger.info(
        "re-approval: PR #{} {} ({})",
        pull_number,
        "carries over" if verdict.eligible else "gets the normal review",
        verdict.reason,
    )
    return ReapprovalOutcome(verdict=verdict, stamp=stamp)


def workflow_path_from_ref(workflow_ref: str | None) -> str | None:
    """The repository path of the running workflow, from ``GITHUB_WORKFLOW_REF``.

    ``owner/repo/.github/workflows/x.yml@refs/heads/main`` → ``.github/workflows/x.yml``.
    """
    if not workflow_ref:
        return None
    location, _, _ref = workflow_ref.partition("@")
    parts = location.split("/", 2)
    return parts[2] if len(parts) == 3 and parts[2] else None


__all__ = [
    "POLICY_DIRECTORY",
    "ReapprovalOutcome",
    "ReapprovalUnavailableError",
    "evaluate_reapproval",
    "review_policy_digest",
    "workflow_path_from_ref",
]
