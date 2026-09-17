"""C5-F2 — ``run_ci_intelligence`` must feed check runs into C-D2 ingest.

``collect_ci_coverage_findings`` / ``collect_ci_mutation_findings`` only treat a
declared-failed check as a finding (and skip the artifact download) when
``check_runs`` is supplied. The SARIF sibling lists check runs and passes them
through; the intelligence sibling must do the same.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.ci.evidence import ci_evidence_findings
from mergecraft.ci.intelligence import run_ci_intelligence
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.scm.types import ListedItems
from mergecraft.utils.github import GitHubClient
from tests.ci.support_crap import (
    CRAP_FIXTURES,
    load_diff,
    load_mutation,
    load_source,
    zip_artifact,
)

if TYPE_CHECKING:
    from pathlib import Path

HEAD_SHA = "cafebabecafebabecafebabecafebabecafebabe"


class _IntelligenceGitHub(GitHubClient):
    """Serves check-suite runs, failed check runs, and a downloadable artifact."""

    def __init__(
        self,
        *,
        artifacts: list[dict[str, Any]],
        archives: dict[int, bytes],
        check_runs: list[dict[str, Any]],
    ) -> None:
        super().__init__(token="test-token")
        self.artifacts = artifacts
        self.archives = archives
        self.check_runs = check_runs
        self.check_run_refs: list[str] = []
        self.download_calls = 0
        self.downloaded_ids: list[int] = []

    async def list_workflow_runs_for_check_suite(
        self, owner: str, repo: str, check_suite_id: int
    ) -> ListedItems:
        _ = (owner, repo, check_suite_id)
        return ListedItems(items=[{"id": 88, "head_sha": HEAD_SHA}], incomplete=False)

    async def list_check_runs_for_ref(
        self,
        owner: str,
        repo: str,
        ref: str,
        **kwargs: Any,
    ) -> ListedItems:
        _ = (owner, repo, kwargs)
        self.check_run_refs.append(ref)
        return ListedItems(
            items=list(self.check_runs),
            incomplete=False,
            total_count=len(self.check_runs),
        )

    async def list_workflow_run_artifacts(self, owner: str, repo: str, run_id: int) -> ListedItems:
        _ = (owner, repo, run_id)
        return ListedItems(items=list(self.artifacts), incomplete=False)

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        _ = (owner, repo)
        self.download_calls += 1
        self.downloaded_ids.append(artifact_id)
        return self.archives[artifact_id]


def _failed_check_run(name: str) -> dict[str, Any]:
    check_run = json.loads(
        (CRAP_FIXTURES / "ingest" / "declared-failed" / "check-run.json").read_text(
            encoding="utf-8"
        )
    )
    check_run["name"] = name
    return check_run


def _ctx(
    tmp_path: Path,
    *,
    github: GitHubClient,
    ci_coverage_artifacts: list[str] | None = None,
    ci_mutation_artifacts: list[str] | None = None,
) -> ToolContext:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "mod.py").write_text(load_source("watch"), encoding="utf-8")
    diff_path = tmp_path / "change.diff"
    diff_path.write_text(load_diff("watch"), encoding="utf-8")
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    repo = primary_repo_state(state)
    repo.checkout_sha = HEAD_SHA
    repo.diff_path = str(diff_path)
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=42, is_pr=True),
            status_checks=True,
            shell="restricted",
        ),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
        resolved_model="claude-sonnet-4-5",
        ci_coverage_artifacts=ci_coverage_artifacts,
        ci_mutation_artifacts=ci_mutation_artifacts,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ctx_field", "artifact_name", "artifact_id", "zip_name", "document"),
    [
        (
            "ci_coverage_artifacts",
            "coverage-json",
            7,
            "coverage.json",
            (CRAP_FIXTURES / "ingest" / "declared-success" / "coverage.json").read_text(
                encoding="utf-8"
            ),
        ),
        (
            "ci_mutation_artifacts",
            "mutation-json",
            11,
            "mutmut-survivor.json",
            load_mutation("mutmut-survivor.json"),
        ),
    ],
    ids=["coverage-json", "mutation-json"],
)
async def test_run_ci_intelligence_declared_failed_check_emits_finding_never_downloads(
    tmp_path: Path,
    ctx_field: str,
    artifact_name: str,
    artifact_id: int,
    zip_name: str,
    document: str,
) -> None:
    """C-D2 via the intelligence sibling: failed check → finding, never a receipt."""
    github = _IntelligenceGitHub(
        artifacts=[{"id": artifact_id, "name": artifact_name}],
        archives={artifact_id: zip_artifact(zip_name, document)},
        check_runs=[_failed_check_run(artifact_name)],
    )
    ctx = _ctx(tmp_path, github=github, **{ctx_field: [artifact_name]})

    await run_ci_intelligence(ctx, check_suite_id=9)

    recorded = ci_evidence_findings(ctx.tool_state)
    assert recorded, "declared-failed check must become a recorded CI finding"
    assert [item.source for item in recorded] == ["ci"]
    assert [item.rule_id for item in recorded] == ["check-run/failure"]
    assert not any(getattr(item, "status", None) == "satisfied-by-ci" for item in recorded)
    assert ctx.tool_state.ci_evidence is not None
    assert ctx.tool_state.ci_evidence.substitutions == []
    assert github.download_calls == 0
    assert artifact_id not in github.downloaded_ids
    assert github.check_run_refs, "intelligence must list check runs like sarif ingest"
