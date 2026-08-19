"""URL-encoding tests for the label MCP tools (issue #260).

``remove_labels`` must percent-encode the label into the delete path, or a
label containing ``/`` or a space shifts or corrupts the path segment. Note the
encoded segment is the **label**, not the repository name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.labels import remove_labels_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

ISSUE_NUMBER = 42
BASE_PATH = f"/repos/acme/demo/issues/{ISSUE_NUMBER}/labels/"


class _RecordingGitHub(GitHubClient):
    """Records the delete paths the label tool issues."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.delete_paths: list[str] = []

    async def get_issue(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> dict[str, Any]:
        return {"number": issue_number}

    async def delete(self, path: str, **kwargs: Any) -> Any:
        self.delete_paths.append(path)
        return {}


def _ctx(tmp_path: Path, github: GitHubClient) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request", is_pr=True)),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


async def test_plain_label_delete_url_is_unchanged(tmp_path: Path) -> None:
    github = _RecordingGitHub()

    result = await remove_labels_tool(_ctx(tmp_path, github)).execute(
        {"issue_number": ISSUE_NUMBER, "labels": ["bug"]}
    )
    assert result.is_error is False, result.content[0]["text"]
    payload = json.loads(result.content[0]["text"])
    assert payload["removed"] == ["bug"]
    assert github.delete_paths == [f"{BASE_PATH}bug"]


@pytest.mark.parametrize(
    ("label", "encoded"),
    [
        ("area/mcp", "area%2Fmcp"),
        ("needs info", "needs%20info"),
        ("../evil", "..%2Fevil"),
    ],
)
async def test_label_name_is_percent_encoded_in_delete_url(
    tmp_path: Path, label: str, encoded: str
) -> None:
    github = _RecordingGitHub()

    result = await remove_labels_tool(_ctx(tmp_path, github)).execute(
        {"issue_number": ISSUE_NUMBER, "labels": [label]}
    )
    assert result.is_error is False, result.content[0]["text"]
    # Only the label segment is encoded; the repo/issue segments stay literal.
    assert github.delete_paths == [f"{BASE_PATH}{encoded}"]
