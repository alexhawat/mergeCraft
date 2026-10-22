"""The merge-evidence packet carries the disposition ledger and closes over it (#941, #942)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION, MergeEvidencePacket
from mergecraft.evidence.run_packet import prepare_run_packet, resolve_prepared_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient


def hit_id_for(finding: Finding) -> str:
    from mergecraft.analyzers.dispositions import hit_id_for as _impl

    return _impl(finding)


def DispositionLedger():
    from mergecraft.analyzers.dispositions import DispositionLedger as _cls

    return _cls()


def _hit(line: int = 2, message: str = "unused import", severity: str = "Minor") -> Finding:
    return make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity=severity,
        confidence="likely",
        message=message,
        path="src/app.py",
        start_line=line,
        end_line=line,
        source="analyzer",
        introduced_by_pr="true",
    )


def _ctx(tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.pr_number = 7
    primary_repo_state(state).checkout_sha = "cafebabecafebabecafebabecafebabecafebabe"
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
            shell="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
        authority_trust="trusted",
    )


def _closed_ledger(kept: list[Finding], *, lost: list[Finding] | None = None) -> Any:
    ledger = DispositionLedger()
    ledger.register_raw([*kept, *(lost or [])])
    ledger.close(kept)
    return ledger


def _record(ctx: ToolContext, kept: list[Finding], ledger: Any, **extra: Any) -> None:
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[finding.model_dump() for finding in kept],
        dispositions=ledger,
        **extra,
    )


def test_schema_version_is_bumped_for_the_analyzers_section() -> None:
    assert PACKET_SCHEMA_VERSION == "1.15.0"


def test_packet_persists_the_ledger_counts_entries_and_audit_rows(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    kept = [_hit(line=3)]
    dropped = _hit(line=40, message="elsewhere")
    ledger = DispositionLedger()
    ledger.register_raw([*kept, dropped])
    ledger.record(
        hit_id_for(dropped), "dropped:baseline", stage="baseline", reason="on base", ref="fp-base"
    )
    ledger.add_suppression_audit(
        fingerprint=dropped.fingerprint, decision="suppressed", reason="pre-existing"
    )
    ledger.close(kept)
    _record(ctx, kept, ledger)

    packet = prepare_run_packet(ctx, run_succeeded=True)

    assert packet is not None
    assert packet.analyzers is not None
    section = packet.analyzers.dispositions[0]
    assert section.source == "catalog"
    assert section.counts.raw == 2
    assert section.counts.kept == 1
    assert section.counts.dropped_by_stage == {"baseline": 1}
    assert {entry.hit_id for entry in section.entries} == {
        hit_id_for(kept[0]),
        hit_id_for(dropped),
    }
    assert all(entry.reason.strip() for entry in section.entries)
    assert [row.decision for row in section.suppression_audit] == ["suppressed"]
    assert section.orphaned_hit_ids == []


def test_packet_round_trips_with_the_analyzers_section(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    kept = [_hit()]
    _record(ctx, kept, _closed_ledger(kept), settings_resolved_from="base_sha")

    packet = prepare_run_packet(ctx, run_succeeded=True)

    assert packet is not None
    reparsed = MergeEvidencePacket.model_validate_json(packet.model_dump_json())
    assert reparsed == packet
    assert reparsed.analyzers is not None
    assert reparsed.analyzers.settings_resolved_from == "base_sha"


def test_packet_json_schema_describes_the_analyzers_section() -> None:
    from mergecraft.evidence.packet import packet_output_schema

    schema = packet_output_schema()
    assert "analyzers" in schema["properties"]


def test_an_open_ledger_makes_the_run_inconclusive_and_names_the_orphan(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    kept = [_hit(line=3)]
    lost = _hit(line=4, message="swallowed by a stage")
    _record(ctx, kept, _closed_ledger(kept, lost=[lost]))

    packet = prepare_run_packet(ctx, run_succeeded=True)

    assert packet is not None
    assert packet.decision is not None
    assert packet.decision.verdict == "neutral"
    assert packet.run_health is not None
    named = [
        finding for finding in packet.run_health.findings if hit_id_for(lost) in finding.message
    ]
    assert named
    assert named[0].scope == "run"
    assert packet.analyzers is not None
    assert packet.analyzers.dispositions[0].orphaned_hit_ids == [hit_id_for(lost)]


def test_a_closed_ledger_does_not_degrade_a_successful_run(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    kept = [_hit(line=3)]
    _record(ctx, kept, _closed_ledger(kept))

    packet = prepare_run_packet(ctx, run_succeeded=True)

    assert packet is not None
    assert packet.decision is not None
    assert packet.decision.verdict == "success"
    assert packet.run_health is None


def test_the_cached_re_finalization_keeps_an_open_ledger_neutral(tmp_path: Path) -> None:
    """Re-finalizing the cached shell must not turn an open ledger back into success.

    The second call takes the cached path, which assembles nothing: the shell it
    already holds names the orphan, so the verdict has to come from that shell
    rather than from the caller's ``run_succeeded`` alone (#941).
    """
    ctx = _ctx(tmp_path)
    kept = [_hit(line=3)]
    lost = _hit(line=4, message="swallowed by a stage")
    _record(ctx, kept, _closed_ledger(kept, lost=[lost]))

    first = resolve_prepared_run_packet(ctx, run_succeeded=True)
    assert first is not None
    assert first.decision is not None
    assert first.decision.verdict == "neutral"

    cached = resolve_prepared_run_packet(ctx, run_succeeded=True)

    assert cached is not None
    assert cached.decision is not None
    assert cached.decision.verdict == "neutral"
    assert cached.decision.reason is not None
    assert "ledger open" in cached.decision.reason


def test_the_cached_re_finalization_keeps_a_closed_ledger_successful(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    kept = [_hit(line=3)]
    _record(ctx, kept, _closed_ledger(kept))

    resolve_prepared_run_packet(ctx, run_succeeded=True)
    cached = resolve_prepared_run_packet(ctx, run_succeeded=True)

    assert cached is not None
    assert cached.decision is not None
    assert cached.decision.verdict == "success"


def test_blockers_still_win_over_an_open_ledger(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    blocker = _hit(line=3, message="hard coded credential", severity="Major")
    lost = _hit(line=4, message="swallowed by a stage")
    _record(ctx, [blocker], _closed_ledger([blocker], lost=[lost]))

    packet = prepare_run_packet(ctx, run_succeeded=True)

    assert packet is not None
    assert packet.decision is not None
    assert packet.decision.verdict == "failure"


def test_run_without_analyzers_has_no_analyzers_section(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)

    packet = prepare_run_packet(ctx, run_succeeded=True)

    assert packet is not None
    assert packet.analyzers is None


@pytest.mark.parametrize("resolved_from", ["base_snapshot", "base_sha", "defaults"])
def test_resolved_from_is_recorded_even_without_a_ledger(
    tmp_path: Path, resolved_from: str
) -> None:
    ctx = _ctx(tmp_path)
    ctx.tool_state.analyzer_run = AnalyzerRunState(ran=False, settings_resolved_from=resolved_from)

    packet = prepare_run_packet(ctx, run_succeeded=True)

    assert packet is not None
    assert packet.analyzers is not None
    assert packet.analyzers.settings_resolved_from == resolved_from
