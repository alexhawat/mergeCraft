"""Provenance of a workflow artifact a pull request cannot have forged.

Two readers accept an artifact uploaded by a GitHub Actions run as evidence about
a pull request: the fail-then-pass receipt (``mergecraft.ci.sarif_ingest``) and
the declared policy proofs (``mergecraft.policy.evidence_producers``). Both are
fail-closed trust boundaries with the same questions, answered here once:

* did the pull request leave the declared workflow file untouched, judged on the
  full change set and not the review-filtered diff (:func:`require_workflow_untouched`);
* which runs on the head commit executed exactly that workflow, from the reviewed
  repository, and succeeded (:func:`provenanced_runs`);
* which of those runs uploaded the declared artifact within the caller's size
  cap, and its bytes (:func:`declared_artifact_archive`).

Each caller keeps its own refusal type and detail wording through ``refuse`` and
``short``; the decisions are shared so a hardening fix lands in both.

Exports:
    Refuse: The ``refuse`` callback type.
    workflow_path: Normalise a declared workflow path.
    head_repository: The ``owner/name`` a run's head came from.
    provenanced_runs: The runs whose upload may count.
    require_workflow_untouched: Fail closed unless the change set shows the workflow untouched.
    declared_artifact_archive: Download the declared artifact of a provenanced run.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from mergecraft.utils.github import GitHubClient

    Refuse = Callable[[str], Exception]
    """Build the caller's refusal from a detail line; the helpers raise what it returns."""


def workflow_path(value: object) -> str:
    """Normalise a workflow path: stripped, without a leading ``./``; ``""`` when not a string."""
    return value.strip().removeprefix("./") if isinstance(value, str) else ""


def head_repository(run: Mapping[str, Any]) -> str:
    """The ``owner/name`` of the run's head repository, or ``""`` when unknown."""
    repository = run.get("head_repository")
    name = repository.get("full_name") if isinstance(repository, dict) else None
    return name.strip() if isinstance(name, str) else ""


def _same_sha(value: object, head: str) -> bool:
    return isinstance(value, str) and bool(head) and value.strip().lower() == head.lower()


def _run_id(run: Mapping[str, Any]) -> int:
    value = run.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def provenanced_runs(
    runs: Sequence[Mapping[str, Any]],
    *,
    head: str,
    workflow: str,
    repo: str,
    label: str,
    refuse: Refuse,
    short: Callable[[str], str],
) -> list[Mapping[str, Any]]:
    """Return the runs whose upload may count: the declared workflow, this repo, success.

    A run counts only when it executed exactly the declared workflow file, its head
    repository is the reviewed repository (never a fork, never unknown), and it
    completed with ``success`` on the head commit. Every other run is ignored, so a
    forged run listed beside the operator's can never shadow it.

    Args:
        runs (Sequence[Mapping[str, Any]]): Workflow runs listed for the head commit.
        head (str): The head commit SHA.
        workflow (str): The declared workflow path (see :func:`workflow_path`).
        repo (str): The reviewed repository as ``owner/name``.
        label (str): What is being proved, for the detail lines.
        refuse (Refuse): Builds the exception raised when no run may count.
        short (Callable[[str], str]): Renders a SHA for the detail lines.

    Returns:
        list[Mapping[str, Any]]: The runs that may have uploaded ``label``.
    """
    on_head = [run for run in runs if _same_sha(run.get("head_sha"), head)]
    if not on_head:
        raise refuse(
            f"no workflow run on the head commit {short(head)} could have uploaded {label}"
        )
    declared = [run for run in on_head if workflow_path(run.get("path")) == workflow]
    if not declared:
        seen = sorted({workflow_path(run.get("path")) or "no workflow path" for run in on_head})
        raise refuse(
            f"no run of the declared workflow {workflow} on the head commit {short(head)} "
            f"could have uploaded {label} (runs seen: {', '.join(seen)})"
        )
    same_repo: list[Mapping[str, Any]] = []
    foreign: list[str] = []
    for run in declared:
        origin = head_repository(run)
        if origin.lower() == repo.lower():
            same_repo.append(run)
        elif origin:
            foreign.append(f"run {run.get('id')} came from {origin}")
        else:
            foreign.append(f"run {run.get('id')} has no head repository")
    if not same_repo:
        raise refuse(
            f"no run of {workflow} on the head commit came from the reviewed repository "
            f"{repo}, so {label} cannot count ({'; '.join(foreign)})"
        )
    succeeded = [
        run
        for run in same_repo
        if run.get("status") == "completed" and run.get("conclusion") == "success"
    ]
    if not succeeded:
        raise refuse(
            f"no run of {workflow} on the head commit {short(head)} that uploads {label} succeeded"
        )
    return succeeded


