"""Files-API rename metadata must describe the same paths as a Git diff."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mergecraft.analyzers.scope import parse_diff_scope
from mergecraft.mcp.checkout import _diff_from_pull_files, pull_request_path_expectations
from mergecraft.utils.diff_paths import changed_paths_from_diff


@pytest.mark.parametrize("patch", [None, "@@ -1 +1 @@\n-old\n+new"])
@pytest.mark.parametrize(
    ("previous", "filename"),
    [
        ("docs/plan b/x.md", "docs/plan b/y.md"),
        ('docs/old"name.md', 'docs/new"name.md'),
        ("docs/old\tname.md", "docs/new\tname.md"),
        ("docs/old\nname.md", "docs/new\nname.md"),
        ("docs/old\\name.md", "docs/new\\name.md"),
        ("docs/café.md", "docs/après.md"),
        (" old.md ", " new.md "),
    ],
)
async def test_files_api_rename_roundtrips_scope(
    previous: str, filename: str, patch: str | None
) -> None:
    ctx = SimpleNamespace(
        repo=SimpleNamespace(owner="acme", name="demo"),
        scm=SimpleNamespace(
            get=AsyncMock(
                return_value=[
                    {
                        "filename": filename,
                        "previous_filename": previous,
                        "status": "renamed",
                        "patch": patch,
                        "additions": int(patch is not None),
                        "deletions": int(patch is not None),
                    }
                ]
            )
        ),
    )
    required, allowed = await pull_request_path_expectations(ctx, pull_number=42)
    assert required == {filename}
    assert allowed == {previous, filename}
    diff = await _diff_from_pull_files(ctx, pull_number=42)
    assert set(changed_paths_from_diff(diff)) == {previous, filename}
    assert "rename from " in diff
    assert "rename to " in diff
    if patch:
        assert parse_diff_scope(diff).hunk_ranges == {filename: [(1, 1)]}
    assert not diff.unreviewable_paths
    assert not diff.truncated
