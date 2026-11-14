"""Carry exact, trusted pull request approvals over to a GitHub merge group.

Exports:
    bind_merge_group: Validate the event and bind it to the scheduled revision.
    prove_merge_group: Verify the queue lineage and its source approvals.
    queue_review_stamp: Attest the actual diff baseline on a source approval.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from mergecraft import __version__
from mergecraft.classify.reapproval import ReviewStamp
from mergecraft.classify.triage import trusted_check_apps
from mergecraft.config.env import ConfigLocatorEnv
from mergecraft.reapproval import (
    POLICY_DIRECTORY,
    ReapprovalUnavailableError,
    _prior_pass,
    _sha,
    _Trees,
    review_policy_digest,
    workflow_path_from_ref,
)
from mergecraft.review_policy.ignore_paths import _base_review_settings

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.mcp.context import ToolContext
    from mergecraft.scm.protocol import ScmProvider

_HEADS = "refs/heads/"
_QUEUE = f"{_HEADS}gh-readonly-queue/"
_MAX_LAYERS = 20
_MAX_REFS = 200
_MAX_POLICY_ENTRIES = 10_000
_MAX_CHANGED_ENTRIES = 10_000
_MAX_WALKED_ENTRIES = 100_000
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_QUEUE_SUFFIX = re.compile(r"pr-([1-9][0-9]{0,10})-([0-9a-f]{40})")

TreeEntry = tuple[str, str]
TreeDelta = dict[str, tuple[TreeEntry | None, TreeEntry | None]]


@dataclass(frozen=True, slots=True)
class _QueueLayer:
    ref: str
    head: str
    base: str
    pull_number: int


@dataclass(frozen=True, slots=True)
class MergeGroup:
    """A scheduled group and its repository-scoped target branch."""

    owner: str
    repo: str
    target_ref: str
    layer: _QueueLayer

    @property
    def api_root(self) -> str:
        return f"/repos/{self.owner}/{self.repo}"


def _mapping(value: object, message: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReapprovalUnavailableError(message)
    return value


def _layer(ref: str, head: str, prefix: str) -> _QueueLayer:
    suffix = _QUEUE_SUFFIX.fullmatch(ref[len(prefix) :]) if ref.startswith(prefix) else None
    if suffix is None:
        raise ReapprovalUnavailableError("GitHub did not identify the queue layer's pull request")
    number, base = suffix.groups()
    return _QueueLayer(ref, head, base, int(number))


def bind_merge_group(event: object, env: Mapping[str, str]) -> MergeGroup:
    """Bind the native event to the repository and revision GitHub scheduled.

    Args:
        event: The native Actions event payload.
        env: The Actions environment naming the scheduled repository, ref and SHA.

    Raises:
        ReapprovalUnavailableError: The event is invalid or does not match the run.
    """
    event_obj = _mapping(event, "There is no native merge group event")
    if event_obj.get("action") != "checks_requested":
        raise ReapprovalUnavailableError("Expected a merge group checks_requested event")
    repository = _mapping(event_obj.get("repository"), "The event repository is missing")
    full_name = env.get("GITHUB_REPOSITORY", "")
    if not _REPO.fullmatch(full_name) or repository.get("full_name") != full_name:
        raise ReapprovalUnavailableError("The merge group belongs to a different repository")
    group = _mapping(event_obj.get("merge_group"), "The merge group is missing")
    head = _sha(group.get("head_sha"), "the merge group revision")
    ref = group.get("head_ref")
    if head != env.get("GITHUB_SHA") or not isinstance(ref, str) or ref != env.get("GITHUB_REF"):
        raise ReapprovalUnavailableError("The merge group revision does not match the Actions run")
    target = group.get("base_ref")
    if (
        not isinstance(target, str)
        or not target.startswith(_HEADS)
        or target.startswith(_QUEUE)
        or len(target) == len(_HEADS)
    ):
        raise ReapprovalUnavailableError("The merge group has no valid target branch")
    layer = _layer(ref, head, f"{_QUEUE}{target.removeprefix(_HEADS)}/")
    if layer.base != group.get("base_sha"):
        raise ReapprovalUnavailableError("The queue ref and event disagree on the predictive base")
    owner, repo = full_name.split("/")
    return MergeGroup(owner, repo, target, layer)


def _ref_head(payload: object, ref: str) -> str:
    row = _mapping(payload, "GitHub did not return the requested ref")
    if row.get("ref") != ref:
        raise ReapprovalUnavailableError("GitHub returned a different ref")
    obj = _mapping(row.get("object"), "A queue or target ref has no object")
    if obj.get("type") != "commit":
        raise ReapprovalUnavailableError("A queue or target ref does not name a commit")
    return _sha(obj.get("sha"), "the ref's commit")


async def _get_ref(scm: ScmProvider, group: MergeGroup, ref: str) -> str:
    path = quote(ref.removeprefix("refs/"))
    return _ref_head(await scm.get(f"{group.api_root}/git/ref/{path}"), ref)


async def _layers(scm: ScmProvider, group: MergeGroup, target: str) -> list[_QueueLayer]:
    layers = [group.layer]
    if group.layer.base == target:
        return layers
    prefix = f"{_QUEUE}{group.target_ref.removeprefix(_HEADS)}/"
    path = quote(prefix.removeprefix("refs/"))
    rows = await scm.get(f"{group.api_root}/git/matching-refs/{path}")
    if not isinstance(rows, list) or len(rows) >= _MAX_REFS:
        raise ReapprovalUnavailableError("GitHub's queue ref listing is unavailable or too large")
    refs: dict[str, list[str]] = {}
    for item in rows:
        row = _mapping(item, "GitHub returned an invalid queue ref")
        ref = row.get("ref")
        if not isinstance(ref, str) or not ref.startswith(prefix):
            raise ReapprovalUnavailableError("GitHub returned an unexpected queue ref")
        refs.setdefault(_ref_head(row, ref), []).append(ref)
    seen = {group.layer.head}
    while layers[-1].base != target:
        head = layers[-1].base
        matches = refs.get(head, [])
        if len(matches) != 1 or head in seen or len(layers) >= _MAX_LAYERS:
            raise ReapprovalUnavailableError("The queue's preceding layers could not be proven")
        layers.append(_layer(matches[0], head, prefix))
        seen.add(head)
    if len({layer.pull_number for layer in layers}) != len(layers):
        raise ReapprovalUnavailableError("The merge group repeats a pull request")
    return layers


async def _merge_base(scm: ScmProvider, root: str, base: str, head: str) -> str:
    comparison = _mapping(await scm.get(f"{root}/compare/{base}...{head}"), "No Git comparison")
    merge_base = _mapping(comparison.get("merge_base_commit"), "No Git merge base")
    return _sha(merge_base.get("sha"), "the Git merge base")


async def _root_tree(scm: ScmProvider, root: str, commit: str) -> str:
    obj = _mapping(await scm.get(f"{root}/git/commits/{commit}"), "A Git commit is missing")
    if obj.get("sha") != commit:
        raise ReapprovalUnavailableError("GitHub returned a different commit")
    tree = _mapping(obj.get("tree"), "A Git commit has no tree")
    return _sha(tree.get("sha"), "the commit tree")


def _tree_entry(row: dict[str, Any] | None) -> TreeEntry | None:
    if row is None:
        return None
    mode = row.get("mode")
    if mode not in ("040000", "100644", "100755", "120000", "160000"):
        raise ReapprovalUnavailableError("A tree entry has an invalid file mode")
    assert isinstance(mode, str)
    return mode, _sha(row.get("sha"), "the tree entry")


async def _tree_delta(
    scm: ScmProvider, root: str, trees: _Trees, base: str, head: str
) -> TreeDelta:
    """Compare complete entries, skipping only subtrees with equal Git object IDs."""
    before = await _root_tree(scm, root, base)
    after = await _root_tree(scm, root, head)
    delta: TreeDelta = {}
    walked = 0
    pending: list[tuple[str, str | None, str | None]] = [("", before, after)]
    while pending:
        prefix, old_sha, new_sha = pending.pop()
        if old_sha == new_sha:
            continue
        old = await trees.entries(old_sha) if old_sha is not None else {}
        new = await trees.entries(new_sha) if new_sha is not None else {}
        walked += len(old) + len(new)
        if walked > _MAX_WALKED_ENTRIES:
            raise ReapprovalUnavailableError("The Git tree delta exceeds the traversal budget")
        if (old_sha is not None and not old) or (new_sha is not None and not new):
            raise ReapprovalUnavailableError("A changed Git tree is empty")
        for name in old.keys() | new.keys():
            if not name or "/" in name or name in {".", ".."}:
                raise ReapprovalUnavailableError("A tree contains an invalid entry name")
            previous, following = _tree_entry(old.get(name)), _tree_entry(new.get(name))
            if previous == following:
                continue
            path = prefix + name
            old_tree = previous is not None and previous[0] == "040000"
            new_tree = following is not None and following[0] == "040000"
            if old_tree or new_tree:
                pending.append(
                    (
                        path + "/",
                        previous[1] if previous is not None and old_tree else None,
                        following[1] if following is not None and new_tree else None,
                    )
                )
            if (previous is not None and not old_tree) or (following is not None and not new_tree):
                if len(delta) >= _MAX_CHANGED_ENTRIES:
                    raise ReapprovalUnavailableError("The Git tree delta exceeds the entry budget")
                delta[path] = (None if old_tree else previous, None if new_tree else following)
    return delta


async def _pull_head(scm: ScmProvider, group: MergeGroup, number: int, target: str) -> str:
    pull = await scm.get_pull(group.owner, group.repo, number)
    base = _mapping(pull.get("base"), "The pull request has no target")
    target_repo = _mapping(base.get("repo"), "The pull request has no target repository")
    if (
        pull.get("number") != number
        or pull.get("state") != "open"
        or _HEADS + str(base.get("ref")) != group.target_ref
        or base.get("sha") != target
        or target_repo.get("full_name") != f"{group.owner}/{group.repo}"
    ):
        raise ReapprovalUnavailableError(f"PR #{number} is no longer open on this target revision")
    head = _mapping(pull.get("head"), "The pull request has no head")
    return _sha(head.get("sha"), "the current pull request head")


async def _verify_policy_tree(trees: _Trees, base: str) -> None:
    """A policy tree must fully contain the file bytes its digest attests to."""
    policy = await trees.entry(base, POLICY_DIRECTORY)
    if policy is None or policy.get("mode") != "040000" or policy.get("type") != "tree":
        raise ReapprovalUnavailableError("The queue policy directory is not a Git tree")
    pending = [_sha(policy.get("sha"), "the queue policy tree")]
    seen: set[str] = set()
    walked = 0
    while pending:
        tree = pending.pop()
        if tree in seen:
            continue
        seen.add(tree)
        entries = await trees.entries(tree)
        walked += len(entries)
        if walked > _MAX_POLICY_ENTRIES:
            raise ReapprovalUnavailableError("The queue policy tree exceeds the entry budget")
        for row in entries.values():
            mode, kind = row.get("mode"), row.get("type")
            if mode == "040000" and kind == "tree":
                pending.append(_sha(row.get("sha"), "a queue policy subtree"))
            elif mode not in ("100644", "100755") or kind != "blob":
                raise ReapprovalUnavailableError(
                    "The queue policy tree contains an entry that is not a regular file or directory"
                )


async def _queue_policy_digest(
    scm: ScmProvider, owner: str, repo: str, base: str, workflow_ref: str | None
) -> str:
    if not workflow_ref or not workflow_ref.startswith(f"{owner}/{repo}/"):
        raise ReapprovalUnavailableError("The review workflow does not belong to the repository")
    workflow_path = workflow_path_from_ref(workflow_ref)
    if workflow_path is None:
        raise ReapprovalUnavailableError("The review workflow is unknown")
    trees = _Trees(scm, f"/repos/{owner}/{repo}")
    for path in (".mergecraft/config.yaml", workflow_path):
        entry = await trees.entry(base, path)
        if entry is None or entry.get("mode") not in ("100644", "100755"):
            raise ReapprovalUnavailableError("The queue config or workflow is not a regular file")
    await _verify_policy_tree(trees, base)
    return await review_policy_digest(
        scm, owner, repo, base, workflow_path=workflow_path, version=__version__
    )


async def prove_merge_group(
    scm: ScmProvider, group: MergeGroup, workflow_ref: str | None
) -> list[str]:
    """Prove every queue layer is precisely the delta of an approved open PR.

    Args:
        scm: GitHub API adapter for the repository's queue job.
        group: The bound native merge group event.
        workflow_ref: The Actions workflow ref used to bind the review policy.

    Returns:
        The source approvals, in queue order, for the group's check summary.

    Raises:
        ReapprovalUnavailableError: The available evidence cannot prove approval.
    """
    target = await _get_ref(scm, group, group.target_ref)
    if await _get_ref(scm, group, group.layer.ref) != group.layer.head:
        raise ReapprovalUnavailableError("The scheduled merge group was replaced")
    settings, _, _ = await _base_review_settings(scm, group.owner, group.repo, target)
    trusted = (
        trusted_check_apps(settings.merge_queue.trusted_check_apps) if settings else frozenset()
    )
    if not trusted:
        raise ReapprovalUnavailableError(
            "No dedicated approval App is trusted by the target config"
        )
    digest = await _queue_policy_digest(scm, group.owner, group.repo, target, workflow_ref)
    trees = _Trees(scm, group.api_root)
    layers = await _layers(scm, group, target)
    evidence: list[tuple[_QueueLayer, str, int]] = []
    for layer in reversed(layers):
        if await _merge_base(scm, group.api_root, layer.base, layer.head) != layer.base:
            raise ReapprovalUnavailableError("A queue layer does not descend from its stated base")
        head = await _pull_head(scm, group, layer.pull_number, target)
        prior = await _prior_pass(
            scm, group.owner, group.repo, head, trusted=trusted, all_runs=True
        )
        baseline = await _merge_base(scm, group.api_root, target, head)
        stamp = ReviewStamp(
            layer.pull_number, group.target_ref.removeprefix(_HEADS), digest, baseline
        )
        if prior.stamp != stamp:
            raise ReapprovalUnavailableError(
                f"PR #{layer.pull_number} has no matching review stamp"
            )
        reviewed = await _tree_delta(scm, group.api_root, trees, baseline, head)
        queued = await _tree_delta(scm, group.api_root, trees, layer.base, layer.head)
        if not reviewed or reviewed != queued:
            raise ReapprovalUnavailableError(
                f"PR #{layer.pull_number} differs from its queue layer"
            )
        evidence.append((layer, head, prior.check_id))

    for layer, head, check_id in evidence:
        current = await _prior_pass(
            scm, group.owner, group.repo, head, trusted=trusted, all_runs=True
        )
        if (
            current.check_id != check_id
            or await _get_ref(scm, group, layer.ref) != layer.head
            or await _pull_head(scm, group, layer.pull_number, target) != head
        ):
            raise ReapprovalUnavailableError(
                "The merge group or approval changed during validation"
            )
    if await _get_ref(scm, group, group.target_ref) != target:
        raise ReapprovalUnavailableError("The merge group's target moved during validation")
    return [
        f"PR #{layer.pull_number}: {head} (approval check {check_id})"
        for layer, head, check_id in evidence
    ]


async def queue_review_stamp(ctx: ToolContext, head_sha: str) -> ReviewStamp | None:
    """Attest the exact merge baseline from the finalized operator-owned PR checkout."""
    from mergecraft.mcp.tool_state import primary_repo_state

    snapshot = ctx.repo_settings_snapshot
    if (
        os.environ.get("GITHUB_EVENT_NAME") != "pull_request_target"
        or ConfigLocatorEnv().config_path
        or snapshot is None
        or not snapshot.operator_owned
        or not trusted_check_apps(snapshot.settings.review.merge_queue.trusted_check_apps)
    ):
        return None
    state = primary_repo_state(ctx.tool_state)
    if not state.reviewed_merge_base or state.checkout_sha != head_sha:
        return None
    event = ctx.gh_event or {}
    pull = event.get("pull_request")
    if not isinstance(pull, dict) or pull.get("number") != state.issue_number:
        return None
    base, head = pull.get("base"), pull.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict) or head.get("sha") != head_sha:
        return None
    base_sha, base_ref = base.get("sha"), base.get("ref")
    if (
        not isinstance(base_ref, str)
        or not isinstance(base_sha, str)
        or base_sha != os.environ.get("GITHUB_SHA")
        or base_sha != os.environ.get("GITHUB_WORKFLOW_SHA")
        or not isinstance(state.issue_number, int)
    ):
        return None
    digest = await _queue_policy_digest(
        ctx.scm, ctx.repo.owner, ctx.repo.name, base_sha, os.environ.get("GITHUB_WORKFLOW_REF")
    )
    return ReviewStamp(state.issue_number, base_ref, digest, state.reviewed_merge_base)


__all__ = ["MergeGroup", "bind_merge_group", "prove_merge_group", "queue_review_stamp"]
