"""``run_analyzers`` MCP tool (W7 integration)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import build_common_tools
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient


def _ctx(
    tmp_path: Path,
    *,
    shell: str = "restricted",
    analyzers_enabled: bool = True,
    tier: str = "trusted",
) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell=shell,  # type: ignore[arg-type]
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        analyzers_settings_enabled=analyzers_enabled,
        trust_tier=tier,  # type: ignore[arg-type]
    )


async def _run(ctx: ToolContext, **params: Any) -> dict[str, Any]:
    analyzers = __import__("mergecraft.mcp.analyzers", fromlist=["run_analyzers_tool"])
    result = await analyzers.run_analyzers_tool(ctx).execute(params)
    return json.loads(result.content[0]["text"])


async def _run_raw(ctx: ToolContext, **params: Any) -> tuple[bool, str]:
    """Return ``(is_error, text)`` without assuming the result is JSON."""
    analyzers = __import__("mergecraft.mcp.analyzers", fromlist=["run_analyzers_tool"])
    result = await analyzers.run_analyzers_tool(ctx).execute(params)
    return bool(result.is_error), str(result.content[0]["text"])


@pytest.fixture
def stub_pipeline(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the real analyzer pipeline so a rejected input cannot run anything."""
    from mergecraft.analyzers import pipeline
    from mergecraft.mcp.tool_state import AnalyzerRunState

    calls: list[dict[str, Any]] = []

    def _fake_run(**kwargs: Any) -> AnalyzerRunState:
        calls.append(kwargs)
        return AnalyzerRunState(ran=False, reason="stub pipeline")

    monkeypatch.setattr(pipeline, "run_analyzer_pipeline", _fake_run)
    return calls


@pytest.mark.asyncio
async def test_reports_not_run_when_nothing_enabled(tmp_path: Path) -> None:
    payload = await _run(_ctx(tmp_path), changed_files=[])
    assert payload["ran"] is False
    assert payload["reason"]
    assert payload["findingCount"] == 0
    if payload["analyzers"]:
        assert all(row["status"] == "unavailable" for row in payload["analyzers"])


