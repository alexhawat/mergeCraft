"""#469 — ``upload_file`` must not send ``Authorization: Bearer `` for an empty token.

Locked D4 (open-issues-sweep-2026-08-24-a): audit ``mcp/upload.py`` the same way as
``utils/github.py``. When ``MERGECRAFT_API_URL`` is set but ``api_token`` is empty
or whitespace, do not interpolate ``Bearer {token}``. Prefer a skip/error that
names the missing token over httpx ``Illegal header value b'Bearer '``.

These assertions fail until the AC implementation wave. Do not xfail: RED is
the point. Do not edit ``src/mergecraft/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.shared import ToolResult
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.mcp.upload import upload_file_tool
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

_EMPTY_TOKENS = ("", "   ", "\t")
_API_URL = "https://api.mergecraft.example/v1"


def _result_text(result: ToolResult) -> str:
    return result.content[0]["text"]


def _authorization(headers: dict[str, str]) -> str | None:
    for key, value in headers.items():
        if key.lower() == "authorization":
            return value
    return None


def _assert_no_empty_bearer(captured: list[dict[str, str]]) -> None:
    for headers in captured:
        auth = _authorization(headers)
        if auth is None:
            continue
        credential = auth.removeprefix("Bearer ").removeprefix("bearer ")
        assert credential.strip(), (
            f"must not send Authorization with an empty Bearer credential (got {auth!r})"
        )


def _ctx(
    repo_root: Path,
    scratch: Path,
    *,
    api_token: str,
) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token=api_token,
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(repo_root)),
        mcp_server_url="",
        tmpdir=str(scratch),
    )


def _install_post_recorder(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    captured: list[dict[str, str]] = []

    class _RecordingAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        async def __aenter__(self) -> _RecordingAsyncClient:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

        async def post(
            self,
            url: str,
            *,
            headers: dict[str, str] | None = None,
            json: Any = None,
        ) -> Any:
            captured.append(dict(headers or {}))
            msg = "signed-url POST must not run with an empty Bearer token"
            raise AssertionError(msg)

    monkeypatch.setattr("mergecraft.mcp.upload.httpx.AsyncClient", _RecordingAsyncClient)
    return captured


@pytest.mark.parametrize("api_token", _EMPTY_TOKENS)
async def test_upload_does_not_send_empty_bearer_when_api_url_set(
    api_token: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Remote upload path must not build ``Authorization: Bearer `` (#469 / D4)."""
    repo_root = tmp_path / "repo"
    scratch = tmp_path / "scratch"
    repo_root.mkdir()
    scratch.mkdir()
    source = repo_root / "report.txt"
    source.write_text("evidence\n", encoding="utf-8")

    monkeypatch.setenv("MERGECRAFT_API_URL", _API_URL)
    captured = _install_post_recorder(monkeypatch)
    ctx = _ctx(repo_root, scratch, api_token=api_token)
    result = await upload_file_tool(ctx).execute({"path": str(source)})
    text = _result_text(result)

    _assert_no_empty_bearer(captured)
    assert "illegal header" not in text.lower()
    assert "bearer " not in text.lower()
    if result.is_error:
        assert "token" in text.lower(), f"error must name the missing token, got {text!r}"
    else:
        assert captured == [], f"empty token must not POST to the upload API, got {captured!r}"


async def test_upload_whitespace_token_does_not_interpolate_bearer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace ``api_token`` is empty: do not interpolate ``Bearer {{token}}``."""
    repo_root = tmp_path / "repo"
    scratch = tmp_path / "scratch"
    repo_root.mkdir()
    scratch.mkdir()
    source = repo_root / "report.txt"
    source.write_text("evidence\n", encoding="utf-8")

    monkeypatch.setenv("MERGECRAFT_API_URL", _API_URL)
    captured = _install_post_recorder(monkeypatch)
    ctx = _ctx(repo_root, scratch, api_token=" ")
    result = await upload_file_tool(ctx).execute({"path": str(source)})

    _assert_no_empty_bearer(captured)
    if captured:
        auths = [_authorization(h) for h in captured]
        msg = f"whitespace token must not produce Bearer headers, got {auths!r}"
        raise AssertionError(msg)
    text = _result_text(result).lower()
    assert "illegal header" not in text
    if result.is_error:
        assert "token" in text
