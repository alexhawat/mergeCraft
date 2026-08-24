"""TH1 RED — coverage-delta wrapper must not pre-gate the base tree (H3 / D10).

``scripts/ci_coverage_delta_gate.sh`` currently runs ``make coverage-gate`` on both
the base worktree and the head checkout before ``check_coverage_delta.py`` runs.
TH2 measures base coverage without the floor gate so inherited drift is attributable.
"""

from __future__ import annotations

import pytest

from tests.ci.workflow_support import REPO_ROOT


def _base_worktree_block(script_text: str) -> str:
    """Return the subshell body that measures coverage on the merge base."""
    start = script_text.index('cd "$worktree"')
    end = script_text.index("cp coverage.json", start)
    return script_text[start:end]


@pytest.mark.xfail(
    reason="green after TH2: base tree must measure coverage without floor pre-check",
    strict=False,
)
def test_delta_wrapper_base_measures_without_floor_gate() -> None:
    """The base-side subshell must not run ``make coverage-gate`` before the delta."""
    script_path = REPO_ROOT / "scripts" / "ci_coverage_delta_gate.sh"
    base_block = _base_worktree_block(script_path.read_text(encoding="utf-8"))
    assert "make coverage-gate" not in base_block, (
        "base worktree still runs make coverage-gate before copying coverage-base.json "
        "(H3 / D10 — TH2 must measure without floor gate)"
    )
