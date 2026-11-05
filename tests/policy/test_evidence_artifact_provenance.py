"""A declared artifact counts only when the operator's own workflow uploaded it.

A JSON document saying ``status: ok`` is easy to write. What makes it evidence is
who ran the code that uploaded it. ``policy.evidence.<key>.artifact`` therefore
names the one workflow file allowed to upload the proof, and a workflow run's
artifact counts only when every one of these holds:

* the run executed exactly the declared workflow file (its ``path``);
* the pull request does not change that workflow file (a diff that touches it
  could make it upload anything);
* the run's head repository is the reviewed repository, not a fork;
* the run completed with ``success`` on the head commit.

A pull request that adds its own workflow, or a fork's run, can upload an artifact
with the right name and a perfect document; neither proves anything.

An artifact whose size GitHub did not report is refused before it is downloaded:
the size is the first bound on what the run will pull into memory.

The suite is written before the provenance checks exist, so it is red until they land.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.config.settings import ReviewSettings
from mergecraft.mcp.checkout import _apply_review_ignore
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.review_policy.ignore_paths import build_review_ignore
from tests.support.policy_evidence_fixtures import (
    ARTIFACT_NAME,
    DECLARED_WORKFLOW,
    DIFF_PATHS,
    HEAD_SHA,
    EvidenceGitHub,
    artifact_declaration,
    document_bytes,
    evidence_ctx,
    evidence_document,
    evidence_settings,
    settings_snapshot,
    workflow_run,
    zip_member,
)

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_FORGED_WORKFLOW = ".github/workflows/forged.yml"
_OTHER_WORKFLOW = ".github/workflows/nightly.yml"
_FORK = "attacker/demo"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


async def _collect(ctx: ToolContext, keys: list[str]) -> Any:
    producers = importlib.import_module("mergecraft.policy.evidence_producers")
    return await producers.collect_policy_evidence(ctx, required_keys=keys)


def _github(
    runs: list[dict[str, Any]], *, size: Any = "auto", omit_size: bool = False
) -> EvidenceGitHub:
    """Every listed run uploaded the declared artifact with a valid ``ok`` document."""
    raw = document_bytes(evidence_document(detail="rollback rehearsed against staging"))
    archive = zip_member(raw)
    artifacts: dict[int, list[dict[str, Any]]] = {}
    archives: dict[int, bytes] = {}
    for run in runs:
        run_id = int(run["id"])
        artifact: dict[str, Any] = {"id": 9000 + run_id, "name": ARTIFACT_NAME}
        if not omit_size:
            artifact["size_in_bytes"] = len(archive) if size == "auto" else size
        artifacts[run_id] = [artifact]
        archives[9000 + run_id] = archive
    return EvidenceGitHub(
        workflow_runs_by_sha={HEAD_SHA: runs},
        artifacts_by_run=artifacts,
        archives=archives,
    )


def _ctx(
    tmp_path: Path, github: EvidenceGitHub, *, diff_paths: tuple[str, ...] = DIFF_PATHS
) -> ToolContext:
    snapshot = settings_snapshot(
        tmp_path, evidence_settings({"rollback_plan": artifact_declaration()}), operator_owned=True
    )
    return evidence_ctx(tmp_path, github=github, snapshot=snapshot, diff_paths=diff_paths)


def _forged_run(run_id: int = 777) -> dict[str, Any]:
    """The verifier's forgery: a fork's own pull_request workflow, added in the diff."""
    run = workflow_run(run_id=run_id, path=_FORGED_WORKFLOW, head_repository=_FORK, fork=True)
    run["event"] = "pull_request"
    run["name"] = "forged"
    return run


def _reason(evidence: Any) -> str:
    assert "rollback_plan" in evidence.absent, evidence.present
    assert "rollback_plan" not in evidence.present
    return str(evidence.absent["rollback_plan"])


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


async def test_the_declared_untouched_same_repo_workflow_is_evidence(tmp_path: Path) -> None:
    """The control: the operator's workflow, unchanged by the diff, on this repository."""
    ctx = _ctx(tmp_path, _github([workflow_run()]))

    evidence = await _collect(ctx, ["rollback_plan"])

    record = evidence.present.get("rollback_plan")
    assert record is not None, evidence.absent
    assert record.source == "declared-artifact"
    assert DECLARED_WORKFLOW in record.detail, "the record must name the workflow that vouched"


