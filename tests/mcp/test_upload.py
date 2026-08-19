"""Path-confinement tests for the ``upload_file`` MCP tool (issue #258 / D8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.mcp.upload import upload_file_tool
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

SECRET_MARKER = "root:x:0:0:stand-in for /etc/passwd"


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    return root


@pytest.fixture
def scratch(tmp_path: Path) -> Path:
    scratch_dir = (tmp_path / "scratch").resolve()
    scratch_dir.mkdir()
    return scratch_dir


@pytest.fixture
def outside_file(tmp_path: Path) -> Path:
    """A readable file outside both the repo root and the tmpdir."""
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text(f"{SECRET_MARKER}\n", encoding="utf-8")
    return secret


@pytest.fixture
def symlink_into_outside(repo_root: Path, outside_file: Path) -> Path:
    """An in-repo symlink whose target escapes the repo root."""
    link = repo_root / "evidence-link.txt"
    link.symlink_to(outside_file)
    return link


@pytest.fixture
def traversal_path(repo_root: Path, outside_file: Path) -> str:
    return str(repo_root / ".." / "outside" / outside_file.name)


@pytest.fixture
def in_repo_file(repo_root: Path) -> Path:
    source = repo_root / "report.txt"
    source.write_text("finding evidence\n", encoding="utf-8")
    return source


@pytest.fixture
def in_tmpdir_file(scratch: Path) -> Path:
    source = scratch / "artifact.txt"
    source.write_text("scratch evidence\n", encoding="utf-8")
    return source


@pytest.fixture
def ctx(repo_root: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch) -> ToolContext:
    # BYOK: no upload API configured, so the tool takes the local file:// path.
    monkeypatch.delenv("MERGECRAFT_API_URL", raising=False)
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(repo_root)),
        mcp_server_url="",
        tmpdir=str(scratch),
    )


async def test_path_outside_repo_and_tmpdir_rejected(ctx: ToolContext, outside_file: Path) -> None:
    result = await upload_file_tool(ctx).execute({"path": str(outside_file)})
    assert result.is_error is True
    # No file:// URI may be handed back for a path that failed confinement.
    assert "file://" not in result.content[0]["text"]


async def test_symlink_escape_rejected(ctx: ToolContext, symlink_into_outside: Path) -> None:
    result = await upload_file_tool(ctx).execute({"path": str(symlink_into_outside)})
    assert result.is_error is True
    assert SECRET_MARKER not in result.content[0]["text"]


async def test_relative_traversal_out_of_repo_rejected(
    ctx: ToolContext, traversal_path: str
) -> None:
    result = await upload_file_tool(ctx).execute({"path": traversal_path})
    assert result.is_error is True


async def test_in_repo_file_still_uploads_in_byok_mode(
    ctx: ToolContext, in_repo_file: Path
) -> None:
    result = await upload_file_tool(ctx).execute({"path": str(in_repo_file)})
    assert result.is_error is False, result.content[0]["text"]
    payload = json.loads(result.content[0]["text"])
    assert payload["success"] is True
    assert payload["filename"] == "report.txt"
    assert payload["publicUrl"].startswith("file://")


async def test_tmpdir_file_still_uploads_in_byok_mode(
    ctx: ToolContext, in_tmpdir_file: Path
) -> None:
    result = await upload_file_tool(ctx).execute({"path": str(in_tmpdir_file)})
    assert result.is_error is False, result.content[0]["text"]
    payload = json.loads(result.content[0]["text"])
    assert payload["success"] is True
    assert payload["filename"] == "artifact.txt"
