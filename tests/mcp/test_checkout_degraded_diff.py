"""P10 / TB-D5-D6 — the checkout records what it actually produced (TB1).

Wave plan: ``.ignorelocal/waves/40-trust-boundaries-wave-plan.md`` (TB1).

When the ``git diff`` after a successful checkout fails, the fallback is a
files-API diff. Today it registers as a ``checkout`` diff with no warning and no
record; the plan requires:

* **TB-D5** — register ``provenance="api"`` with an explicit
  ``review_scope="files-api-diff"`` (not api-only — head files are readable),
  emit a warning, and record a ``degraded`` reason naming the git-diff failure.
* **TB-D6** — a file with no ``patch`` but non-zero line changes is
  unreviewable (``unreviewablePaths`` + ``degraded``); a file with no ``patch``
  and no line changes is a binary/empty header, as today; the page-cap exit is
  recorded as a truncation.

RED markers were reconciled after TB3 landed; every case here is a real pass.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.mcp.checkout import checkout_pr_tool
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _pr_repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "base")
    _git(work, "branch", "-M", "base")
    _git(work, "checkout", "-b", "feature")
    (work / "feature.py").write_text("changed = 1\n", encoding="utf-8")
    _git(work, "add", "feature.py")
    _git(work, "commit", "-m", "feature")
    _git(work, "clone", "--bare", str(work), str(origin))
    _git(work, "push", str(origin), "feature:refs/pull/1/head")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    return clone


class _StubGitHub(GitHubClient):
    """Serves one same-repo PR plus a scripted files-API page map."""

    def __init__(self, *, pages: dict[int, list[dict[str, Any]]] | None = None) -> None:
        super().__init__(token="test-token")
        self._pages = pages or {}

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        repo_ref = {"full_name": f"{owner}/{repo}", "fork": False}
        return {
            "number": pull_number,
            "head": {"ref": "feature", "sha": "a" * 40, "repo": repo_ref},
            "base": {"ref": "base", "sha": "b" * 40, "repo": repo_ref},
            "title": "A pull request",
            "html_url": f"https://example.test/pull/{pull_number}",
        }

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return []

    async def get(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/files"):
            params = kwargs.get("params") or {}
            page = int(params.get("page", 1))
            return list(self._pages.get(page, []))
        return {}


def _ctx_for(repo: Path, github: GitHubClient, tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(repo))
    state.selected_mode = "Review"
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_synchronize")),
        github=github,
        tool_state=state,
        modes=compute_modes("claude"),
        tmpdir=str(tmp_path / "artifacts"),
    )


def _fail_merge_base_diff(monkeypatch: MonkeyPatch) -> None:
    """Make only the post-checkout ``git diff --merge-base`` call fail."""
    from mergecraft.mcp import checkout as checkout_module

    real = checkout_module._run_git

    def _maybe_fail(args: list[str], **kwargs: Any) -> str:
        if args[:2] == ["diff", "--merge-base"]:
            msg = "fatal: bad revision 'origin/base'"
            raise RuntimeError(msg)
        return real(args, **kwargs)

    monkeypatch.setattr(checkout_module, "_run_git", _maybe_fail)


async def _checkout(ctx: ToolContext) -> tuple[bool, dict[str, Any] | str]:
    result = await checkout_pr_tool(ctx).execute({"pull_number": 1})
    if result.is_error:
        return True, str(result.content[0]["text"])
    return False, json.loads(result.content[0]["text"])


@pytest.mark.asyncio
async def test_git_diff_failure_is_labelled_a_files_api_diff(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """TB-D5 — a files-API fallback registers as ``files-api-diff``, not checkout."""
    from mergecraft.mcp import checkout as checkout_module

    repo = _pr_repo(tmp_path)
    files = {
        1: [
            {
                "filename": "feature.py",
                "additions": 1,
                "deletions": 0,
                "patch": "@@ -0,0 +1 @@\n+changed = 1\n",
            }
        ]
    }
    warnings: list[str] = []
    monkeypatch.setattr(checkout_module, "warning", warnings.append)
    _fail_merge_base_diff(monkeypatch)
    ctx = _ctx_for(repo, _StubGitHub(pages=files), tmp_path)

    is_error, payload = await _checkout(ctx)

    assert is_error is False, payload
    assert isinstance(payload, dict)
    assert ctx.tool_state.scope_provenance == "api"
    assert ctx.tool_state.review_scope == "files-api-diff"
    assert "degraded" in payload
    assert "diff" in str(payload["degraded"]).lower()
    assert warnings, "a degraded diff must emit a warning"


@pytest.mark.asyncio
async def test_missing_text_patch_is_recorded_as_unreviewable(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """TB-D6 — no patch but non-zero line changes is a text diff too large to inline."""
    repo = _pr_repo(tmp_path)
    files = {
        1: [
            {
                "filename": "huge.py",
                "additions": 500,
                "deletions": 3,
                "patch": None,
            }
        ]
    }
    _fail_merge_base_diff(monkeypatch)
    ctx = _ctx_for(repo, _StubGitHub(pages=files), tmp_path)

    is_error, payload = await _checkout(ctx)

    assert is_error is False, payload
    assert isinstance(payload, dict)
    assert "huge.py" in payload.get("unreviewablePaths", [])
    assert "degraded" in payload


@pytest.mark.asyncio
async def test_zero_line_missing_patch_is_not_unreviewable(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """TB-D6 — no patch and no line changes is a binary/empty header, as today.

    Guard: this already holds (no file is flagged today), and TB3 must not
    start flagging binaries.
    """
    repo = _pr_repo(tmp_path)
    files = {
        1: [
            {
                "filename": "logo.png",
                "additions": 0,
                "deletions": 0,
                "patch": None,
            }
        ]
    }
    _fail_merge_base_diff(monkeypatch)
    ctx = _ctx_for(repo, _StubGitHub(pages=files), tmp_path)

    is_error, payload = await _checkout(ctx)

    assert is_error is False, payload
    assert isinstance(payload, dict)
    assert "logo.png" not in payload.get("unreviewablePaths", [])


@pytest.mark.asyncio
async def test_page_cap_records_a_truncation(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """TB-D6 — hitting the page cap is recorded, not only logged."""
    from mergecraft.mcp import checkout as checkout_module

    monkeypatch.setattr(checkout_module, "_PULL_FILES_MAX_PAGES", 2)
    full_page = [
        {"filename": f"f{i}.py", "additions": 1, "deletions": 0, "patch": "@@ -0,0 +1 @@\n+x\n"}
        for i in range(100)
    ]
    repo = _pr_repo(tmp_path)
    _fail_merge_base_diff(monkeypatch)
    ctx = _ctx_for(repo, _StubGitHub(pages={1: full_page, 2: full_page}), tmp_path)

    is_error, payload = await _checkout(ctx)

    assert is_error is False, payload
    assert isinstance(payload, dict)
    assert "truncat" in str(payload.get("degraded", "")).lower()