def _ignore_analyzer_cache(_dir: str, names: list[str]) -> set[str]:
    """Copy rule shared with ``tests/analyzers/conftest.py`` — drop the cache."""
    if Path(_dir).name == ".mergecraft":
        return {"analyzer-cache"}
    return set()


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Isolated copy of the checked-in fixture repo, at ``tmp_path`` itself.

    The copy has to *be* the tool state's ``dir``, not merely live under it:
    the analyzer tool only accepts a ``repo_root`` that resolves to a
    registered checkout, and the checkout the tests register is ``tmp_path``.
    Copying there also keeps a real analyzer run (and its lock record) out of
    the tracked fixture tree.
    """
    import shutil

    from tests.analyzers.support import FIXTURE_REPO

    shutil.copytree(FIXTURE_REPO, tmp_path, ignore=_ignore_analyzer_cache, dirs_exist_ok=True)
    return tmp_path


@pytest.mark.asyncio
async def test_per_analyzer_status_returned(tmp_path: Path, fixture_repo: Path) -> None:
    payload = await _run(
        _ctx(tmp_path),
        changed_files=[".github/workflows/broken.yml"],
        repo_root=str(fixture_repo),
    )
    assert "analyzers" in payload
    assert isinstance(payload["analyzers"], list)
    if payload["ran"]:
        assert all("status" in row for row in payload["analyzers"])


# --------------------------------------------------------------------------- #
# S15 / N17 — the tool reads where the agent points. An out-of-root repo, or a
# diff path that escapes the authorized roots / is missing / is a directory /
# is not UTF-8, is one rejection class, and nothing runs.
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_out_of_root_repo_root_is_rejected(
    tmp_path: Path, stub_pipeline: list[dict[str, Any]]
) -> None:
    out_of_root = tmp_path / "not-the-checkout"
    out_of_root.mkdir()

    is_error, text = await _run_raw(_ctx(tmp_path), changed_files=[], repo_root=str(out_of_root))

    assert is_error is True, text
    assert "repo_root" in text
    assert stub_pipeline == [], "an unconfined repo_root still ran the pipeline"


@pytest.mark.asyncio
async def test_missing_diff_path_is_rejected_not_silently_ignored(
    tmp_path: Path, stub_pipeline: list[dict[str, Any]]
) -> None:
    missing = tmp_path / "no-such.diff"

    is_error, text = await _run_raw(_ctx(tmp_path), changed_files=[], diff_path=str(missing))

    assert is_error is True, text
    assert "diff_path" in text
    assert stub_pipeline == [], "a missing diff_path ran an unscoped pipeline"


@pytest.mark.asyncio
async def test_directory_diff_path_is_rejected(
    tmp_path: Path, stub_pipeline: list[dict[str, Any]]
) -> None:
    directory = tmp_path / "diff-dir"
    directory.mkdir()

    is_error, text = await _run_raw(_ctx(tmp_path), changed_files=[], diff_path=str(directory))

    assert is_error is True, text
    assert "diff_path" in text
    assert stub_pipeline == []


@pytest.mark.asyncio
async def test_diff_path_symlink_escaping_the_roots_is_rejected(
    tmp_path: Path, stub_pipeline: list[dict[str, Any]]
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.diff"
    outside.write_text("diff --git a/x b/x\n", encoding="utf-8")
    link = tmp_path / "escape.diff"
    link.symlink_to(outside)

    is_error, text = await _run_raw(_ctx(tmp_path), changed_files=[], diff_path=str(link))

    assert is_error is True, text
    assert "diff_path" in text
    assert stub_pipeline == []


@pytest.mark.asyncio
async def test_non_utf8_diff_path_is_rejected_with_a_named_reason(
    tmp_path: Path, stub_pipeline: list[dict[str, Any]]
) -> None:
    diff = tmp_path / "binary.diff"
    diff.write_bytes(b"\xff\xfe\x00diff --git a/x b/x\n")

    is_error, text = await _run_raw(_ctx(tmp_path), changed_files=[], diff_path=str(diff))

    assert is_error is True, text
    assert "diff_path" in text
    assert "utf-8" in text.casefold() or "decode" in text.casefold()
    assert stub_pipeline == []


@pytest.mark.asyncio
async def test_diff_path_under_tmpdir_is_accepted(
    tmp_path: Path, stub_pipeline: list[dict[str, Any]]
) -> None:
    diff = tmp_path / "scratch.diff"
    diff.write_text("diff --git a/x b/x\n", encoding="utf-8")

    is_error, text = await _run_raw(_ctx(tmp_path), changed_files=[], diff_path=str(diff))

    assert is_error is False, text
    assert stub_pipeline, "an accepted diff_path must reach the pipeline"
    assert json.loads(text)["ran"] is False


# --------------------------------------------------------------------------- #
# T8 — the MCP analyzer test must not provision into, or write a lock under,
# the checked-in fixture tree.
# --------------------------------------------------------------------------- #


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.asyncio
async def test_analyzer_run_leaves_the_tracked_fixture_tree_unchanged(
    tmp_path: Path, fixture_repo: Path
) -> None:
    """A run against the fixture must reproduce its tree byte for byte."""
    from tests.analyzers.support import FIXTURE_REPO

    before = _snapshot_tree(FIXTURE_REPO)

    await _run(
        _ctx(tmp_path),
        changed_files=[".github/workflows/broken.yml"],
        repo_root=str(fixture_repo),
    )

    after = _snapshot_tree(FIXTURE_REPO)
    assert after == before, "the analyzer run mutated the tracked fixture tree"


def test_tool_withheld_when_trust_tier_forbids(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, shell="disabled", analyzers_enabled=False)
    names = {t.name for t in build_common_tools(ctx)}
    assert "run_analyzers" not in names


def test_tool_withheld_on_untrusted_tier_when_disabled(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, tier="untrusted", analyzers_enabled=False)
    names = {t.name for t in build_common_tools(ctx)}
    assert "run_analyzers" not in names
