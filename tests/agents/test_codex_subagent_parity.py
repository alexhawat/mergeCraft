"""HA4.1 RED suite — Codex prose-only subagent degradation is declared (D15).

Real Codex subagent dispatch needs the agent registry (review-integrity file 3 /
W-10). HA4 records the gap so a harness-by-model benchmark cannot silently treat
the instruction-preamble path as toolset parity with Claude/OpenCode.
"""

from __future__ import annotations

import pytest

_HA42 = pytest.mark.xfail(reason="green after HA4.2: tool classes", strict=False)


@_HA42
def test_codex_subagent_degradation_is_declared() -> None:
    """D15 — the prose-only subagent path is a declared limitation, not parity."""
    from mergecraft.agents.codex import CODEX_SUBAGENT_DEGRADATION

    assert CODEX_SUBAGENT_DEGRADATION.kind == "prose-only"
    assert CODEX_SUBAGENT_DEGRADATION.toolset_parity is False
