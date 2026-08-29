"""Plan 13 W1.2 — git tool ergonomics RED contracts (green after W3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.mcp.reviewer_resilience_support import git_ctx, init_git_repo, tool_error_text

from mergecraft.mcp.checkout import checkout_pr_tool
from mergecraft.mcp.git import git_tool


class _RunGitRecorder:
    def __init__(self, output: str = "ok\n") -> None:
        self.calls: list[list[str]] = []
        self.output = output

    def __call__(self, args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
        self.calls.append([str(a) for a in args])
        return self.output


@pytest.mark.parametrize("subcommand", ["show-ref", "for-each-ref", "ls-remote"])
@pytest.mark.xfail(reason="green after W3: allow missing read-only verbs", strict=False)
@pytest.mark.asyncio
async def test_readonly_discovery_verbs_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subcommand: str
) -> None:
    init_git_repo(tmp_path)
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(git_ctx(tmp_path)).execute({"command": subcommand})
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [[subcommand]]


@pytest.mark.xfail(reason="green after W3: config --get remote.origin.url", strict=False)
@pytest.mark.asyncio
async def test_config_get_remote_origin_url_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_git_repo(tmp_path)
    recorder = _RunGitRecorder(output="https://github.com/acme/demo.git\n")
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(git_ctx(tmp_path)).execute(
        {"command": "config", "args": ["--get", "remote.origin.url"]}
    )
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [["config", "--get", "remote.origin.url"]]


@pytest.mark.parametrize(
    "key",
    [
        "http.https://github.com/.extraHeader",
        "credential.helper",
        "url.https://github.com/.insteadOf",
    ],
)
@pytest.mark.xfail(reason="green after W3: refuse credential config keys", strict=False)
@pytest.mark.asyncio
async def test_config_get_credential_keys_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    init_git_repo(tmp_path)
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(git_ctx(tmp_path)).execute(
        {"command": "config", "args": ["--get", key]}
    )
    assert result.is_error is True, result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.parametrize(
    "args",
    [
        ["--unset", "user.email"],
        ["user.email", "evil@example.com"],
    ],
)
@pytest.mark.xfail(reason="green after W3: config writes remain refused", strict=False)
@pytest.mark.asyncio
async def test_config_write_forms_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    init_git_repo(tmp_path)
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(git_ctx(tmp_path)).execute({"command": "config", "args": args})
    assert result.is_error is True, result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.parametrize("alias_key", ["pr_number", "issue_number"])
@pytest.mark.xfail(reason="green after W3: checkout_pr parameter aliases", strict=False)
@pytest.mark.asyncio
async def test_checkout_pr_parameter_aliases_resolve_to_pull_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias_key: str
) -> None:
    monkeypatch.setattr("mergecraft.mcp.checkout.get_git_status", lambda cwd: "")
    monkeypatch.setattr(
        "mergecraft.mcp.checkout._run_git",
        lambda *args, **kwargs: "deadbeef\n" if args[0] == ["rev-parse", "HEAD"] else "ok\n",
    )

    async def _pull(_owner: str, _repo: str, pull_number: int) -> dict[str, object]:
        return {
            "head": {"ref": "feature", "sha": "a" * 40, "repo": {"full_name": "acme/demo"}},
            "base": {"ref": "main", "repo": {"full_name": "acme/demo"}},
            "title": "t",
            "html_url": "https://x/1",
        }

    monkeypatch.setattr("mergecraft.mcp.checkout.GitHubClient.get_pull", _pull, raising=False)

    result = await checkout_pr_tool(git_ctx(tmp_path)).execute({alias_key: 546})
    assert result.is_error is False, result.content[0]["text"]
    payload = json.loads(result.content[0]["text"])
    assert payload.get("pullNumber") == 546 or payload.get("pull_number") == 546


@pytest.mark.asyncio
async def test_unknown_checkout_alias_produces_schema_error(tmp_path: Path) -> None:
    spec = checkout_pr_tool(git_ctx(tmp_path))
    result = await spec.execute({"pullNumber": 1})
    assert result.is_error is True
    text = tool_error_text(result)
    assert "additionalProperties" in text or "pull_number" in text
