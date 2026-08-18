"""DG2 hierarchical summarization — large-PR context engine (G6).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG2).
Implementation: **DG2.2** — map → summaries → hunks with raw tokens reserved for
high-risk regions; reduced scope is always reported (file 2 D12).
"""

from __future__ import annotations

import pytest

from mergecraft.utils.run_bounds import ScopeReduction


def _synthetic_diff(*, files: int, lines_per_file: int) -> str:
    chunks: list[str] = []
    for index in range(files):
        path = f"src/module_{index:04d}.py"
        body = "\n".join(f"+line {line}" for line in range(lines_per_file))
        chunks.append(
            f"diff --git a/{path} b/{path}\n"
            f"--- a/{path}\n"
            f"+++ b/{path}\n"
            f"@@ -0,0 +1,{lines_per_file} @@\n"
            f"{body}\n"
        )
    return "".join(chunks)


def _build_hierarchical_context(*args: object, **kwargs: object) -> object:
    from mergecraft.review.hierarchical_summaries import build_hierarchical_context

    return build_hierarchical_context(*args, **kwargs)


@pytest.mark.xfail(reason="green after DG2.2", strict=False)
def test_large_diff_reduces_to_map_then_summaries_then_hunks() -> None:
    """A large diff becomes a map, cluster summaries, and selected raw hunks."""
    diff_text = _synthetic_diff(files=40, lines_per_file=200)
    risk_regions = {"src/module_0001.py", "migrations/001_init.sql"}

    result = _build_hierarchical_context(
        diff_text,
        token_budget=8_000,
        risk_regions=risk_regions,
    )

    assert result.map, "large diffs must emit a navigable map"
    assert result.summaries, "clusters must be summarized before raw hunks"
    assert result.hunks, "some raw hunks must survive the budget"
    assert result.token_estimate <= 8_000


@pytest.mark.xfail(reason="green after DG2.2", strict=False)
def test_high_risk_regions_keep_raw_tokens() -> None:
    """High-risk paths keep verbatim diff tokens even under a tight budget."""
    diff_text = _synthetic_diff(files=30, lines_per_file=150)
    risk_path = "src/module_0007.py"
    risk_regions = {risk_path}

    result = _build_hierarchical_context(
        diff_text,
        token_budget=2_000,
        risk_regions=risk_regions,
    )

    preserved = {hunk.path for hunk in result.hunks}
    assert risk_path in preserved
    assert any(hunk.raw for hunk in result.hunks if hunk.path == risk_path)


@pytest.mark.xfail(reason="green after DG2.2", strict=False)
def test_reduced_scope_is_reported() -> None:
    """Scope reduction is explicit — large-PR summarization never truncates silently."""
    diff_text = _synthetic_diff(files=60, lines_per_file=500)

    result = _build_hierarchical_context(diff_text, token_budget=4_000)

    assert result.scope_reduction is not None
    assert isinstance(result.scope_reduction, ScopeReduction)
    assert result.scope_reduction.omitted_paths, "reduced scope must name omitted paths"
    reason = result.scope_reduction.reason.lower()
    assert "scope" in reason or "reduced" in reason or "budget" in reason
