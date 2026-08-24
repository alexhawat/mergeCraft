"""TH1 RED — coverage-delta wrapper must not pre-gate the base tree (H3 / D10)."""

from __future__ import annotations

import re

from tests.ci.workflow_support import REPO_ROOT

_BASE_MEASURE_MARKER = "BASE_WORKTREE_MEASURE_BLOCK"
_BASE_MEASURE_BLOCK_RE = re.compile(
    rf"#.*{re.escape(_BASE_MEASURE_MARKER)}.*\n\(\s*\n(.*?)^\)",
    re.MULTILINE | re.DOTALL,
)


def _base_worktree_block(script_text: str) -> str:
    match = _BASE_MEASURE_BLOCK_RE.search(script_text)
    assert match is not None, f"{_BASE_MEASURE_MARKER} block missing from ci_coverage_delta_gate.sh"
    return match.group(1)


def test_delta_wrapper_base_measures_without_floor_gate() -> None:
    script_path = REPO_ROOT / "scripts" / "ci_coverage_delta_gate.sh"
    base_block = _base_worktree_block(script_path.read_text(encoding="utf-8"))
    assert "make coverage-gate" not in base_block, (
        "base worktree still runs make coverage-gate before copying coverage-base.json"
    )
