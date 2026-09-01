"""W1.3 — green-CI SARIF ingest contracts (lane D, green after W4)."""

from __future__ import annotations

import importlib
import json
from io import BytesIO
from typing import TYPE_CHECKING, Any
from zipfile import ZipFile

import pytest
from scripts.workflow_yaml import permission_dict

from mergecraft.ci.evidence import ci_evidence_findings
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.scm.types import ListedItems
from mergecraft.utils.github import GitHubClient
from tests.ci.workflow_support import job, load_workflow

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_HEAD_SHA = "cafebabecafebabecafebabecafebabecafebabe"


def _import_ingest_callable():
    module = importlib.import_module("mergecraft.main")
    fn = getattr(module, "ingest_ci_sarif_after_ci_wait", None)
    if fn is None:
        pytest.fail("mergecraft.main.ingest_ci_sarif_after_ci_wait is not defined yet")
    return fn


def _sarif_document(tool: str = "ruff") -> str:
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": tool}},
                    "results": [
                        {
                            "ruleId": "F401",
                            "level": "error",
                            "message": {"text": "lint"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "src/a.py"},
                                        "region": {"startLine": 1},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _zip_bytes(name: str, document: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(name, document)
    return buffer.getvalue()


class _ArtifactGitHub(GitHubClient):
    def __init__(
        self,
        *,
        artifacts: list[dict[str, Any]],
        archives: dict[int, bytes],
        head_sha_runs: list[dict[str, Any]] | None = None,
        download_error: Exception | None = None,
    ) -> None:
        super().__init__(token="test-token")
        self.artifacts = artifacts
        self.archives = archives
        self.head_sha_runs = head_sha_runs or [{"id": 901, "head_sha": _HEAD_SHA}]
        self.head_sha_queries: list[str] = []
        self._download_error = download_error

    async def get(self, path: str, **kwargs: Any) -> Any:
        params = kwargs.get("params") or {}
        if path.endswith("/actions/runs") and params.get("head_sha"):
            self.head_sha_queries.append(str(params["head_sha"]))
            return {"workflow_runs": self.head_sha_runs}
        return {"workflow_runs": []}

    async def list_workflow_run_artifacts(self, owner: str, repo: str, run_id: int) -> ListedItems:
        _ = (owner, repo, run_id)
        return ListedItems(
            items=list(self.artifacts), incomplete=False, total_count=len(self.artifacts)
        )

    async def download_artifact_zip(self, owner: str, repo: str, artifact_id: int) -> bytes:
        _ = (owner, repo)
        if self._download_error is not None:
            raise self._download_error
        return self.archives[artifact_id]


def _tool_context(tmp_path: Path, github: GitHubClient) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_target")),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        ci_sarif_artifacts=["ruff-sarif", "mypy-sarif", "bandit-sarif"],
    )


@pytest.mark.asyncio
async def test_green_wait_ingests_declared_artifacts(tmp_path: Path) -> None:
    """D9 — ``state=complete`` + ``failed_count=0`` still downloads declared SARIF."""
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    ctx = _tool_context(tmp_path, github)
    ingest = _import_ingest_callable()
    await ingest(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
    )
    assert ci_evidence_findings(ctx.tool_state), "ingest must record SARIF findings"


@pytest.mark.asyncio
async def test_green_wait_lists_workflow_runs_for_head_sha_not_only_failed_suite(
    tmp_path: Path,
) -> None:
    """D9 — ingest must list workflow runs for the head SHA, not only a failed suite id."""
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: _zip_bytes("ruff.sarif.json", _sarif_document())},
    )
    ctx = _tool_context(tmp_path, github)
    ingest = _import_ingest_callable()
    await ingest(
        ctx,
        ci_wait_state="complete",
        ci_failed_count=0,
        head_sha=_HEAD_SHA,
        check_suite_id=None,
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
    github = _ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: b""},
        download_error=PermissionError("artifact download forbidden"),
    )
    ctx = _tool_context(tmp_path, github)
    ingest = _import_ingest_callable()
    await ingest(
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