async def test_a_forked_workflow_the_pull_request_adds_is_not_evidence(tmp_path: Path) -> None:
    """A fork adds ``forged.yml`` and uploads a perfect proof: it is still not evidence."""
    ctx = _ctx(
        tmp_path,
        _github([_forged_run()]),
        diff_paths=(*DIFF_PATHS, _FORGED_WORKFLOW),
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    assert DECLARED_WORKFLOW in _reason(evidence)


@pytest.mark.parametrize(
    ("run", "fragment"),
    [
        (workflow_run(head_repository=_FORK, fork=True), _FORK),
        (workflow_run(path=_OTHER_WORKFLOW), DECLARED_WORKFLOW),
        (workflow_run(path=None), DECLARED_WORKFLOW),
        (workflow_run(head_repository=None), "repository"),
    ],
    ids=[
        "fork-run-of-the-declared-workflow",
        "another-same-repo-workflow",
        "run-without-a-workflow-path",
        "run-without-a-head-repository",
    ],
)
async def test_an_artifact_from_any_other_run_is_not_evidence(
    tmp_path: Path, run: dict[str, Any], fragment: str
) -> None:
    """Right name, right document, wrong uploader: absent, and the reason says which."""
    ctx = _ctx(tmp_path, _github([run]))

    evidence = await _collect(ctx, ["rollback_plan"])

    assert fragment in _reason(evidence)


async def test_a_diff_that_edits_the_declared_workflow_voids_its_artifact(tmp_path: Path) -> None:
    """The pull request rewrote the workflow that vouches for it: nothing it uploads counts."""
    ctx = _ctx(
        tmp_path,
        _github([workflow_run()]),
        diff_paths=(*DIFF_PATHS, DECLARED_WORKFLOW),
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    assert DECLARED_WORKFLOW in _reason(evidence), "the reason must name the edited workflow"


async def test_mode_only_change_to_spaced_workflow_voids_artifact(tmp_path: Path) -> None:
    workflow = ".github/workflows/deploy proof.yml"
    github = _github([workflow_run(path=workflow)])
    snapshot = settings_snapshot(
        tmp_path,
        evidence_settings({"rollback_plan": artifact_declaration(workflow=workflow)}),
        operator_owned=True,
    )
    ctx = evidence_ctx(tmp_path, github=github, snapshot=snapshot)
    diff_path = primary_repo_state(ctx.tool_state).diff_path
    assert diff_path is not None
    await asyncio.to_thread(
        Path(diff_path).write_text,
        f"diff --git a/{workflow} b/{workflow}\nold mode 100644\nnew mode 100755\n",
    )
    evidence = await _collect(ctx, ["rollback_plan"])
    assert workflow in _reason(evidence)
    assert github.call_names() == []


@pytest.mark.parametrize("source", ["config", "input"])
async def test_an_ignored_workflow_edit_voids_its_artifact(tmp_path: Path, source: str) -> None:
    github = _github([workflow_run()])
    ctx = _ctx(tmp_path, github, diff_paths=(*DIFF_PATHS, DECLARED_WORKFLOW))
    ctx.tool_state.review_ignore = build_review_ignore(
        input_value=".github/workflows/**" if source == "input" else None,
        review=ReviewSettings(ignore_paths=[".github/workflows/**"] if source == "config" else []),
        source=source,
    )
    diff_path = Path(primary_repo_state(ctx.tool_state).diff_path or "")
    diff = await asyncio.to_thread(diff_path.read_text, encoding="utf-8")
    filtered, _, ignored = _apply_review_ignore(ctx, diff, unreviewable=[], truncated=False)
    assert DECLARED_WORKFLOW in ignored
    assert DECLARED_WORKFLOW not in filtered
    await asyncio.to_thread(diff_path.write_text, filtered, encoding="utf-8")

    evidence = await _collect(ctx, ["rollback_plan"])

    reason = _reason(evidence)
    assert DECLARED_WORKFLOW in reason
    assert "ignored" in reason
    assert github.call_names() == [], "refuse the proof before any artifact API call"


@pytest.mark.parametrize("missing", ["truncated", "unreviewable", "no-diff", "unreadable"])
async def test_unverifiable_workflow_changes_void_the_artifact(
    tmp_path: Path, missing: str
) -> None:
    github = _github([workflow_run()])
    ctx = _ctx(tmp_path, github)
    if missing == "truncated":
        ctx.tool_state.coverage.diff_truncated = True
    elif missing == "unreviewable":
        ctx.tool_state.coverage.unreviewable_paths = [DECLARED_WORKFLOW]
    elif missing == "no-diff":
        primary_repo_state(ctx.tool_state).diff_path = None
    else:
        await asyncio.to_thread(Path(primary_repo_state(ctx.tool_state).diff_path or "").unlink)

    evidence = await _collect(ctx, ["rollback_plan"])

    reason = _reason(evidence)
    assert "diff" in reason or "unreviewable" in reason
    assert github.call_names() == [], "unknown provenance must never reach the artifact API"


async def test_unrelated_omitted_paths_do_not_void_the_artifact(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _github([workflow_run()]))
    ctx.tool_state.ignored_review_paths = ["CHANGELOG.md"]
    ctx.tool_state.coverage.unreviewable_paths = ["assets/logo.png"]

    evidence = await _collect(ctx, ["rollback_plan"])

    assert "rollback_plan" in evidence.present, evidence.absent


async def test_the_declared_run_is_chosen_over_a_newer_forged_one(tmp_path: Path) -> None:
    """A forged run listed first must not shadow the operator's run."""
    ctx = _ctx(
        tmp_path,
        _github([_forged_run(run_id=777), workflow_run(run_id=501)]),
        diff_paths=(*DIFF_PATHS, _FORGED_WORKFLOW),
    )

    evidence = await _collect(ctx, ["rollback_plan"])

    record = evidence.present.get("rollback_plan")
    assert record is not None, evidence.absent
    assert "501" in record.detail
    assert "777" not in record.detail


# ---------------------------------------------------------------------------
# the archive size must be known before anything is downloaded
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("size", "omit_size"),
    [(None, False), ("1024", False), (None, True)],
    ids=["size-null", "size-a-string", "size-missing"],
)
async def test_an_artifact_of_unknown_size_is_never_downloaded(
    tmp_path: Path, size: Any, omit_size: bool
) -> None:
    """GitHub did not say how big it is: refuse it rather than download blind."""
    github = _github([workflow_run()], size=size, omit_size=omit_size)
    ctx = _ctx(tmp_path, github)

    evidence = await _collect(ctx, ["rollback_plan"])

    reason = _reason(evidence).casefold()
    assert "size" in reason
    assert "unknown" in reason
    assert "list_workflow_run_artifacts" in github.call_names(), "the artifact must be listed"
    assert "download_artifact_zip" not in github.call_names()


# ---------------------------------------------------------------------------
# "the PR did not change the workflow" needs the unfiltered, complete change set
# ---------------------------------------------------------------------------
#
# The review diff is filtered: ``review.ignorePaths`` (and the ``ignore_paths``
# input) drop whole files from it, and a files listing that hit its page cap is
# truncated. Neither may hide an edit to the declared workflow. The untouched check
# reads the unfiltered set — the review diff's paths plus
# ``ToolState.ignored_review_paths`` and ``ToolState.coverage.unreviewable_paths`` —
# and fails closed when that set is truncated or unavailable.


def _ignoring_ctx(tmp_path: Path, github: EvidenceGitHub) -> ToolContext:
    """An operator snapshot that ignores every workflow file in review."""
    from mergecraft.config.settings import RepoSettings

    settings = RepoSettings.model_validate(
        {
            "review": {"ignorePaths": [".github/workflows/**"]},
            "policy": {"evidence": {"rollback_plan": artifact_declaration()}},
        }
    )
    snapshot = settings_snapshot(tmp_path, settings, operator_owned=True)
    return evidence_ctx(tmp_path, github=github, snapshot=snapshot, diff_paths=DIFF_PATHS)


async def test_an_ignored_edit_to_the_declared_workflow_voids_its_artifact(
    tmp_path: Path,
) -> None:
    """``ignorePaths`` dropped the workflow from the review diff; the edit still counts."""
    github = _github([workflow_run()])
    ctx = _ignoring_ctx(tmp_path, github)
    ctx.tool_state.ignored_review_paths = [DECLARED_WORKFLOW]

    evidence = await _collect(ctx, ["rollback_plan"])

    reason = _reason(evidence)
    assert DECLARED_WORKFLOW in reason
    assert "ignore" in reason.casefold(), "the reason must say the edit was ignored in review"
    assert "download_artifact_zip" not in github.call_names()


async def test_an_unreviewable_edit_to_the_declared_workflow_voids_its_artifact(
    tmp_path: Path,
) -> None:
    """A workflow edit GitHub sent no patch for is still a change to the workflow."""
    github = _github([workflow_run()])
    ctx = _ctx(tmp_path, github)
    ctx.tool_state.coverage.unreviewable_paths = [DECLARED_WORKFLOW]

    evidence = await _collect(ctx, ["rollback_plan"])

    assert DECLARED_WORKFLOW in _reason(evidence)
    assert "download_artifact_zip" not in github.call_names()


async def test_a_truncated_change_set_cannot_prove_the_workflow_untouched(
    tmp_path: Path,
) -> None:
    """Files past the listing's page cap were never seen: the workflow may be among them."""
    github = _github([workflow_run()])
    ctx = _ctx(tmp_path, github)
    ctx.tool_state.coverage.diff_truncated = True

    evidence = await _collect(ctx, ["rollback_plan"])

    assert "truncat" in _reason(evidence).casefold()
    assert "download_artifact_zip" not in github.call_names()


@pytest.mark.parametrize("diff", ["none", "unreadable", "unparseable"])
async def test_an_unavailable_change_set_cannot_prove_the_workflow_untouched(
    tmp_path: Path, diff: str
) -> None:
    """No diff and no listing: the change set could not be verified, so nothing counts."""
    from mergecraft.mcp.tool_state import primary_repo_state

    github = _github([workflow_run()])
    ctx = _ctx(tmp_path, github)
    primary = primary_repo_state(ctx.tool_state)
    primary.diff_path = None if diff == "none" else str(tmp_path / "missing.diff")
    if diff == "unparseable":
        await asyncio.to_thread(
            (tmp_path / "missing.diff").write_text,
            'diff --git "a/broken\nold mode 100644\nnew mode 100755\n',
        )

    evidence = await _collect(ctx, ["rollback_plan"])

    reason = _reason(evidence)
    assert "could not be verified" in reason, reason
    assert "download_artifact_zip" not in github.call_names()


async def test_a_complete_unfiltered_change_set_without_the_workflow_counts(
    tmp_path: Path,
) -> None:
    """The control: workflows ignored in review, others ignored, nothing truncated."""
    github = _github([workflow_run()])
    ctx = _ignoring_ctx(tmp_path, github)
    ctx.tool_state.ignored_review_paths = [".github/workflows/lint.yml", "docs/changelog.md"]
    ctx.tool_state.coverage.unreviewable_paths = ["assets/logo.png"]
    ctx.tool_state.coverage.diff_truncated = False

    evidence = await _collect(ctx, ["rollback_plan"])

    record = evidence.present.get("rollback_plan")
    assert record is not None, evidence.absent
    assert DECLARED_WORKFLOW in record.detail


def test_the_policy_evidence_doc_states_the_fail_closed_change_set_rule() -> None:
    """Operators must read that ignored or truncated changes never let a proof count."""
    from pathlib import Path as _Path

    doc = (_Path(__file__).resolve().parents[2] / "docs" / "policy-evidence.md").read_text(
        encoding="utf-8"
    )
    lowered = " ".join(doc.casefold().split())

    assert "ignorepaths" in lowered
    assert "truncated" in lowered
    assert "could not be verified" in lowered
