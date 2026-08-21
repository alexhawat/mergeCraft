"""Batch CA / #350 — review-only production boundary.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20c-wave-plan.md``
(W2.2 recon). Production registry is Review / IncrementalReview / Plan only.
Write-capable modules stay importable (D12). A reviewer-shaped run cannot
edit a tracked file, ``git commit``, ``git push``, or open a code-changing PR.
Out of scope (#350): MCP transport auth (#345/#346) and trust/privilege drop.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mergecraft.config.settings import ModeDefinition
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.git import commit_changes_tool, git_tool, push_branch_tool
from mergecraft.mcp.pr import create_pull_request_tool
from mergecraft.mcp.select_mode import select_mode_tool
from mergecraft.mcp.shell import shell_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import (
    _MODE_DEFS,
    _custom_modes,
    compute_modes,
    modes,
)
from mergecraft.utils.github import GitHubClient

# Write-capable built-ins still registered on pre-0.0.1 @ a2e3944d (#350 / D12).
WRITE_CAPABLE_MODE_NAMES: tuple[str, ...] = (
    "Build",
    "AddressReviews",
    "Fix",
    "ResolveConflicts",
    "Task",
)
REVIEW_ONLY_MODE_NAMES: tuple[str, ...] = (
    "Review",
    "IncrementalReview",
    "Plan",
)
_REVIEWER_SHAPED: tuple[str, ...] = ("Review", "IncrementalReview")


def _registry_names() -> list[str]:
    return [name for name, _, _ in _MODE_DEFS]


def _computed_names() -> list[str]:
    return [mode.name for mode in compute_modes("opencode")]


def _init_repo(root: Path) -> Path:
    tracked = root / "tracked.txt"
    tracked.write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "ca@test.local"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "CA Tests"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tracked


def _ctx(tmp_path: Path, *, selected_mode: str | None = None) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    if selected_mode is not None:
        state.selected_mode = selected_mode
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell="restricted",
            push="enabled",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=list(compute_modes("claude")),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        signed_commits=True,
    )


def _tool_text(result: object) -> str:
    content = getattr(result, "content", None)
    if not content:
        return ""
    first = content[0]
    if isinstance(first, dict):
        return str(first.get("text", ""))
    return str(first)


class _GitRecorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
        del cwd, env
        self.calls.append([str(part) for part in args])
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return "feature\n"
        if args[:2] == ["rev-parse", "HEAD"]:
            return "abc123\n"
        if args[:1] == ["status"]:
            return " M tracked.txt\n"
        return "ok\n"


class _RecordingScm:
    def __init__(self) -> None:
        self.posts: list[str] = []

    async def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        self.posts.append(path)
        return {
            "id": 1,
            "number": 99,
            "html_url": "https://example.test/acme/demo/pull/99",
            "title": kwargs.get("json", {}).get("title", "x"),
            "head": {"ref": "feature"},
            "base": {"ref": "main"},
        }


# ── D12: unregistered write-mode modules stay importable ───────────────────────


def test_write_mode_modules_remain_importable_as_negative_fixtures() -> None:
    """D12: ``modes/Fix.py`` (and siblings) stay importable even after un-registering."""
    from mergecraft.modes import AddressReviews, Build, Fix, ResolveConflicts, Task

    assert Fix.NAME == "Fix"
    assert Build.NAME == "Build"
    assert Task.NAME == "Task"
    assert AddressReviews.NAME == "AddressReviews"
    assert ResolveConflicts.NAME == "ResolveConflicts"


# ── W2 production registry ─────────────────────────────────────────────────────


def test_production_registry_excludes_write_capable_modes() -> None:
    """After W2, ``_MODE_DEFS`` is review-only (D12)."""
    names = set(_registry_names())
    leaked = names.intersection(WRITE_CAPABLE_MODE_NAMES)
    assert not leaked, f"write-capable modes still registered: {sorted(leaked)}"
    for mode_name in REVIEW_ONLY_MODE_NAMES:
        assert mode_name in names, mode_name


def test_compute_modes_excludes_write_capable_modes() -> None:
    """After W2, ``compute_modes`` must not return write-capable names."""
    names = set(_computed_names())
    leaked = names.intersection(WRITE_CAPABLE_MODE_NAMES)
    assert not leaked, f"compute_modes still lists write modes: {sorted(leaked)}"


def test_static_modes_export_excludes_write_capable_modes() -> None:
    """After W2, the static ``modes`` export matches the production registry."""
    names = {mode.name for mode in modes}
    leaked = names.intersection(WRITE_CAPABLE_MODE_NAMES)
    assert not leaked, f"static modes still lists write modes: {sorted(leaked)}"


@pytest.mark.parametrize("mode_name", WRITE_CAPABLE_MODE_NAMES)
async def test_select_mode_rejects_write_capable_names(tmp_path: Path, mode_name: str) -> None:
    """After W2, ``select_mode`` cannot resolve a write-capable built-in."""
    result = await select_mode_tool(_ctx(tmp_path)).execute({"mode": mode_name})
    payload = json.loads(_tool_text(result))
    assert "error" in payload, payload
    assert "not found" in str(payload["error"]).lower()
    available = {entry["name"] for entry in payload.get("availableModes", [])}
    assert mode_name not in available


async def test_custom_config_cannot_reenable_write_capable_fix(tmp_path: Path) -> None:
    """D12: a ``.mergecraft/config.yaml`` custom mode must not re-enable writes."""
    custom = _custom_modes(
        [
            ModeDefinition(
                id="fix",
                name="Fix",
                description="re-enable writes via config",
                prompt='git add . && git commit -m "fix" && git push',
            ),
        ]
    )
    ctx = _ctx(tmp_path)
    ctx.modes = [*compute_modes("claude"), *custom]
    result = await select_mode_tool(ctx).execute({"mode": "Fix"})
    payload = json.loads(_tool_text(result))
    assert "error" in payload, payload
    assert "not found" in str(payload["error"]).lower()


# ── Reviewer-shaped negatives ──────────────────────────────────────────────────


@pytest.mark.parametrize("selected_mode", _REVIEWER_SHAPED)
async def test_reviewer_shaped_run_cannot_edit_tracked_file(
    tmp_path: Path, selected_mode: str
) -> None:
    """A Review / IncrementalReview run must not mutate a tracked file."""
    tracked = _init_repo(tmp_path)
    before = tracked.read_text(encoding="utf-8")
    ctx = _ctx(tmp_path, selected_mode=selected_mode)
    result = await shell_tool(ctx).execute(
        {
            "command": "printf mutated >> tracked.txt",
            "description": "attempt to edit a tracked file",
        }
    )
    assert result.is_error is True, _tool_text(result)
    assert "review-only" in _tool_text(result).lower()
    assert tracked.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("selected_mode", _REVIEWER_SHAPED)
async def test_reviewer_shaped_run_cannot_git_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selected_mode: str
) -> None:
    """``commit_changes`` must refuse a reviewer-shaped run and not invoke git."""
    recorder = _GitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)
    ctx = _ctx(tmp_path, selected_mode=selected_mode)
    result = await commit_changes_tool(ctx).execute({"message": "chore: must not land"})
    assert result.is_error is True, _tool_text(result)
    text = _tool_text(result).lower()
    assert "review-only" in text
    assert "commit" in text
    assert not any("commit" in call for call in recorder.calls), recorder.calls


@pytest.mark.parametrize("selected_mode", _REVIEWER_SHAPED)
async def test_reviewer_shaped_run_cannot_git_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selected_mode: str
) -> None:
    """``push_branch`` must refuse a reviewer-shaped run and not invoke git push."""
    recorder = _GitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)
    ctx = _ctx(tmp_path, selected_mode=selected_mode)
    result = await push_branch_tool(ctx).execute({"branchName": "feature"})
    assert result.is_error is True, _tool_text(result)
    text = _tool_text(result).lower()
    assert "review-only" in text
    assert "push" in text
    assert not any("push" in call for call in recorder.calls), recorder.calls


@pytest.mark.parametrize("selected_mode", _REVIEWER_SHAPED)
async def test_reviewer_shaped_run_cannot_open_code_changing_pr(
    tmp_path: Path, selected_mode: str
) -> None:
    """``create_pull_request`` must refuse a reviewer-shaped run (code-changing PR)."""
    scm = _RecordingScm()
    ctx = _ctx(tmp_path, selected_mode=selected_mode)
    ctx.scm = scm
    result = await create_pull_request_tool(ctx).execute(
        {"title": "apply the fix", "body": "code change", "base": "main"}
    )
    assert result.is_error is True, _tool_text(result)
    text = _tool_text(result).lower()
    assert "review-only" in text
    assert scm.posts == []


# ── Already-true supporting pin (git MCP never forwards ``commit``) ───────────


async def test_git_mcp_tool_does_not_forward_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``git`` MCP tool already refuses ``commit``; must not reopen it."""
    recorder = _GitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)
    result = await git_tool(_ctx(tmp_path, selected_mode="Review")).execute(
        {"command": "commit", "args": ["-m", "nope"]}
    )
    assert result.is_error is True, _tool_text(result)
    assert recorder.calls == []
