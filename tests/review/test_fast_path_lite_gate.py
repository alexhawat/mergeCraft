"""The ``lite`` tier through the gate, the packet, the checks and a whole ``main()`` run.

``lite`` is one capped LLM call, and it is triage, not review: it can add a blocking
finding but it can never grant ``mergecraft-approval``. The pre-dispatch gate honours
it only from the operator's base-side config and turns any read failure into a full
review. ``main._triage_gate`` hands a ``lite`` decision to the single-call driver and
returns a ``LiteAgentReview`` (a sibling of ``SkipAgentReview``), so the agent and its
MCP server are never started. The packet records the cap and the tokens the call used;
a ``lite`` run with a ``success`` decision is refused; the ``mergecraft`` check is
``neutral``, or ``failure`` when the call raised a Critical or Major finding. A cap
the provider reports overrunning, or a malformed answer, is ``inconclusive``. A diff
too large for the cap is downgraded to the full review it would have had anyway.

The single-call driver is substituted through ``main``'s module-level
``run_lite_review`` binding, exactly as ``load_triage_inputs`` is.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import mergecraft.main as main_mod
from mergecraft.config.settings import RepoSettings
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.run_outcome import RunOutcome
from tests.review.test_fast_path_gate import FakeScm, _check, _files_from_diff
from tests.support.run_main_harness import FakeAgent, run_main_for_test

if TYPE_CHECKING:
    from mergecraft.config.settings import FastPathSettings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PIN_DIFF = (
    Path(__file__).resolve().parent.parent / "classify" / "fixtures" / "pin_bump_pr_889_shape.diff"
).read_text(encoding="utf-8")
_VERIFIER = "Verify changed deployment candidates"
_TRUSTED_APP = "mergecraft-reviewer"
_HEAD = "c" * 40
_CAP = 9_000
_LITE_LINE = f"Tier: lite — single-call review, cap {_CAP} tokens"
_PROMPT_VERSION = "lite-test-v1"
_WHITESPACE_DIFF = (
    "diff --git a/src/a.js b/src/a.js\n--- a/src/a.js\n+++ b/src/a.js\n"
    "@@ -1 +1 @@\n-let a = 1;  \n+let a = 1;\n"
)
_COMMENT_PATCH = "@@ -1,3 +1,3 @@\n let a = 1;\n-// old note\n+// new note\n let b = 2;\n"
_COMMENT_HEAD = "let a = 1;\n// new note\nlet b = 2;\n"


def _fast_path(*, lite_enabled: bool = True, skip_llm: list[str] | None = None) -> dict[str, Any]:
    return {
        "enabled": True,
        "skipLlm": skip_llm if skip_llm is not None else [],
        "pinBump": {"requireChecks": [_VERIFIER], "trustedCheckApps": [_TRUSTED_APP]},
        "lite": {
            "enabled": lite_enabled,
            "provider": "cheapo",
            "model": "tiny-1",
            "tokenCap": _CAP,
        },
    }


def _config(**kwargs: Any) -> FastPathSettings:
    from mergecraft.config.settings import FastPathSettings

    return FastPathSettings.model_validate(_fast_path(**kwargs))


def _settings(**kwargs: Any) -> RepoSettings:
    return RepoSettings.model_validate({"review": {"fastPath": _fast_path(**kwargs)}})


def _outcome(**overrides: Any) -> Any:
    from mergecraft.agents.lite import LiteOutcome

    fields: dict[str, Any] = {
        "status": "reviewed",
        "reason": "single-call review completed",
        "tokens_used": 1_200,
        "usage_estimated": False,
        "cap_hit": False,
        "findings": [],
        "summary": "Nothing stands out.",
        "prompt_version": _PROMPT_VERSION,
    }
    fields.update(overrides)
    return LiteOutcome(**fields)


def _major() -> dict[str, Any]:
    return {
        "path": ".github/workflows/ci.yml",
        "line": 12,
        "severity": "Major",
        "message": "LITE-MAJOR the pinned action now runs with write permissions",
    }


async def _decide(scm: FakeScm, **kwargs: Any) -> Any:
    from mergecraft.fast_path import decide_fast_path

    options: dict[str, Any] = {"config": _config(), "operator_owned": True}
    options.update(kwargs)
    return await decide_fast_path(scm, "acme", "demo", 7, _HEAD, **options)  # type: ignore[arg-type]


# ── the pre-dispatch gate ─────────────────────────────────────────────────────


async def test_an_unopted_recognizer_match_is_lite_from_the_operators_config() -> None:
    scm = FakeScm(files=_files_from_diff(_WHITESPACE_DIFF))

    decision = await _decide(scm)

    assert decision.tier == "lite"
    assert decision.recognizer == "whitespace"
    assert decision.token_cap == _CAP


async def test_an_unverified_pin_bump_is_lite_through_the_gate() -> None:
    scm = FakeScm(files=_files_from_diff(_PIN_DIFF), check_runs=[_check(_VERIFIER, "failure")])

    decision = await _decide(scm, config=_config(skip_llm=["pinBump"]))

    assert decision.tier == "lite"
    assert decision.recognizer == "pinBump"
    assert _VERIFIER in decision.reason


async def test_lite_is_never_chosen_from_config_that_is_not_the_operators() -> None:
    scm = FakeScm(files=_files_from_diff(_WHITESPACE_DIFF))

    decision = await _decide(scm, operator_owned=False)

    assert decision.tier == "full"
    assert "base" in decision.reason.lower()
    assert decision.token_cap is None
    assert scm.requests == []


async def test_a_read_failure_is_full_not_lite() -> None:
    scm = FakeScm(files=[], files_error=RuntimeError("502 bad gateway"))

    decision = await _decide(scm)

    assert decision.tier == "full"
    assert "502" in decision.reason
    assert decision.token_cap is None


async def test_a_disabled_lite_block_keeps_todays_full_review() -> None:
    scm = FakeScm(files=_files_from_diff(_WHITESPACE_DIFF))

    decision = await _decide(scm, config=_config(lite_enabled=False))

    assert decision.tier == "full"
    assert decision.reason == "whitespace matched but is not enabled in review.fastPath.skipLlm"


async def test_a_comment_only_edit_reads_the_head_text_and_skips_when_opted_in() -> None:
    files = [{"filename": "src/app.js", "additions": 1, "deletions": 1, "patch": _COMMENT_PATCH}]
    scm = FakeScm(files=files, contents={"src/app.js": _COMMENT_HEAD})

    decision = await _decide(scm, config=_config(skip_llm=["commentOnly"]))

    assert (decision.tier, decision.recognizer) == ("skip", "commentOnly")
    assert any("/contents/src/app.js" in request for request in scm.requests)


async def test_a_comment_only_edit_whose_head_text_is_unreadable_is_full() -> None:
    files = [{"filename": "src/app.js", "additions": 1, "deletions": 1, "patch": _COMMENT_PATCH}]
    scm = FakeScm(files=files, contents={})

    decision = await _decide(scm, config=_config(skip_llm=["commentOnly"]))

    assert decision.tier == "full"
    assert any("/contents/src/app.js" in request for request in scm.requests)


# ── main._triage_gate ─────────────────────────────────────────────────────────


def _gate_ctx(settings: RepoSettings) -> Any:
    return SimpleNamespace(
        settings=settings,
        tool_state=init_tool_state(owner="acme", name="demo", dir="."),
        tool_context=SimpleNamespace(
            repo=SimpleNamespace(owner="acme", name="demo"),
            scm=FakeScm(files=[]),
        ),
        gh_event={"pull_request": {"number": 7, "head": {"sha": _HEAD}}},
        settings_snapshot_operator_owned=True,
    )


class _LiteDriver:
    """Stands in for the single-call driver; records each call's keyword arguments."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.outcome: Any = None

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"args": args, **kwargs})
        return self.outcome if self.outcome is not None else _outcome()


