"""W1.3 — green-CI SARIF ingest contracts (lane D, green after W4)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import yaml
from scripts.workflow_yaml import permission_dict

from mergecraft.ci.evidence import ci_evidence_findings
from mergecraft.ci.sarif_ingest import ingest_ci_sarif_after_ci_wait
from tests.ci.support_self_review_sarif import (
    ArtifactGitHub,
    head_sha,
    sarif_document,
    tool_context,
    tool_context_with_scm,
    zip_bytes,
)
from tests.ci.workflow_support import job, load_workflow, read_text
from tests.scm.support import RecordingScmProvider

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_HEAD_SHA = head_sha()
_WAIT_ENV_FORWARD = (
    ("MERGECRAFT_CI_WAIT_STATE", "${{ needs.wait-for-ci.outputs.state }}"),
    ("MERGECRAFT_CI_FAILED_COUNT", "${{ needs.wait-for-ci.outputs.failed_count }}"),
    ("CI_STATE", "${{ needs.wait-for-ci.outputs.state }}"),
    ("CI_FAILED_COUNT", "${{ needs.wait-for-ci.outputs.failed_count }}"),
)


@pytest.mark.asyncio
async def test_green_wait_ingests_declared_artifacts(tmp_path: Path) -> None:
    """D9 — ``state=complete`` + ``failed_count=0`` still downloads declared SARIF."""
    github = ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: zip_bytes("ruff.sarif.json", sarif_document())},
    )
    ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_after_ci_wait(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert ci_evidence_findings(ctx.tool_state), "ingest must record SARIF findings"


@pytest.mark.asyncio
async def test_red_ci_complete_still_ingests_declared_artifacts(tmp_path: Path) -> None:
    """D9 — ``state=complete`` with failed jobs still ingests declared SARIF."""
    github = ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: zip_bytes("ruff.sarif.json", sarif_document())},
    )
    ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_after_ci_wait(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=2,
        head_sha=_HEAD_SHA,
    )
    assert github.head_sha_queries == [_HEAD_SHA]
    assert ci_evidence_findings(ctx.tool_state)


@pytest.mark.asyncio
async def test_green_wait_lists_workflow_runs_for_head_sha_not_only_failed_suite(
    tmp_path: Path,
) -> None:
    """D9 — ingest must list workflow runs for the head SHA, not only a failed suite id."""
    github = ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: zip_bytes("ruff.sarif.json", sarif_document())},
    )
    ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_after_ci_wait(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert github.head_sha_queries == [_HEAD_SHA]


@pytest.mark.asyncio
async def test_artifact_download_403_logs_warning_and_continues(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — download failures are best-effort; the review must continue."""
    warnings: list[str] = []
    from mergecraft.utils import gha_log

    monkeypatch.setattr(gha_log, "warning", lambda msg: warnings.append(msg))
    github = ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: b""},
        download_error=PermissionError("artifact download forbidden"),
    )
    ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_after_ci_wait(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert warnings, "403 download must emit a warning"
    assert not ci_evidence_findings(ctx.tool_state)


def test_mergecraft_yml_review_job_includes_actions_read() -> None:
    """D10 — dogfood review job needs ``actions: read`` to download ``ci.yml`` artifacts."""
    perms = permission_dict(job(load_workflow("mergecraft.yml"), "review").get("permissions"))
    assert perms.get("actions") == "read"


def test_hardened_example_review_job_includes_actions_read() -> None:
    """D10 — hardened consumer template grants ``actions: read`` for ciEvidence ingest."""
    doc = yaml.safe_load(read_text("examples/workflows/mergecraft-hardened.yml"))
    assert isinstance(doc, dict)
    perms = permission_dict(doc.get("permissions"))
    assert perms.get("actions") == "read"


def test_hardened_example_review_job_forwards_wait_env_for_sarif_ingest() -> None:
    """D10 — hardened template forwards wait-for-ci outputs for action-side SARIF ingest."""
    doc = yaml.safe_load(read_text("examples/workflows/mergecraft-hardened.yml"))
    assert isinstance(doc, dict)
    jobs = doc.get("jobs")
    assert isinstance(jobs, dict)
    review = jobs.get("review")
    assert isinstance(review, dict)
    env = review.get("env")
    assert isinstance(env, dict)
    for key, expected in _WAIT_ENV_FORWARD:
        assert env.get(key) == expected


@pytest.mark.asyncio
async def test_ingest_skips_when_ci_wait_state_not_complete(tmp_path: Path) -> None:
    """D9 — non-complete wait state must not list workflow runs or record findings."""
    github = ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: zip_bytes("ruff.sarif.json", sarif_document())},
    )
    ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_after_ci_wait(
        ctx,
        ci_wait_state="pending",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert not github.head_sha_queries
    assert not ci_evidence_findings(ctx.tool_state)


@pytest.mark.asyncio
async def test_ingest_skips_when_head_sha_blank(tmp_path: Path) -> None:
    """D9 — blank head SHA must short-circuit before workflow listing."""
    github = ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: zip_bytes("ruff.sarif.json", sarif_document())},
    )
    ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_after_ci_wait(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha="   ",
    )
    assert not github.head_sha_queries
    assert not ci_evidence_findings(ctx.tool_state)


@pytest.mark.asyncio
async def test_ingest_skips_without_github_client(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — non-GitHub SCM must skip SARIF ingest with a warning."""
    warnings: list[str] = []
    from mergecraft.utils import gha_log

    monkeypatch.setattr(gha_log, "warning", lambda msg: warnings.append(msg))
    ctx = tool_context_with_scm(tmp_path, RecordingScmProvider())
    await ingest_ci_sarif_after_ci_wait(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert warnings
    assert any("no GitHub client" in msg for msg in warnings)
    assert not ci_evidence_findings(ctx.tool_state)


@pytest.mark.asyncio
async def test_ingest_workflow_listing_error_logs_warning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — workflow run listing failures are best-effort warnings."""
    warnings: list[str] = []
    from mergecraft.utils import gha_log

    monkeypatch.setattr(gha_log, "warning", lambda msg: warnings.append(msg))

    class ListingErrorGitHub(ArtifactGitHub):
        async def list_workflow_runs_for_head_sha(
            self,
            owner: str,
            repo: str,
            head_sha: str,
        ) -> Any:
            _ = (owner, repo, head_sha)
            raise RuntimeError("workflow listing failed")

    github = ListingErrorGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: zip_bytes("ruff.sarif.json", sarif_document())},
    )
    ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_after_ci_wait(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert warnings
    assert any("workflow run listing failed" in msg for msg in warnings)
    assert not ci_evidence_findings(ctx.tool_state)


@pytest.mark.asyncio
async def test_ingest_workflow_listing_incomplete_logs_warning(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — truncated workflow run listing must not be treated as complete."""
    warnings: list[str] = []
    from mergecraft.utils import gha_log

    monkeypatch.setattr(gha_log, "warning", lambda msg: warnings.append(msg))

    class IncompleteListingGitHub(ArtifactGitHub):
        async def list_workflow_runs_for_head_sha(
            self,
            owner: str,
            repo: str,
            head_sha: str,
        ) -> Any:
            _ = (owner, repo, head_sha)
            from mergecraft.scm.types import ListedItems

            return ListedItems(items=[], incomplete=True)

    github = IncompleteListingGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: zip_bytes("ruff.sarif.json", sarif_document())},
    )
    ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_after_ci_wait(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert warnings
    assert any("listing truncated" in msg for msg in warnings)
    assert not ci_evidence_findings(ctx.tool_state)
