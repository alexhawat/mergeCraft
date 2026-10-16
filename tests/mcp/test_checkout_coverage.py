"""``checkout_pr`` records what it delivered, so coverage can be accounted for at the end.

The checkout is the one place that knows which hunks the reviewer's diff holds and which
it could not hold: files GitHub sent line counts for but no ``patch``, and files beyond
the files-API page cap. Both used to reach the agent only as ``unreviewablePaths`` /
``diffTruncated`` on the tool result and were read by nothing else. They are now recorded
on the run state and surface in the packet's ``coverage`` section.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_checkout_degraded_diff import (
    _checkout,
    _ctx_for,
    _fail_merge_base_diff,
    _pr_repo,
    _StubGitHub,
)

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _patched_file(name: str) -> dict[str, Any]:
    return {
        "filename": name,
        "additions": 1,
        "deletions": 0,
        "patch": "@@ -0,0 +1 @@\n+x\n",
    }


@pytest.mark.asyncio
async def test_a_files_api_diff_over_the_page_cap_is_recorded_as_truncated(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    from mergecraft.mcp import checkout as checkout_module

    monkeypatch.setattr(checkout_module, "_PULL_FILES_MAX_PAGES", 2)
    full_page = [_patched_file(f"f{i}.py") for i in range(100)]
    repo = _pr_repo(tmp_path)
    _fail_merge_base_diff(monkeypatch)
    ctx = _ctx_for(repo, _StubGitHub(pages={1: full_page, 2: full_page}), tmp_path)

    is_error, _payload = await _checkout(ctx)

    assert is_error is False
    assert ctx.tool_state.coverage.diff_truncated is True
    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert section.complete is False
    assert [row.cause for row in section.uncovered] == ["diff_truncated"]


@pytest.mark.asyncio
async def test_a_file_with_line_changes_and_no_patch_is_recorded_as_unreviewable(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    repo = _pr_repo(tmp_path)
    files = {
        1: [
            _patched_file("small.py"),
            {"filename": "huge.py", "additions": 500, "deletions": 3, "patch": None},
        ]
    }
    _fail_merge_base_diff(monkeypatch)
    ctx = _ctx_for(repo, _StubGitHub(pages=files), tmp_path)

    is_error, _payload = await _checkout(ctx)

    assert is_error is False
    assert ctx.tool_state.coverage.unreviewable_paths == ["huge.py"]
    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert [(r.path, r.cause) for r in section.uncovered] == [("huge.py", "no_inline_patch")]
    assert section.hunks_covered == 1


@pytest.mark.asyncio
async def test_a_binary_header_with_no_line_changes_is_not_an_uncovered_hunk(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    repo = _pr_repo(tmp_path)
    files = {
        1: [
            _patched_file("small.py"),
            {"filename": "logo.png", "additions": 0, "deletions": 0, "patch": None},
        ]
    }
    _fail_merge_base_diff(monkeypatch)
    ctx = _ctx_for(repo, _StubGitHub(pages=files), tmp_path)

    await _checkout(ctx)

    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert section.complete is True


@pytest.mark.asyncio
async def test_a_clean_local_checkout_diff_is_fully_covered(tmp_path: Path) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    repo = _pr_repo(tmp_path)
    ctx = _ctx_for(repo, _StubGitHub(), tmp_path)

    is_error, _payload = await _checkout(ctx)

    assert is_error is False
    assert ctx.tool_state.coverage.authoritative_diff
    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert section.complete is True
    assert section.hunks_total >= 1
    assert section.hunks_covered == section.hunks_total