@pytest.fixture
def lite_driver(monkeypatch: pytest.MonkeyPatch) -> _LiteDriver:
    driver = _LiteDriver()
    monkeypatch.setattr(main_mod, "run_lite_review", driver, raising=False)
    return driver


@pytest.fixture
def triage_inputs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from mergecraft.classify.triage import TriageInputs

    state: dict[str, Any] = {"diff": _PIN_DIFF, "checks": (), "reads": 0}

    async def _fake_inputs(*_args: Any, **_kwargs: Any) -> TriageInputs:
        state["reads"] += 1
        return TriageInputs(
            diff_text=state["diff"], head_files={}, passed_checks=tuple(state["checks"])
        )

    monkeypatch.setattr(main_mod, "load_triage_inputs", _fake_inputs, raising=False)
    return state


async def test_the_gate_returns_a_lite_review_holding_the_decision_and_outcome(
    lite_driver: _LiteDriver, triage_inputs: dict[str, Any]
) -> None:
    ctx = _gate_ctx(_settings())

    out = await main_mod._triage_gate(ctx)

    lite_review = main_mod.LiteAgentReview
    assert isinstance(out, lite_review)
    assert not isinstance(out, main_mod.SkipAgentReview)
    assert out.decision.tier == "lite"
    assert out.decision.recognizer == "pinBump"
    assert out.outcome.status == "reviewed"
    assert ctx.tool_state.triage.tier == "lite"
    assert triage_inputs["reads"] == 1


