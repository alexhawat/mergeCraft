"""J1.6 — parallel judge, evidence/claim packs, JevJudgePin (D11, G10)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.jev.support import (
    PINNED_MODEL,
    TRANSPORT_DIR,
    assert_honest_skip,
    import_jev,
    load_review,
    loguru_lines,
    make_agent_finding,
    skipping_jev_client,
)


def _judge() -> Any:
    return import_jev("judge")


def _client() -> Any:
    return import_jev("client")


def test_jev_judge_pin_records_pinned_model() -> None:
    pin = _judge().JevJudgePin()
    assert pin.model == PINNED_MODEL
    assert pin.model_pinned is True
    assert pin.judge_version
    assert pin.rubric_version
    assert pin.provider in {"jev", "typesafe"}


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


def _attestation_ids(result: Any) -> list[str]:
    return [item.rule_id for item in result.findings]


def _assert_run_scoped_attestations(result: Any) -> None:
    assert result.scope == "run"
    assert result.blocking is False
    for item in result.findings:
        assert item.scope == "run"
        assert item.severity in {"Trivial", "Minor", "Major", "Critical"}


async def test_unsupported_evidence_emits_jev_evidence_unsupported() -> None:
    """F-UNBACKED-RULE-IDS: deleting the ``jev-evidence-unsupported`` emit-if fails this test."""
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
    assert "jev-evidence-unsupported" in _attestation_ids(result)
    _assert_run_scoped_attestations(result)


async def test_unbacked_blocker_emits_jev_claim_unbacked_blocker() -> None:
    """F-UNBACKED-RULE-IDS: deleting the ``jev-claim-unbacked-blocker`` emit-if fails this test."""
    module = _client()
    transport = module.RecordedTransport.from_fixture(
        TRANSPORT_DIR / "claim_blocker_without_row.json"
    )
    result = await _judge().judge_prose_claims(
        load_review("blocker_summary_no_findings.md"),
        findings=[],
        client=module.AsyncJevClient(api_key="mc-test-jev-key", transport=transport),
    )
    assert "jev-claim-unbacked-blocker" in _attestation_ids(result)
    _assert_run_scoped_attestations(result)


async def test_verdict_mismatch_emits_jev_claim_verdict_mismatch() -> None:
    """F-UNBACKED-RULE-IDS: deleting the ``jev-claim-verdict-mismatch`` emit-if fails this test."""
    module = _client()
    transport = module.RecordedTransport.from_fixture(TRANSPORT_DIR / "claim_verdict_mismatch.json")
    result = await _judge().judge_prose_claims(
        "The change is approved even though the summary request_changes it.\n",
        findings=[],
        client=module.AsyncJevClient(api_key="mc-test-jev-key", transport=transport),
    )
    assert "jev-claim-verdict-mismatch" in _attestation_ids(result)
    _assert_run_scoped_attestations(result)


async def test_two_terminal_verdicts_violate_exactly_one_verdict_rule() -> None:
    """Plan 21 D6 rule 4: two terminal verdicts must emit a run-scoped attestation."""
    module = _client()
    transport = module.RecordedTransport.from_fixture(
        TRANSPORT_DIR / "claim_blocker_without_row.json"
    )
    result = await _judge().judge_prose_claims(
        load_review("two_terminal_verdicts.md"),
        findings=[],
        client=module.AsyncJevClient(api_key="mc-test-jev-key", transport=transport),
    )
    assert "jev-claim-verdict-mismatch" in _attestation_ids(result)
    _assert_run_scoped_attestations(result)


async def test_judge_finding_evidence_skip_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-SKIP-RAISES: judge skip stays a skip (D4). Guard-deletion for raise-on-skip."""
    types = import_jev("types")
    client, transport = skipping_jev_client(monkeypatch, "evidence_says_nothing.json")
    finding = make_agent_finding(
        message="Untrusted input is executed via shell=True",
        evidence=["def add(left, right): return left + right"],
    )
    with loguru_lines() as logs:
        try:
            result = await _judge().judge_finding_evidence(
                finding,
                cited_section=finding.evidence[0],
                client=client,
            )
        except types.JevError as exc:
            pytest.fail(f"judge must not raise JevError on skip (D4); code={exc.code}")
    assert transport.calls == 0
    assert_honest_skip(result, logs, reason="credential_absent")


async def test_judge_prose_claims_skip_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-SKIP-RAISES: claim battery skip stays a skip (D4)."""
    types = import_jev("types")
    client, transport = skipping_jev_client(monkeypatch, "claim_blocker_without_row.json")
    with loguru_lines() as logs:
        try:
            result = await _judge().judge_prose_claims(
                load_review("blocker_summary_no_findings.md"),
                findings=[],
                client=client,
            )
        except types.JevError as exc:
            pytest.fail(f"judge must not raise JevError on skip (D4); code={exc.code}")
    assert transport.calls == 0
    assert_honest_skip(result, logs, reason="credential_absent")
