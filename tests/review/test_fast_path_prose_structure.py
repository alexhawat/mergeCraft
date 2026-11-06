"""Deleted YAML front matter remains executable configuration through the API gate."""

from __future__ import annotations

import pytest

from tests.classify.test_whitespace_proof import patch
from tests.review.test_fast_path_gate import FakeScm, _decide, _files_from_diff


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("---\nlayout: admin\n---\nBody.\n", "Body.\n", "full"),
        ("---\nlayout: admin\n...\nBody.\n", "Body.\n", "full"),
        ("Body.\n", "---\nlayout: admin\n---\nBody.\n", "full"),
        ("---\nlayout: admin\n---\nOld body.\n", "---\nlayout: admin\n---\nNew body.\n", "skip"),
    ],
)
async def test_api_gate_uses_both_markdown_structures(
    before: str, after: str, expected: str
) -> None:
    scm = FakeScm(
        files=_files_from_diff(patch("page.md", before, after)), contents={"page.md": after}
    )
    decision = await _decide(scm)
    assert decision.tier == expected
    assert decision.recognizer == ("prose" if expected == "skip" else None)