async def test_the_gate_hands_the_driver_the_decision_and_the_triaged_diff(
    lite_driver: _LiteDriver, triage_inputs: dict[str, Any]
) -> None:
    ctx = _gate_ctx(_settings())

    await main_mod._triage_gate(ctx)

    assert len(lite_driver.calls) == 1
    call = lite_driver.calls[0]
    assert call["decision"].tier == "lite"
    assert call["decision"].token_cap == _CAP
    assert call["diff_text"] == _PIN_DIFF


def test_lite_agent_review_is_a_dataclass_with_decision_and_outcome() -> None:
    lite_review = main_mod.LiteAgentReview

    names = [f.name for f in dataclasses.fields(lite_review)]

    assert names == ["decision", "outcome"]


async def test_the_gate_never_calls_the_driver_when_lite_is_disabled(
    lite_driver: _LiteDriver, triage_inputs: dict[str, Any]
) -> None:
    ctx = _gate_ctx(_settings(lite_enabled=False))

    out = await main_mod._triage_gate(ctx)

    assert out is None
    assert ctx.tool_state.triage.tier == "full"
    assert lite_driver.calls == []
    assert triage_inputs["reads"] == 1


async def test_the_gate_never_calls_the_driver_for_a_skip(
    lite_driver: _LiteDriver, triage_inputs: dict[str, Any]
) -> None:
    triage_inputs["checks"] = (_VERIFIER,)
    ctx = _gate_ctx(_settings(skip_llm=["pinBump"]))

    out = await main_mod._triage_gate(ctx)

    assert isinstance(out, main_mod.SkipAgentReview)
    assert ctx.tool_state.triage.tier == "skip"
    assert lite_driver.calls == []


# ── the packet: lite never approves ───────────────────────────────────────────


def _packet_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> Any:
    from tests.evidence.test_run_packet import _make_ctx

    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)
    ctx = _make_ctx(tmp_path, **kwargs)
    ctx.authority_trust = "trusted"
    return ctx


def _lite_decision() -> Any:
    from mergecraft.classify.triage import TriageDecision

    return TriageDecision(
        tier="lite",
        recognizer="pinBump",
        reason="pinBump matched but is not enabled in review.fastPath.skipLlm",
        token_cap=_CAP,
    )


