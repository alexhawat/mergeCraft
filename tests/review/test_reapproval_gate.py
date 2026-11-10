"""Re-approval through ``main()`` (#1284): zero LLM calls, the prior verdict on the new head.

``_triage_gate`` consults the re-approval proof before the recognizers. When the proof
holds, the run never reaches the dispatcher, the checks are published on the exact new
head with the prior review link, the compared SHAs, the qualifying path and the skipped
work, and ``mergecraft-approval`` carries the prior pass over. When it does not, the run
is the normal review, and its approval check still states the review stamp a later
re-approval reads back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import mergecraft.main as main_mod
import mergecraft.reapproval as reapproval_mod
from mergecraft.classify.reapproval import (
    ReapprovalRecord,
    ReapprovalVerdict,
    ReviewStamp,
    parse_review_stamp,
)
from mergecraft.config.settings import RepoSettings
from mergecraft.reapproval import ReapprovalOutcome
from mergecraft.run_outcome import RunOutcome
from tests.support.run_main_harness import FakeAgent, run_main_for_test

_PRIOR = "a" * 40
_HEAD = "c" * 40
_PRIOR_URL = "https://github.com/acme/demo/actions/runs/42697047477"
_STAMP = ReviewStamp(pull_number=1280, base_ref="main", policy_digest="d" * 64)

_EVENT: dict[str, Any] = {
    "action": "synchronize",
    "number": 1280,
    "pull_request": {
        "number": 1280,
        "title": "Merge main",
        "body": "",
        "head": {"ref": "feature", "sha": _HEAD, "repo": {"full_name": "acme/demo", "fork": False}},
        "base": {"ref": "main", "sha": "b" * 40, "repo": {"full_name": "acme/demo"}},
    },
    "repository": {"full_name": "acme/demo", "owner": {"login": "acme"}, "name": "demo"},
}


def _record() -> ReapprovalRecord:
    return ReapprovalRecord(
        prior_url=_PRIOR_URL,
        prior_check_id=101,
        prior_head_sha=_PRIOR,
        head_sha=_HEAD,
        prior_merge_base="1" * 40,
        merge_base="2" * 40,
        qualifying_paths=("CHANGELOG.md",),
        preserved_paths=("src/app.py",),
        inherited_paths=("src/other.py",),
    )


def _settings(*, reapproval: bool = True) -> RepoSettings:
    # A same-repo ``pull_request_target`` run holds approval authority only at
    # ``selfReview: full`` — the posture this repository's own self-review runs at.
    return RepoSettings.model_validate(
        {
            "trust": {"selfReview": "full"},
            "review": {
                "fastPath": {
                    "enabled": True,
                    "reapproval": {
                        "enabled": reapproval,
                        "trustedCheckApps": ["mergecraft-reviewer"],
                    },
                }
            },
        }
    )


class _Evaluator:
    def __init__(self, outcome: ReapprovalOutcome) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> ReapprovalOutcome:
        self.calls.append({"args": args, **kwargs})
        return self.outcome


@pytest.fixture
def eligible(monkeypatch: pytest.MonkeyPatch) -> _Evaluator:
    record = _record()
    evaluator = _Evaluator(
        ReapprovalOutcome(verdict=ReapprovalVerdict(record, record.reason()), stamp=_STAMP)
    )
    monkeypatch.setattr(reapproval_mod, "evaluate_reapproval", evaluator)
    return evaluator


@pytest.fixture
def refused(monkeypatch: pytest.MonkeyPatch) -> _Evaluator:
    evaluator = _Evaluator(
        ReapprovalOutcome(
            verdict=ReapprovalVerdict(None, "src/app.py changed since the review"), stamp=_STAMP
        )
    )
    monkeypatch.setattr(reapproval_mod, "evaluate_reapproval", evaluator)
    return evaluator


@pytest.fixture
def no_triage_read(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    from mergecraft.classify.triage import TriageInputs

    reads: list[Any] = []

    async def _inputs(*args: Any, **_kwargs: Any) -> TriageInputs:
        reads.append(args)
        return TriageInputs(diff_text="", head_files={}, passed_checks=())

    monkeypatch.setattr(main_mod, "load_triage_inputs", _inputs, raising=False)
    return reads


async def test_a_carried_over_pass_makes_zero_llm_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, eligible: _Evaluator, no_triage_read: list[Any]
) -> None:
    agent = FakeAgent()

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=_settings(),
        event_name="pull_request_target",
        event_payload=_EVENT,
        agent=agent,
    )

    assert rec.raised is None, rec.raised
    assert rec.agent_runs == []
    assert agent.calls == []
    assert len(eligible.calls) == 1
    assert eligible.calls[0]["args"][3:] == (1280, _HEAD)
    assert no_triage_read == [], "the recognizers never re-read a carried-over pull request"
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.passed


async def test_the_checks_publish_the_reused_verdict_on_the_new_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, eligible: _Evaluator, no_triage_read: list[Any]
) -> None:
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=_settings(),
        event_name="pull_request_target",
        event_payload=_EVENT,
        capture_status_checks=True,
    )

    assert rec.raised is None, rec.raised
    by_name = {run["name"]: run for run in rec.status_check_runs}
    for name in ("mergecraft", "mergecraft-approval"):
        run = by_name[name]
        assert run["head_sha"] == _HEAD
        summary = run["output"]["summary"]
        assert f"Prior review: {_PRIOR_URL}" in summary
        assert f"Compared: {_PRIOR}..{_HEAD}" in summary
        assert "Qualifying path: CHANGELOG.md" in summary
        assert "Skipped: LLM review" in summary
        assert "Reused from the prior review: the mergecraft-approval verdict" in summary
        assert "Other required checks are not reused" in summary
    approval = by_name["mergecraft-approval"]
    assert approval["conclusion"] == "success"
    assert parse_review_stamp(approval["output"]["summary"]) == _STAMP


async def test_the_packet_records_the_reapproval(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, eligible: _Evaluator, no_triage_read: list[Any]
) -> None:
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=_settings(),
        event_name="pull_request_target",
        event_payload=_EVENT,
        capture_status_checks=True,
    )

    packet = rec.report_status_calls[-1]["packet"]
    assert packet.reviewed_head_sha == _HEAD
    assert (packet.triage.tier, packet.triage.recognizer) == ("skip", "reapproval")
    section = packet.triage.reapproval
    assert section.prior_head_sha == _PRIOR
    assert section.prior_url == _PRIOR_URL
    assert section.qualifying_paths == ["CHANGELOG.md"]
    assert "LLM review" in section.skipped
    assert packet.decision.verdict == "success"
    assert _PRIOR in packet.decision.reason


async def test_a_refused_reapproval_runs_the_normal_review_and_stamps_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, refused: _Evaluator, no_triage_read: list[Any]
) -> None:
    agent = FakeAgent()

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=_settings(),
        event_name="pull_request_target",
        event_payload=_EVENT,
        agent=agent,
        capture_status_checks=True,
    )

    assert rec.raised is None, rec.raised
    assert rec.agent_runs, "a refused re-approval is the normal review"
    assert len(refused.calls) == 1
    packet = rec.report_status_calls[-1]["packet"]
    assert packet.triage is None or packet.triage.reapproval is None
    approval = {run["name"]: run for run in rec.status_check_runs}["mergecraft-approval"]
    assert parse_review_stamp(approval["output"]["summary"]) == _STAMP


async def test_reapproval_off_reads_nothing_and_stamps_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, eligible: _Evaluator, no_triage_read: list[Any]
) -> None:
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=_settings(reapproval=False),
        event_name="pull_request_target",
        event_payload=_EVENT,
        agent=FakeAgent(),
        capture_status_checks=True,
    )

    assert rec.raised is None, rec.raised
    assert eligible.calls == []
    assert rec.agent_runs
    approval = {run["name"]: run for run in rec.status_check_runs}["mergecraft-approval"]
    assert parse_review_stamp(approval["output"]["summary"]) is None


async def test_head_side_config_never_reapproves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, eligible: _Evaluator, no_triage_read: list[Any]
) -> None:
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=_settings(),
        event_name="pull_request",
        event_payload=_EVENT,
        agent=FakeAgent(),
    )

    assert rec.raised is None, rec.raised
    assert eligible.calls == []
    assert rec.agent_runs


async def test_an_untrusted_run_never_grants_the_carried_over_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.classify.triage import TriageDecision
    from mergecraft.evidence.run_packet import build_run_packet
    from tests.evidence.test_run_packet import _make_ctx

    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)
    ctx = _make_ctx(tmp_path, findings=[])
    ctx.tool_state.analyzer_run = None
    ctx.tool_state.reapproval = _record()
    ctx.tool_state.triage = TriageDecision(tier="skip", recognizer="reapproval", reason="x")

    ctx.authority_trust = "trusted"
    trusted = build_run_packet(ctx, run_succeeded=True)
    ctx.authority_trust = "untrusted"
    untrusted = build_run_packet(ctx, run_succeeded=True)
    ctx.authority_trust = "trusted"
    crashed = build_run_packet(ctx, run_succeeded=False)

    assert trusted.decision is not None
    assert trusted.decision.verdict == "success"
    assert untrusted.decision is not None
    assert untrusted.decision.verdict == "neutral"
    assert crashed.decision is not None
    assert crashed.decision.verdict != "success"


async def test_a_blocker_is_never_softened_by_a_carried_over_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.classify.triage import TriageDecision
    from mergecraft.evidence.run_packet import build_run_packet
    from tests.evidence.test_run_packet import _make_ctx

    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)
    ctx = _make_ctx(tmp_path)
    ctx.authority_trust = "trusted"
    ctx.tool_state.reapproval = _record()
    ctx.tool_state.triage = TriageDecision(tier="skip", recognizer="reapproval", reason="x")
    ctx.tool_state.analyzer_run.findings[0]["severity"] = "Critical"

    packet = build_run_packet(ctx, run_succeeded=True)

    assert packet.decision is not None
    assert packet.decision.verdict == "failure"
