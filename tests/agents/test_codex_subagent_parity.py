"""HA4 suite — Codex prose-only subagent degradation is declared (D15).

Real Codex subagent dispatch needs the agent registry (review-integrity file 3 /
W-10). HA4 records the gap so a harness-by-model benchmark cannot silently treat
the instruction-preamble path as toolset parity with Claude/OpenCode.
"""

from __future__ import annotations

from dataclasses import fields


def test_codex_subagent_degradation_is_declared() -> None:
    """D15 — the prose-only subagent path is a declared limitation, not parity."""
    from mergecraft.agents.codex import CODEX_SUBAGENT_DEGRADATION, CodexSubagentDegradation

    assert isinstance(CODEX_SUBAGENT_DEGRADATION, CodexSubagentDegradation)
    assert {f.name for f in fields(CodexSubagentDegradation)} == {"kind", "toolset_parity"}
    assert CODEX_SUBAGENT_DEGRADATION.kind == "prose-only"
    assert CODEX_SUBAGENT_DEGRADATION.toolset_parity is False
