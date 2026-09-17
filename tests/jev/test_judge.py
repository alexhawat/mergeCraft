"""J1.6 — parallel judge, evidence/claim packs, JevJudgePin (D11, G10)."""

from __future__ import annotations

from typing import Any

from tests.jev.support import (
    J4_XFAIL,
    PINNED_MODEL,
    TRANSPORT_DIR,
    import_jev,
    load_review,
    make_agent_finding,
)


def _judge() -> Any:
    return import_jev("judge")


def _client() -> Any:
    return import_jev("client")


@J4_XFAIL
def test_jev_judge_pin_records_pinned_model() -> None:
    pin = _judge().JevJudgePin()
    assert pin.model == PINNED_MODEL
    assert pin.model_pinned is True
    assert pin.judge_version
    assert pin.rubric_version
    assert pin.provider in {"jev", "typesafe"}


@J4_XFAIL
async def test_evidence_pack_over_unsupported_quote() -> None:
    module = _client()
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / "evidence_says_nothing.json")
    finding = make_agent_finding(
        message="Untrusted input is executed via shell=True",
        path="src/mergecraft/mcp/shell.py",
        evidence=["def add(left, right): return left + right"],
    )
    result = await _judge().judge_finding_evidence(
        finding,
        cited_section=finding.evidence[0],
        client=module.AsyncJevClient(api_key="mc-test-jev-key", transport=transport),
    )
    assert result.pack_id == "evidence/v1"
    assert result.relation == "says_nothing"
    assert result.scope == "run"
    assert result.blocking is False
    assert result.pin.model == PINNED_MODEL
    assert transport.calls == 1


@J4_XFAIL
async def test_claim_pack_over_blocker_summary_with_no_findings_row() -> None:
    module = _client()
    transport = module.RecordedTransport.from_fixture(
        TRANSPORT_DIR / "claim_blocker_without_row.json"
    )
    result = await _judge().judge_prose_claims(
        load_review("blocker_summary_no_findings.md"),
        findings=[],
        client=module.AsyncJevClient(api_key="mc-test-jev-key", transport=transport),
    )
    assert result.pack_id == "claim/v1"
    assert result.backed_by_row < 0.5
    assert result.blocking_language >= 0.5
    assert result.scope == "run"
    assert result.blocking is False


@J4_XFAIL
async def test_judge_runs_beside_verifier_not_instead() -> None:
    from mergecraft.agents.verifier import should_verify

    finding = make_agent_finding(
        message="Untrusted input is executed via shell=True",
        severity="Critical",
    )
    assert should_verify(finding) is True
    module = _client()
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / "evidence_says_nothing.json")
    result = await _judge().run_parallel_judge(
        findings=[finding],
        review_body=load_review("blocker_summary_no_findings.md"),
        client=module.AsyncJevClient(api_key="mc-test-jev-key", transport=transport),
    )
    assert result.replaces_verifier is False
    assert result.mode == "parallel"
    assert should_verify(finding) is True


@J4_XFAIL
def test_judge_disagreement_is_a_signal_not_a_gate() -> None:
    judge = _judge()
    record = judge.record_judge_disagreement(
        jev_verdict="unsupported",
        verifier_verdict="confirm",
        fingerprint="abc123",
    )
    assert record.gate is False
    assert record.signal is True
    assert record.fingerprint == "abc123"
