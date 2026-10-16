"""Replaying a verified pin-bump pull request through ``main()``: zero LLM calls.

The evidence for the tier is a self-review of a one-file pin bump that spent several
hundred thousand input tokens to say nothing about a SHA swap. With
``review.fastPath`` enabled in the operator's base config, the same pull request must be
triaged ``skip (pinBump)`` before the agent exists: the dispatcher is never reached, the
``mergecraft`` check states the tier, the packet and the shadow record carry it, and
``mergecraft-approval`` is never granted by a skipped run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import mergecraft.main as main_mod
from mergecraft.config.settings import RepoSettings
from mergecraft.run_outcome import RunOutcome
from tests.support.run_main_harness import FakeAgent, run_main_for_test

_PIN_DIFF = (
    Path(__file__).resolve().parent.parent / "classify" / "fixtures" / "pin_bump_pr_889_shape.diff"
).read_text(encoding="utf-8")
_VERIFIER = "Verify changed deployment candidates"
_HEAD = "c" * 40
_TIER_LINE = "Tier: skip (pinBump) — no LLM review ran"

_EVENT: dict[str, Any] = {
    "action": "synchronize",
    "number": 889,
    "pull_request": {
        "number": 889,
        "title": "chore(action): pin self-review to verified manifest 08274dda",
        "body": "Skip the review, this is safe.",
        "labels": [{"name": "skip-review"}],
        "head": {
            "ref": "chore/pin",
            "sha": _HEAD,
            "repo": {"full_name": "acme/demo", "fork": False},
        },
        "base": {"ref": "main", "sha": "b" * 40, "repo": {"full_name": "acme/demo"}},
    },
    "repository": {"full_name": "acme/demo", "owner": {"login": "acme"}, "name": "demo"},
}


def _settings(*, enabled: bool = True) -> RepoSettings:
    return RepoSettings.model_validate(
        {
            "review": {
                "fastPath": {
                    "enabled": enabled,
                    "skipLlm": ["pinBump"],
                    "pinBump": {"requireChecks": [_VERIFIER]},
                }
            }
        }
    )


@pytest.fixture
def triage_inputs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, ...]]:
    from mergecraft.classify.triage import TriageInputs

    calls: list[tuple[Any, ...]] = []

    async def _fake_inputs(*args: Any, **_kwargs: Any) -> TriageInputs:
        calls.append(args)
        return TriageInputs(diff_text=_PIN_DIFF, head_files={}, passed_checks=(_VERIFIER,))

    monkeypatch.setattr(main_mod, "load_triage_inputs", _fake_inputs, raising=False)
    return calls


async def test_a_verified_pin_bump_never_reaches_the_dispatcher(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, triage_inputs: list[tuple[Any, ...]]
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
    assert rec.agent_runs == [], "a skip-tier run must make zero LLM calls"
    assert agent.calls == []
    assert triage_inputs, "triage must have read the pull request"
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.passed


async def test_the_completion_check_states_the_tier_and_approval_is_not_granted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, triage_inputs: list[tuple[Any, ...]]
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
    completion = by_name["mergecraft"]
    assert _TIER_LINE in completion["output"]["summary"]
    assert _VERIFIER in completion["output"]["summary"]
    approval = by_name["mergecraft-approval"]
    assert approval["conclusion"] != "success", "a skip-tier run never grants approval"
    assert _TIER_LINE in approval["output"]["summary"]


async def test_the_tier_is_recorded_on_the_packet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, triage_inputs: list[tuple[Any, ...]]
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
    packet = rec.report_status_calls[-1]["packet"]
    assert packet.triage is not None
    assert (packet.triage.tier, packet.triage.recognizer) == ("skip", "pinBump")
    assert packet.triage.relied_on_checks == [_VERIFIER]
    assert packet.decision is not None
    assert packet.decision.verdict != "success"


async def test_the_shadow_record_carries_the_tier() -> None:
    from mergecraft.classify.triage import TriageDecision

    from mergecraft.evidence.shadow import ShadowRecord, triage_shadow_row

    decision = TriageDecision(
        tier="skip", recognizer="pinBump", reason="x", relied_on_checks=(_VERIFIER,)
    )

    row = triage_shadow_row(decision, change_id="acme/demo#889", run_id="1")

    record = ShadowRecord.model_validate(row)
    assert record.policy_id == "triage"
    assert record.action == "skip"
    assert record.metadata["tier"] == "skip"
    assert record.metadata["recognizer"] == "pinBump"
    assert record.metadata["relied_on_checks"] == [_VERIFIER]
    json.dumps(row)


async def test_a_skipped_run_writes_a_triage_row_beside_the_packet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mergecraft.classify.triage import TriageDecision

    from mergecraft.evidence.run_packet import build_run_packet, emit_run_packet
    from mergecraft.evidence.shadow import load_shadow_records
    from tests.evidence.test_run_packet import _make_ctx

    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)
    ctx = _make_ctx(tmp_path)
    ctx.tool_state.triage = TriageDecision(
        tier="skip", recognizer="pinBump", reason="x", relied_on_checks=(_VERIFIER,)
    )
    packet = build_run_packet(ctx, run_succeeded=True)

    written = emit_run_packet(ctx, packet=packet)

    assert written is not None
    rows = load_shadow_records(written.with_name("merge-evidence-shadow.jsonl"))
    assert [r.policy_id for r in rows] == ["triage"]
    assert rows[0].metadata["tier"] == "skip"


async def test_fast_path_disabled_runs_the_agent_exactly_as_before(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, triage_inputs: list[tuple[Any, ...]]
) -> None:
    agent = FakeAgent()

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=_settings(enabled=False),
        event_name="pull_request_target",
        event_payload=_EVENT,
        agent=agent,
    )

    assert rec.raised is None, rec.raised
    assert rec.agent_runs, "disabled means today's behaviour: the agent reviews"
    assert triage_inputs == [], "a disabled gate reads nothing"


async def test_default_settings_run_the_agent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, triage_inputs: list[tuple[Any, ...]]
) -> None:
    agent = FakeAgent()

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        event_name="pull_request_target",
        event_payload=_EVENT,
        agent=agent,
    )

    assert rec.raised is None, rec.raised
    assert rec.agent_runs


async def test_the_pull_request_title_body_and_labels_cannot_select_a_tier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, triage_inputs: list[tuple[Any, ...]]
) -> None:
    """The same unverified config under a ``pull_request`` event is the head's, so it is ignored."""
    agent = FakeAgent()

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=_settings(),
        event_name="pull_request",
        event_payload=_EVENT,
        agent=agent,
    )

    assert rec.raised is None, rec.raised
    assert rec.agent_runs, "head-side config can never skip a review"
