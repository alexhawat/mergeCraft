"""The ``describe`` summary carries no internal guidance filler (#1340 review)."""

from __future__ import annotations

from mergecraft.pr import build_describe_output

_DIFF = (
    "diff --git a/feature.py b/feature.py\n"
    "new file mode 100644\n"
    "--- /dev/null\n"
    "+++ b/feature.py\n"
    "@@ -0,0 +1,2 @@\n"
    "+def feature():\n"
    "+    return 2\n"
)


def test_summary_has_no_guidance_length_filler() -> None:
    """The summary names the change, not the size of an internal prompt."""
    described = build_describe_output(diff=_DIFF, pr_metadata={"title": "repo"})

    assert "summarizes 1 changed file" in described.body
    assert "chars of guidance" not in described.body
    assert "summary discipline" not in described.body