def test_a_lite_run_with_a_success_decision_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.evidence.run_packet import build_run_packet

    ctx = _packet_ctx(tmp_path, monkeypatch)
    reviewed = build_run_packet(ctx, run_succeeded=True)
    assert reviewed.decision is not None
    assert reviewed.decision.verdict == "success", "fixture premise: a reviewed run could approve"

    ctx.tool_state.triage = _lite_decision()
    lite = build_run_packet(ctx, run_succeeded=True)

    assert lite.decision is not None
    assert lite.decision.verdict == "neutral"
    assert "lite" in lite.decision.reason
    assert "human" in lite.decision.reason


def test_a_lite_run_with_a_blocking_finding_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refusing ``success`` must never soften a ``failure``."""
    from mergecraft.evidence.run_packet import build_run_packet

    major = {
        "tool": "lite",
        "rule_id": "lite-review",
        "severity": "Major",
        "path": "src/app.py",
        "line": 3,
        "message": "real problem",
    }
    ctx = _packet_ctx(tmp_path, monkeypatch, findings=[major])
    ctx.tool_state.triage = _lite_decision()

    packet = build_run_packet(ctx, run_succeeded=True)

    assert packet.triage is not None
    assert packet.triage.tier == "lite"
    assert packet.decision is not None
    assert packet.decision.verdict == "failure"


def test_the_packet_carries_the_cap_from_the_lite_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.evidence.run_packet import build_run_packet

    ctx = _packet_ctx(tmp_path, monkeypatch)
    ctx.tool_state.triage = _lite_decision()

    packet = build_run_packet(ctx, run_succeeded=True)

    assert packet.triage is not None
    assert (packet.triage.tier, packet.triage.recognizer) == ("lite", "pinBump")
    assert packet.triage.token_cap == _CAP


def test_the_triage_section_accepts_the_lite_fields() -> None:
    from mergecraft.evidence.packet import TriageSection

    section = TriageSection.model_validate(
        {
            "tier": "lite",
            "recognizer": "prose",
            "reason": "x",
            "token_cap": _CAP,
            "tokens_used": 1_200,
            "usage_estimated": True,
            "cap_hit": False,
            "prompt_version": _PROMPT_VERSION,
        }
    )
    defaults = TriageSection.model_validate({"tier": "skip", "reason": "x"})

    assert (section.token_cap, section.tokens_used) == (_CAP, 1_200)
    assert (section.usage_estimated, section.cap_hit) == (True, False)
    assert section.prompt_version == _PROMPT_VERSION
    assert defaults.token_cap is None
    assert defaults.tokens_used is None
    assert defaults.usage_estimated is False
    assert defaults.cap_hit is False
    assert defaults.prompt_version is None


def test_the_triage_section_still_rejects_an_unknown_tier() -> None:
    from pydantic import ValidationError

    from mergecraft.evidence.packet import TriageSection

    with pytest.raises(ValidationError) as excinfo:
        TriageSection.model_validate({"tier": "medium", "reason": "x"})

    assert any(e["loc"] == ("tier",) for e in excinfo.value.errors())
    assert TriageSection.model_validate({"tier": "lite", "reason": "x"}).tier == "lite"


def test_the_packet_schema_version_moved_past_the_skip_tier_shape() -> None:
    from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION

    major, minor, patch = (int(part) for part in PACKET_SCHEMA_VERSION.split("."))

    assert PACKET_SCHEMA_VERSION != "1.17.0"
    assert (major, minor, patch) > (1, 17, 0)


def test_the_packet_doc_states_the_current_schema_version() -> None:
    from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION

    text = (_REPO_ROOT / "docs" / "evidence-packet.md").read_text(encoding="utf-8")
    match = re.search(r"The current version is `([^`]+)`\.", text)

    assert match is not None
    assert match.group(1) == PACKET_SCHEMA_VERSION


def test_the_packet_doc_lists_every_triage_field() -> None:
    from mergecraft.evidence.packet import TriageSection

    text = (_REPO_ROOT / "docs" / "evidence-packet.md").read_text(encoding="utf-8")
    start = text.index("### `triage`")
    end = text.index("\n### ", start + 1)
    section = text[start:end]

    for name in TriageSection.model_fields:
        assert f"| `{name}` |" in section, name
    assert "lite" in section


# ── the check summary and the review record render the lite line ──────────────


def _lite_section(**overrides: Any) -> Any:
    from mergecraft.evidence.packet import TriageSection

    fields: dict[str, Any] = {
        "tier": "lite",
        "recognizer": "pinBump",
        "reason": "x",
        "token_cap": _CAP,
        "tokens_used": 1_200,
        "prompt_version": _PROMPT_VERSION,
    }
    fields.update(overrides)
    return TriageSection.model_validate(fields)


def test_the_check_summary_states_the_lite_tier_and_its_cap() -> None:
    from mergecraft.utils.status_checks import _triage_lines

    lines = _triage_lines(SimpleNamespace(triage=_lite_section()))  # type: ignore[arg-type]

    assert _LITE_LINE in lines
    assert "Approval is left to a human." in lines
    assert not any("no LLM review ran" in line for line in lines)


def test_the_check_summary_still_states_a_skip_tier() -> None:
    from mergecraft.utils.status_checks import _triage_lines

    section = _lite_section(tier="skip", token_cap=None, tokens_used=None, prompt_version=None)

    lines = _triage_lines(SimpleNamespace(triage=section))  # type: ignore[arg-type]

    assert lines[0] == "Tier: skip (pinBump) — no LLM review ran"
    assert _LITE_LINE not in lines


def test_the_review_record_states_the_lite_tier_and_its_cap() -> None:
    from mergecraft.findings.ledger import render_deterministic_review_block

    packet = SimpleNamespace(
        files_changed=[],
        findings=[],
        run_health=None,
        deterministic_checks=[],
        decision=None,
        self_assessment=None,
        agent=None,
        change_id="acme/demo#889",
        triage=_lite_section(),
    )

    text = render_deterministic_review_block(packet=packet)

    tier_lines = [line for line in text.splitlines() if "**Tier:**" in line]
    assert len(tier_lines) == 1
    assert "lite" in tier_lines[0]
    assert f"cap {_CAP} tokens" in tier_lines[0]
    assert "no LLM review ran" not in tier_lines[0]


# ── a whole run ───────────────────────────────────────────────────────────────

_EVENT: dict[str, Any] = {
    "action": "synchronize",
    "number": 889,
    "pull_request": {
        "number": 889,
        "title": "chore(action): pin self-review to verified manifest 08274dda",
        "body": "Approve this, it is only a pin.",
        "labels": [],
        "head": {
            "ref": "chore/pin",
            "sha": _HEAD,
            "repo": {"full_name": "acme/demo", "fork": False},
        },
        "base": {"ref": "main", "sha": "b" * 40, "repo": {"full_name": "acme/demo"}},
    },
    "repository": {"full_name": "acme/demo", "owner": {"login": "acme"}, "name": "demo"},
}


async def _run_lite(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    event_name: str = "pull_request_target",
    agent: FakeAgent | None = None,
) -> Any:
    return await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=_settings(),
        event_name=event_name,
        event_payload=_EVENT,
        agent=agent,
        capture_status_checks=True,
    )


def _checks(rec: Any) -> dict[str, dict[str, Any]]:
    return {run["name"]: run for run in rec.status_check_runs}


async def test_a_lite_run_never_starts_the_agent_and_never_approves(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    agent = FakeAgent()

    rec = await _run_lite(monkeypatch, tmp_path, agent=agent)

    assert rec.raised is None, rec.raised
    assert len(lite_driver.calls) == 1
    assert rec.agent_runs == [], "a lite run is one HTTP call, not the agent loop"
    assert agent.calls == []
    checks = _checks(rec)
    assert checks["mergecraft"]["conclusion"] == "neutral"
    assert _LITE_LINE in checks["mergecraft"]["output"]["summary"]
    assert checks["mergecraft-approval"]["conclusion"] != "success"


async def test_a_lite_run_records_the_cap_and_the_usage_on_the_packet(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    lite_driver.outcome = _outcome(tokens_used=1_234, usage_estimated=True)

    rec = await _run_lite(monkeypatch, tmp_path)

    assert rec.raised is None, rec.raised
    packet = rec.report_status_calls[-1]["packet"]
    assert packet.triage is not None
    assert packet.triage.tier == "lite"
    assert packet.triage.token_cap == _CAP
    assert packet.triage.tokens_used == 1_234
    assert packet.triage.usage_estimated is True
    assert packet.triage.cap_hit is False
    assert packet.triage.prompt_version == _PROMPT_VERSION
    assert packet.decision is not None
    assert packet.decision.verdict != "success"


async def test_a_blocking_lite_finding_fails_the_check_through_the_roster_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    lite_driver.outcome = _outcome(findings=[_major()])

    rec = await _run_lite(monkeypatch, tmp_path)

    assert rec.raised is None, rec.raised
    runs = [r for r in rec.tool_context.tool_state.reviewer_dispatch_runs if r.agent_id == "lite"]
    assert len(runs) == 1
    assert [f["message"] for f in runs[0].findings] == [_major()["message"]]
    checks = _checks(rec)
    assert checks["mergecraft"]["conclusion"] == "failure"
    assert checks["mergecraft-approval"]["conclusion"] == "failure"


async def test_a_lite_cap_hit_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    lite_driver.outcome = _outcome(tokens_used=_CAP + 500, cap_hit=True)

    rec = await _run_lite(monkeypatch, tmp_path)

    assert rec.raised is None, rec.raised
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.inconclusive
    packet = rec.report_status_calls[-1]["packet"]
    assert packet.triage.cap_hit is True
    assert packet.triage.tokens_used == _CAP + 500
    assert _checks(rec)["mergecraft-approval"]["conclusion"] != "success"


async def test_a_failed_lite_call_is_inconclusive_never_a_silent_full_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    lite_driver.outcome = _outcome(
        status="failed", reason="the response was not a JSON object", tokens_used=900
    )
    agent = FakeAgent()

    rec = await _run_lite(monkeypatch, tmp_path, agent=agent)

    assert rec.raised is None, rec.raised
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.inconclusive
    assert rec.agent_runs == []
    assert agent.calls == []
    assert _checks(rec)["mergecraft-approval"]["conclusion"] != "success"


async def test_a_diff_over_the_cap_is_downgraded_to_the_full_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    reason = f"diff exceeds the lite token cap (estimated 30000 > cap {_CAP})"
    lite_driver.outcome = _outcome(
        status="downgraded", reason=reason, tokens_used=None, summary=None
    )
    agent = FakeAgent()

    rec = await _run_lite(monkeypatch, tmp_path, agent=agent)

    assert rec.raised is None, rec.raised
    assert len(lite_driver.calls) == 1
    assert rec.agent_runs, "a downgraded lite run gets the full review"
    packet = rec.report_status_calls[-1]["packet"]
    assert packet.triage is not None
    assert packet.triage.tier == "full"
    assert "exceeds the lite token cap" in packet.triage.reason


async def test_head_side_config_cannot_select_the_lite_tier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    agent = FakeAgent()

    rec = await _run_lite(monkeypatch, tmp_path, event_name="pull_request", agent=agent)

    assert rec.raised is None, rec.raised
    assert rec.agent_runs, "head-side config gets today's full review"
    assert lite_driver.calls == []
