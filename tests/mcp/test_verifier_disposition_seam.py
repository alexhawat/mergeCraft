"""A verifier verdict reaches the disposition ledger through the real MCP tool (#941)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.mcp.test_verification import _ctx

from mergecraft.analyzers.dispositions import DispositionLedger
from mergecraft.analyzers.finding import make_finding
from mergecraft.mcp.verification import record_finding_verdict_tool


def _ledger_with_kept_hit():
    hit = make_finding(
        tool="semgrep",
        rule_id="sqli",
        category="Security & Privacy",
        severity="Major",
        confidence="likely",
        message="query built from user input",
        path="src/app.py",
        start_line=12,
        end_line=12,
        source="analyzer",
    )
    ledger = DispositionLedger()
    ledger.register_raw([hit])
    ledger.close([hit])
    return hit, ledger


@pytest.mark.asyncio
async def test_a_verifier_drop_is_recorded_against_the_analyzer_hit(tmp_path: Path) -> None:
    hit, ledger = _ledger_with_kept_hit()
    ctx = _ctx(tmp_path)
    assert ctx.tool_state.analyzer_run is not None
    ctx.tool_state.analyzer_run.dispositions = ledger

    await record_finding_verdict_tool(ctx).execute(
        {"fingerprint": hit.fingerprint, "verdict": "drop", "reason": "input is validated upstream"}
    )

    entry = ledger.entry_for(hit)
    assert entry is not None
    assert (entry.disposition, entry.stage) == ("dropped:verifier", "verifier")
    assert "validated upstream" in entry.reason
    assert ledger.orphans() == []