def require_workflow_untouched(state: Any, *, workflow: str, label: str, refuse: Refuse) -> None:
    """Fail closed unless the full, unfiltered change set shows ``workflow`` untouched.

    The review diff is filtered: ``review.ignorePaths`` and the ``ignore_paths``
    input drop whole files from it, and GitHub sends no patch for some files. The
    change set judged here is therefore the review diff's paths (rename sources
    included) plus every path the review ignored (``ToolState.ignored_review_paths``)
    plus every path it could not review (``ToolState.coverage.unreviewable_paths``).
    A diff that is missing or unreadable, or a files listing that was truncated,
    cannot show the workflow untouched, so nothing counts then either.

    Args:
        state (Any): The run's ``ToolState``.
        workflow (str): The declared workflow path (see :func:`workflow_path`).
        label (str): What is being proved, for the detail lines.
        refuse (Refuse): Builds the exception raised when the workflow may be changed.
    """
    from mergecraft.mcp.tool_state import primary_repo_state
    from mergecraft.utils.diff_paths import changed_paths_from_diff

    unverified = (
        f"whether this pull request changes the declared workflow {workflow} could not be "
        f"verified, so {label} cannot count"
    )
    coverage = getattr(state, "coverage", None)
    if getattr(coverage, "diff_truncated", False):
        raise refuse(f"{unverified}: the pull request's diff file listing was truncated")
    diff_path = primary_repo_state(state).diff_path
    if not diff_path:
        raise refuse(f"{unverified}: the review has no diff")
    try:
        text = Path(diff_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise refuse(f"{unverified}: the diff could not be read ({type(exc).__name__})") from exc
    reviewed = {workflow_path(path) for path in changed_paths_from_diff(text)}
    ignored = {workflow_path(path) for path in getattr(state, "ignored_review_paths", ())}
    unreviewable = {
        workflow_path(path) for path in getattr(coverage, "unreviewable_paths", ()) or ()
    }
    if workflow in ignored:
        raise refuse(
            f"this pull request changes the declared workflow {workflow}; the change was "
            f"ignored in review (ignorePaths) but still voids {label}"
        )
    if workflow in unreviewable:
        raise refuse(
            f"this pull request changes the declared workflow {workflow} (GitHub sent no "
            f"reviewable patch for it, so the path is unreviewable in the diff), so nothing "
            f"it uploads counts as {label}"
        )
    if workflow in reviewed:
        raise refuse(
            f"this pull request changes the declared workflow {workflow}, so nothing it "
            f"uploads counts as {label}"
        )


async def declared_artifact_archive(
    client: GitHubClient,
    *,
    owner: str,
    repo: str,
    runs: Sequence[Mapping[str, Any]],
    artifact: str,
    label: str,
    max_bytes: int,
    refuse: Refuse,
) -> tuple[Mapping[str, Any], bytes]:
    """Return ``(run, archive bytes)`` for the declared artifact of a provenanced run.

    Runs are tried newest first. An artifact is refused before download when it has
    expired, reports no usable size, or is listed past ``max_bytes``; what was
    downloaded is refused again past the cap. A listing or download failure is a
    refusal, never a crash.

    Args:
        client (GitHubClient): The GitHub client for listings and downloads.
        owner (str): Repository owner.
        repo (str): Repository name.
        runs (Sequence[Mapping[str, Any]]): The runs from :func:`provenanced_runs`.
        artifact (str): The declared artifact name.
        label (str): What is being proved, for the detail lines.
        max_bytes (int): The largest archive ever downloaded; the caller's cap.
        refuse (Refuse): Builds the exception raised when no artifact may count.

    Returns:
        tuple[Mapping[str, Any], bytes]: The run that uploaded it and the archive bytes.
    """
    for run in sorted(runs, key=_run_id, reverse=True):
        run_id = _run_id(run)
        try:
            artifacts = await client.list_workflow_run_artifacts(owner, repo, run_id)
        except Exception as exc:  # a transport failure is a refusal, never a crash
            raise refuse(
                f"the artifacts of workflow run {run_id} could not be listed for {label} "
                f"({type(exc).__name__})"
            ) from exc
        if artifacts.incomplete:
            raise refuse(
                f"the artifact listing of workflow run {run_id} was incomplete, "
                f"so {label} is unconfirmed"
            )
        for item in artifacts.items:
            if not isinstance(item, dict) or item.get("name") != artifact:
                continue
            if item.get("expired"):
                raise refuse(f"{label} from workflow run {run_id} has expired")
            size = item.get("size_in_bytes")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise refuse(
                    f"{label} from workflow run {run_id} reports an unknown size, so it was "
                    "not downloaded"
                )
            if size > max_bytes:
                raise refuse(f"{label} is a {size}-byte archive, past the {max_bytes}-byte limit")
            artifact_id = item.get("id")
            if not isinstance(artifact_id, int) or isinstance(artifact_id, bool):
                continue
            try:
                archive = await client.download_artifact_zip(owner, repo, artifact_id)
            except Exception as exc:  # a transport failure is a refusal, never a crash
                raise refuse(
                    f"{label} could not be downloaded from workflow run {run_id} "
                    f"({type(exc).__name__})"
                ) from exc
            if len(archive) > max_bytes:
                raise refuse(f"{label} is past the {max_bytes}-byte archive limit")
            return run, bytes(archive)
    raise refuse(f"no successful run of the declared workflow on the head commit uploaded {label}")


__all__ = [
    "Refuse",
    "declared_artifact_archive",
    "head_repository",
    "provenanced_runs",
    "require_workflow_untouched",
    "workflow_path",
]
