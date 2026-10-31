"""SARIF ingested from ``ciEvidence.sarifArtifacts`` follows the same disposition contract (#941)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.mcp.tool_state import init_tool_state


def hit_id_for(finding: Finding) -> str:
    from mergecraft.analyzers.dispositions import hit_id_for as _impl

    return _impl(finding)


def _sarif_hit(line: int, message: str = "tainted sink", severity: str = "Major") -> Finding:
    return make_finding(
        tool="codeql",
        rule_id="py/sql-injection",
        category="Security & Privacy",
        severity=severity,
        confidence="likely",
        message=message,
        path="src/db.py",
        start_line=line,
        end_line=line,
        source="ci",
    )


def test_every_sarif_hit_ends_kept_or_merged_with_a_reason(tmp_path: Path) -> None:
    from mergecraft.ci.evidence import record_sarif_findings

    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    first = _sarif_hit(3)
    duplicate = _sarif_hit(3, severity="Minor")  # same hit reported by a second SARIF run
    other = _sarif_hit(9, message="another sink")

    record_sarif_findings(state, [first, duplicate, other])

    assert state.ci_evidence is not None
    ledger = state.ci_evidence.sarif_dispositions
    assert ledger is not None
    summary = ledger.summary()
    assert summary.orphaned == []
    assert summary.raw == len({hit_id_for(first), hit_id_for(other)})
    assert summary.kept == summary.raw
    assert all(entry.reason.strip() for entry in ledger.entries())


def test_sarif_hits_that_never_reach_the_evidence_are_orphans(tmp_path: Path) -> None:
    from mergecraft.ci.evidence import record_sarif_findings

    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    hit = _sarif_hit(3)
    record_sarif_findings(state, [hit])

    ledger = state.ci_evidence.sarif_dispositions  # type: ignore[union-attr]
    ledger.register_raw([_sarif_hit(77, message="registered but never recorded")])

    assert len(ledger.orphans()) == 1


def test_sarif_ledger_reaches_the_packet(tmp_path: Path) -> None:
    from mergecraft.ci.evidence import record_sarif_findings
    from mergecraft.evidence.run_packet import prepare_run_packet
    from tests.evidence.test_packet_dispositions import _ctx

    ctx = _ctx(tmp_path)
    record_sarif_findings(ctx.tool_state, [_sarif_hit(3), _sarif_hit(9, message="another sink")])

    packet = prepare_run_packet(ctx, run_succeeded=True)

    assert packet is not None
    assert packet.analyzers is not None
    sources = {section.source for section in packet.analyzers.dispositions}
    assert "ci_sarif" in sources
