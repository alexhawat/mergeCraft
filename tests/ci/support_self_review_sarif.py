"""Shared builders for lane-D self-review SARIF ingest tests (W4 / W5)."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from zipfile import ZipFile

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.scm.types import ListedItems
from mergecraft.utils.github import GitHubClient

_HEAD_SHA = "cafebabecafebabecafebabecafebabecafebabe"


def head_sha() -> str:
    """Canonical PR head SHA used across W4 ingest fixtures."""
    return _HEAD_SHA


def sarif_document(tool: str = "ruff") -> str:
    """Minimal SARIF 2.1.0 document for ingest tests."""
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


def zip_bytes(name: str, document: str) -> bytes:
    """Zip a single SARIF document for artifact download stubs."""
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(name, document)
    return buffer.getvalue()


class ArtifactGitHub(GitHubClient):
    """GitHub client stub that serves workflow runs and SARIF artifact zips."""

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


def tool_context(tmp_path: Any, github: GitHubClient) -> ToolContext:
    """Build a ToolContext with GitHub client and default ciEvidence artifact names."""
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


def tool_context_with_scm(tmp_path: Any, scm: Any) -> ToolContext:
    """Build a ToolContext with a non-GitHub SCM provider."""
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_target")),
        scm=scm,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        ci_sarif_artifacts=["ruff-sarif", "mypy-sarif", "bandit-sarif"],
    )
