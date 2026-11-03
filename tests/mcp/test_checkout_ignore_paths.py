"""``checkout_pr`` keeps files ignored by config out of the reviewer's diff (#1109).

The diff on disk is what the reviewer reads and what the changed-line coverage gate
accounts against, so an ignored file must be absent from both: it is out of scope, not
unread. The tool result names the ignored files and the review body lists them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_checkout_coverage import _mark_read, _patched_file
from tests.mcp.test_checkout_degraded_diff import (
    _checkout,
    _ctx_for,
    _fail_merge_base_diff,
    _git,
    _StubGitHub,
)

from mergecraft.config.settings import ReviewSettings
from mergecraft.review_policy.ignore_paths import build_review_ignore

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def _mixed_pr_repo(tmp_path: Path) -> Path:
    """A PR that changes source, a changelog, a lockfile and eval data."""
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
    (work / "CHANGELOG.md").write_text("# Changelog\n- CHANGELOG_SECRET\n", encoding="utf-8")
    (work / "uv.lock").write_text("LOCK_CONTENT = 1\n", encoding="utf-8")
    evals = work / "host" / "evals" / "suite"
    evals.mkdir(parents=True)
    (evals / "case.jsonl").write_text('{"EVAL_PAYLOAD": 1}\n', encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-m", "feature")
    _git(work, "clone", "--bare", str(work), str(origin))
    _git(work, "push", str(origin), "feature:refs/pull/1/head")
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    return clone


def _read_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _ignore(input_value: str | None = "host/evals/**/*.jsonl\nCHANGELOG.md") -> Any:
    return build_review_ignore(input_value=input_value, review=ReviewSettings(), source="test")


@pytest.mark.asyncio
async def test_ignored_files_never_reach_the_reviewer_diff(tmp_path: Path) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    repo = _mixed_pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(), tmp_path)
    ctx.tool_state.review_ignore = _ignore()

    is_error, payload = await _checkout(ctx)

    assert is_error is False
    assert isinstance(payload, dict)
    diff_text = _read_text(payload["diffPath"])
    assert "feature.py" in diff_text
    for leaked in ("CHANGELOG_SECRET", "LOCK_CONTENT", "EVAL_PAYLOAD"):
        assert leaked not in diff_text
    assert sorted(payload["ignoredPaths"]) == [
        "CHANGELOG.md",
        "host/evals/suite/case.jsonl",
        "uv.lock",
    ]
    assert "not reviewed (ignored by config)" in payload["ignoredPathsNote"]
    assert sorted(ctx.tool_state.ignored_review_paths) == sorted(payload["ignoredPaths"])

    authoritative = ctx.tool_state.coverage.authoritative_diff or ""
    assert "CHANGELOG_SECRET" not in authoritative
    _mark_read(ctx, "feature.py")
    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert section.complete is True, "ignored files are out of scope, not unread"
    assert {row.path for row in section.uncovered}.isdisjoint(set(payload["ignoredPaths"]))


@pytest.mark.asyncio
async def test_without_a_matcher_the_diff_is_unchanged(tmp_path: Path) -> None:
    repo = _mixed_pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(), tmp_path)

    _is_error, payload = await _checkout(ctx)

    assert isinstance(payload, dict)
    diff_text = _read_text(payload["diffPath"])
    assert "CHANGELOG_SECRET" in diff_text
    assert "ignoredPaths" not in payload
    assert ctx.tool_state.ignored_review_paths == []


@pytest.mark.asyncio
async def test_files_api_diff_drops_ignored_and_unreviewable_ignored_files(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    repo = _mixed_pr_repo(tmp_path)
    files = {
        1: [
            _patched_file("feature.py"),
            _patched_file("CHANGELOG.md"),
            # A huge eval file GitHub sends no patch for: ignored, so not "unreviewable".
            {
                "filename": "host/evals/suite/big.jsonl",
                "additions": 9000,
                "deletions": 0,
                "patch": None,
            },
        ]
    }
    _fail_merge_base_diff(monkeypatch)
    ctx = _ctx_for(repo, _StubGitHub(pages=files), tmp_path)
    ctx.tool_state.review_ignore = _ignore()

    is_error, payload = await _checkout(ctx)

    assert is_error is False
    assert isinstance(payload, dict)
    assert "unreviewablePaths" not in payload
    assert payload["ignoredPaths"] == ["CHANGELOG.md", "host/evals/suite/big.jsonl"]
    assert ctx.tool_state.coverage.unreviewable_paths == []
    diff_text = _read_text(payload["diffPath"])
    assert "CHANGELOG.md" not in diff_text
    _mark_read(ctx, "feature.py")
    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert section.complete is True


def test_coverage_treats_ignored_hunks_as_out_of_scope_for_any_scope_source() -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state
    from mergecraft.mcp.tool_state import init_tool_state

    state = init_tool_state(owner="acme", name="demo", dir=".")
    state.coverage.authoritative_diff = (
        "diff --git a/CHANGELOG.md b/CHANGELOG.md\n"
        "--- a/CHANGELOG.md\n"
        "+++ b/CHANGELOG.md\n"
        "@@ -0,0 +1 @@\n"
        "+x\n"
    )
    state.coverage.unreviewable_paths = ["uv.lock"]
    without = coverage_section_for_state(state)
    assert without is not None
    assert without.complete is False

    state.review_ignore = _ignore(None)
    assert coverage_section_for_state(state) is None, "nothing left in scope to account for"
