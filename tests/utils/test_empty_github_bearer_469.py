"""#469 — empty GitHub token must not build ``Authorization: Bearer ``.

Locked D4 (open-issues-sweep-2026-08-24-a):

- Do not set ``Authorization`` when the token is empty or whitespace-only.
- An offline / tokenless ``get_commit_info`` reports the tool unavailable and
  names the missing token — not httpx ``Illegal header value b'Bearer '``.
- No HTTP request is constructed with an empty Bearer header.

These assertions fail until the AC implementation wave. Do not xfail: RED is
the point. Do not edit ``src/mergecraft/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.mcp.commit_info import get_commit_info_tool
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.shared import ToolResult
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

_EMPTY_TOKENS = ("", "   ", "\t", "\n")


def _authorization(client: GitHubClient) -> str | None:
    return client._client.headers.get("Authorization")


def _result_text(result: ToolResult) -> str:
    return result.content[0]["text"]


def _tool_context(tmp_path: Path, github: GitHubClient) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


@pytest.mark.parametrize("token", _EMPTY_TOKENS)
async def test_github_client_omits_authorization_when_token_empty(token: str) -> None:
    """Owned-client default headers must not include ``Authorization: Bearer ``."""
    async with GitHubClient(token) as client:
        auth = _authorization(client)
        assert auth is None, (
            f"empty token must not set Authorization (got {auth!r}); "
            "httpx rejects 'Bearer ' as an illegal header value"
        )


async def test_github_client_sends_bearer_when_token_present() -> None:
    """A real token still becomes ``Authorization: Bearer <token>`` (pin)."""
    async with GitHubClient("ghp_live-token") as client:
        assert _authorization(client) == "Bearer ghp_live-token"


@pytest.mark.parametrize("token", _EMPTY_TOKENS)
async def test_get_commit_info_without_token_reports_unavailable_naming_token(
    token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Offline review: skip GitHub HTTP and name the missing token (#469)."""
    github = GitHubClient(token)
    http_calls: list[tuple[str, str]] = []

    async def _spy(method: str, url: str, **kwargs: object) -> object:
        http_calls.append((method, str(url)))
        msg = "GitHub HTTP must not run without a token"
        raise AssertionError(msg)

    monkeypatch.setattr(github._client, "request", _spy)
    try:
        ctx = _tool_context(tmp_path, github)
        result = await get_commit_info_tool(ctx).execute({"sha": "abc1234deadbeef"})
    finally:
        await github.aclose()
    text = _result_text(result)
    lowered = text.lower()

    assert result.is_error is True
    assert "token" in lowered, f"skip/error must name the missing token, got {text!r}"
    assert "illegal header" not in lowered
    assert "bearer " not in lowered
    assert http_calls == [], (
        f"no request must be built with an empty Bearer header, got {http_calls!r}"
    )


@pytest.mark.parametrize("token", _EMPTY_TOKENS)
async def test_download_artifact_zip_fail_closed_without_token(
    token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = GitHubClient(token)
    http_calls: list[tuple[str, str]] = []

    async def _spy(method: str, url: str, **kwargs: object) -> object:
        http_calls.append((method, str(url)))
        msg = "GitHub HTTP must not run without a token"
        raise AssertionError(msg)

    monkeypatch.setattr(github._client, "request", _spy)
    try:
        with pytest.raises(ValueError, match="token"):
            await github.download_artifact_zip("acme", "demo", 1)
    finally:
        await github.aclose()
    assert http_calls == []


@pytest.mark.parametrize("token", _EMPTY_TOKENS)
async def test_download_workflow_run_logs_fail_closed_without_token(
    token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = GitHubClient(token)
    http_calls: list[tuple[str, str]] = []

    async def _spy(method: str, url: str, **kwargs: object) -> object:
        http_calls.append((method, str(url)))
        msg = "GitHub HTTP must not run without a token"
        raise AssertionError(msg)

    monkeypatch.setattr(github._client, "request", _spy)
    try:
        with pytest.raises(ValueError, match="token"):
            await github.download_workflow_run_logs("acme", "demo", 1)
    finally:
        await github.aclose()
    assert http_calls == []
