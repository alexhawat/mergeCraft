"""Agent span lens attribution (X1) — W5.1 RED suite.

Pins both ``agent_run_span`` call sites in ``src/mergecraft/main.py`` so
``lens=`` receives a lens id, not ``tool_state.selected_mode`` (Review mode).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAIN_PY = _REPO_ROOT / "src" / "mergecraft" / "main.py"

# X1 — both ``with agent_run_span(`` blocks (currently ~L1148 and ~L1170).
_AGENT_RUN_SPAN_RE = re.compile(
    r"with\s+agent_run_span\s*\((.*?)\)\s*:",
    re.DOTALL,
)


def test_agent_span_lens_attribute_is_a_lens_id_not_the_mode() -> None:
    """Neither ``agent_run_span`` site may pass ``selected_mode`` as ``lens``."""
    source = _MAIN_PY.read_text(encoding="utf-8")
    matches = _AGENT_RUN_SPAN_RE.findall(source)
    assert len(matches) >= 2, (
        "X1: expected at least two agent_run_span call sites in main.py; "
        "update this test if the dispatch wiring moved"
    )

    for index, block in enumerate(matches[:2], start=1):
        assert "lens=" in block, f"call site {index} must pass lens= to agent_run_span"
        assert "selected_mode" not in block, (
            f"call site {index} passes tool_state.selected_mode as lens= — "
            "that is the review mode (Review/IncrementalReview), not a lens id"
        )
