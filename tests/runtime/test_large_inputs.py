"""CC3 — large-input degradation (D12) (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC3.1** (RED). Implementation: **CC3.2**.
"""

from __future__ import annotations

from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.run_bounds import (
    ScopeReduction,
    apply_diff_line_budget,
    outcome_with_scope_reduction,
)


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


def test_oversized_diff_degrades_and_reports_reduced_scope() -> None:
    """Oversized diffs record omitted scope — never silent truncation (D12)."""
    original = _synthetic_diff(files=50, lines_per_file=1000)
    reduced_text, reduction = apply_diff_line_budget(original, max_lines=10_000)
    assert reduction is not None
    assert isinstance(reduction, ScopeReduction)
    assert reduction.original_lines > reduction.kept_lines
    assert reduction.omitted_paths, "reduced scope must name omitted paths"
    assert "reduced" in reduction.reason.lower() or "scope" in reduction.reason.lower()
    assert len(reduced_text) < len(original)


def test_reduced_scope_downgrades_the_outcome() -> None:
    """Scope reduction downgrades a would-be pass to ``inconclusive`` (D12)."""
    reduction = ScopeReduction(
        original_lines=50_000,
        kept_lines=10_000,
        omitted_paths=["src/big.py"],
        reason="diff exceeded max_diff_lines; scope reduced",
    )
    assert outcome_with_scope_reduction(RunOutcome.passed, reduction) is RunOutcome.inconclusive
    assert outcome_with_scope_reduction(RunOutcome.failed, reduction) is RunOutcome.failed
