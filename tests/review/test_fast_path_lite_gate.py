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
from tests.review.test_fast_path_whitespace_modes import ModeScm
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


def _settings(*, extra: dict[str, Any] | None = None, **kwargs: Any) -> RepoSettings:
    return RepoSettings.model_validate(
        {"review": {"fastPath": _fast_path(**kwargs)}, **(extra or {})}
    )


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
    scm = ModeScm()

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
    assert decision.reason == "no recognizer matches the whole diff"


async def test_a_comment_only_edit_reads_the_head_text_and_skips_when_opted_in() -> None:
    files = [{"filename": "src/app.ts", "additions": 1, "deletions": 1, "patch": _COMMENT_PATCH}]
    scm = FakeScm(files=files, contents={"src/app.ts": _COMMENT_HEAD})

    decision = await _decide(scm, config=_config(skip_llm=["commentOnly"]))

    assert (decision.tier, decision.recognizer) == ("skip", "commentOnly")
    assert any("/contents/src/app.ts" in request for request in scm.requests)


async def test_a_comment_only_edit_whose_head_text_is_unreadable_is_full() -> None:
    files = [{"filename": "src/app.ts", "additions": 1, "deletions": 1, "patch": _COMMENT_PATCH}]
    scm = FakeScm(files=files, contents={})

    decision = await _decide(scm, config=_config(skip_llm=["commentOnly"]))

    assert decision.tier == "full"
    assert any("/contents/src/app.ts" in request for request in scm.requests)


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


def _compact_major_row() -> dict[str, Any]:
    return {
        "tool": "lite",
        "rule_id": "lite-review",
        "severity": "Major",
        "path": "src/app.py",
        "line": 3,
        "message": "real problem",
    }


def _full_major_row() -> dict[str, Any]:
    from mergecraft.analyzers.finding import make_finding

    row = make_finding(
        tool="review",
        rule_id="agent:real-problem",
        category="Functional Correctness",
        severity="Major",
        confidence="likely",
        message="real problem",
        path="src/app.py",
        start_line=3,
        end_line=3,
        source="agent",
    ).model_dump(mode="json")
    assert isinstance(row, dict)
    return row


@pytest.mark.parametrize(
    "make_row", [_compact_major_row, _full_major_row], ids=["compact-lite-row", "full-finding-row"]
)
def test_a_lite_run_with_a_blocking_finding_still_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_row: Any
) -> None:
    """Refusing ``success`` must never soften a ``failure``, whatever shape the finding has."""
    from mergecraft.evidence.run_packet import build_run_packet

    ctx = _packet_ctx(tmp_path, monkeypatch, findings=[make_row()])
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
    settings: RepoSettings | None = None,
) -> Any:
    return await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=settings if settings is not None else _settings(),
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


async def test_a_blocking_lite_finding_fails_the_check_through_the_packet_findings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    """The compact lite rows are expanded into packet findings, which the gate reads."""
    lite_driver.outcome = _outcome(findings=[_major()])

    rec = await _run_lite(monkeypatch, tmp_path)

    assert rec.raised is None, rec.raised
    packet = rec.report_status_calls[-1]["packet"]
    lite_findings = [f for f in packet.findings if f.tool == "lite"]
    assert [(f.severity, f.path, f.message) for f in lite_findings] == [
        ("Major", _major()["path"], _major()["message"])
    ]
    checks = _checks(rec)
    assert checks["mergecraft"]["conclusion"] == "failure"
    assert checks["mergecraft-approval"]["conclusion"] == "failure"


async def test_lite_findings_are_recorded_on_the_roster_under_agent_lite(
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


# ── the lite record is published as a COMMENT review ──────────────────────────


class _Publication:
    """Spies on ``main.publish_deterministic_record`` and the review it creates."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.created: list[dict[str, Any]] = []
        self.updated: list[str] = []


@pytest.fixture
def publication(monkeypatch: pytest.MonkeyPatch) -> _Publication:
    from mergecraft.scm.github import GitHubScmAdapter

    spy = _Publication()
    real = main_mod.publish_deterministic_record

    async def _publish(**kwargs: Any) -> Any:
        spy.calls.append(kwargs)
        return await real(**kwargs)

    async def _create_review(
        _self: Any, _owner: str, _repo: str, _pull: int, **fields: Any
    ) -> dict[str, Any]:
        spy.created.append(fields)
        return {"id": 4242, "node_id": "PRR_lite"}

    async def _update_review(
        _self: Any, _owner: str, _repo: str, _pull: int, _review_id: int, body: str
    ) -> dict[str, Any]:
        spy.updated.append(body)
        return {"id": _review_id}

    monkeypatch.setattr(main_mod, "publish_deterministic_record", _publish)
    monkeypatch.setattr(GitHubScmAdapter, "create_review", _create_review)
    monkeypatch.setattr(GitHubScmAdapter, "update_review", _update_review)
    return spy


def _published_body(spy: _Publication) -> str:
    assert len(spy.calls) == 1, "a lite run publishes exactly one deterministic record"
    assert len(spy.created) == 1
    assert spy.created[0].get("event") == "COMMENT"
    body = spy.created[0].get("body")
    assert isinstance(body, str)
    return body


async def test_a_clean_lite_run_publishes_its_summary_as_a_comment_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
    publication: _Publication,
) -> None:
    lite_driver.outcome = _outcome(summary="LITE-SUMMARY-0 nothing stands out in the pin")

    rec = await _run_lite(monkeypatch, tmp_path)

    assert rec.raised is None, rec.raised
    body = _published_body(publication)
    assert "LITE-SUMMARY-0 nothing stands out in the pin" in body
    assert "lite" in body
    assert "cheapo/tiny-1" in body, "the record names the lite provider/model slug"
    assert "**Provider:** `claude`" not in body
    assert "(unresolved)" not in body


async def test_a_blocking_lite_run_publishes_each_finding_location_and_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
    publication: _Publication,
) -> None:
    major = _major()
    lite_driver.outcome = _outcome(
        findings=[major], summary="LITE-SUMMARY-1 one blocker in the workflow"
    )

    rec = await _run_lite(monkeypatch, tmp_path)

    assert rec.raised is None, rec.raised
    body = _published_body(publication)
    assert "LITE-SUMMARY-1 one blocker in the workflow" in body
    assert major["message"] in body
    location = re.escape(major["path"]) + r"\D{0,12}" + str(major["line"]) + r"\b"
    assert re.search(location, body), "the record names the finding's path and line"


async def test_a_failed_completion_check_never_says_the_run_finished_successfully(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    lite_driver.outcome = _outcome(findings=[_major()])

    rec = await _run_lite(monkeypatch, tmp_path)

    assert rec.raised is None, rec.raised
    completion = _checks(rec)["mergecraft"]
    assert completion["conclusion"] == "failure"
    assert _LITE_LINE in completion["output"]["summary"]
    assert "finished successfully" not in completion["output"]["summary"]


# ── trust, caps and blockers ──────────────────────────────────────────────────


async def test_a_trusted_lite_run_with_a_minor_finding_never_approves(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    """``trust.selfReview: full`` reaches the trusted tier; lite still cannot approve."""
    minor = {**_major(), "severity": "Minor", "message": "LITE-MINOR consider a comment"}
    lite_driver.outcome = _outcome(findings=[minor])
    settings = _settings(extra={"trust": {"selfReview": "full"}})

    rec = await _run_lite(monkeypatch, tmp_path, settings=settings)

    assert rec.raised is None, rec.raised
    assert rec.tool_context.tool_state.authority_trust == "trusted", "premise: trusted tier"
    checks = _checks(rec)
    assert checks["mergecraft-approval"]["conclusion"] != "success"
    assert checks["mergecraft"]["conclusion"] == "neutral"


async def test_a_blocker_is_never_softened_by_a_cap_hit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    lite_driver: _LiteDriver,
    triage_inputs: dict[str, Any],
) -> None:
    lite_driver.outcome = _outcome(findings=[_major()], tokens_used=_CAP + 10, cap_hit=True)

    rec = await _run_lite(monkeypatch, tmp_path)

    assert rec.raised is None, rec.raised
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.inconclusive
    checks = _checks(rec)
    assert checks["mergecraft"]["conclusion"] == "failure"
    assert checks["mergecraft-approval"]["conclusion"] == "failure"


# ── head text is read only when something can use it ──────────────────────────


def _comment_files() -> list[dict[str, Any]]:
    return [{"filename": "src/app.ts", "additions": 1, "deletions": 1, "patch": _COMMENT_PATCH}]


async def test_code_head_text_is_not_read_when_neither_comment_only_nor_lite_is_on() -> None:
    scm = FakeScm(files=_comment_files(), contents={"src/app.ts": _COMMENT_HEAD})

    decision = await _decide(scm, config=_config(lite_enabled=False, skip_llm=["prose"]))

    assert decision.tier == "full"
    assert scm.requests, "premise: the files listing was read"
    assert not any("/contents/src/app.ts" in request for request in scm.requests)


async def test_code_head_text_is_read_when_lite_is_enabled() -> None:
    scm = FakeScm(files=_comment_files(), contents={"src/app.ts": _COMMENT_HEAD})

    decision = await _decide(scm, config=_config(lite_enabled=True, skip_llm=[]))

    assert (decision.tier, decision.recognizer) == ("lite", "commentOnly")
    assert any("/contents/src/app.ts" in request for request in scm.requests)


async def test_code_head_text_is_read_when_comment_only_is_opted_in_without_lite() -> None:
    scm = FakeScm(files=_comment_files(), contents={"src/app.ts": _COMMENT_HEAD})

    decision = await _decide(scm, config=_config(lite_enabled=False, skip_llm=["commentOnly"]))

    assert (decision.tier, decision.recognizer) == ("skip", "commentOnly")
    assert any("/contents/src/app.ts" in request for request in scm.requests)


async def test_prose_head_text_is_still_read_without_comment_only_or_lite() -> None:
    files = [
        {
            "filename": "README.md",
            "additions": 1,
            "deletions": 1,
            "patch": "@@ -1,3 +1,3 @@\n # Title\n-Old words.\n+New words.\n More.\n",
        }
    ]
    scm = FakeScm(files=files, contents={"README.md": "# Title\nNew words.\nMore.\n"})

    decision = await _decide(scm, config=_config(lite_enabled=False, skip_llm=["prose"]))

    assert (decision.tier, decision.recognizer) == ("skip", "prose")
    assert any("/contents/README.md" in request for request in scm.requests)


# ── operator docs name the closed list and the record format ──────────────────


def test_review_checks_lists_exactly_the_recognised_comment_only_suffixes() -> None:
    from mergecraft.classify.triage import COMMENT_ONLY_SUFFIXES

    text = (_REPO_ROOT / "docs" / "REVIEW-CHECKS.md").read_text(encoding="utf-8")
    match = re.search(r"`//`-comment languages — `([^`]+)`", text)

    assert match is not None
    listed = match.group(1).split()
    assert sorted(listed) == sorted(COMMENT_ONLY_SUFFIXES)
    assert set(listed) == {
        ".ts",
        ".go",
        ".java",
        ".kt",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".swift",
    }


def test_the_changelog_records_the_finding_line_format_under_changed() -> None:
    text = (_REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = text.split("## [0.1.0a5]", 1)[1].split("\n## [", 1)[0]
    changed = unreleased.split("### Changed", 1)[1].split("\n### ", 1)[0]

    assert "path:line" in changed


def _comment_only_paragraph() -> str:
    text = (_REPO_ROOT / "docs" / "REVIEW-CHECKS.md").read_text(encoding="utf-8")
    start = text.index("`commentOnly` (")
    end = text.index("A mixed diff matches nothing", start)
    return text[start:end]


def test_review_checks_names_the_excluded_languages_and_why() -> None:
    paragraph = _comment_only_paragraph()
    listed = re.search(r"`//`-comment languages — `([^`]+)`", paragraph)
    assert listed is not None
    outside_list = paragraph.replace(listed.group(0), "")

    for excluded in ("`.js`", "`.jsx`", "`.tsx`", "Rust", "_test.go"):
        assert excluded in outside_list, excluded
    assert "JSX" in outside_list


def test_review_checks_says_comments_can_still_carry_tool_directives() -> None:
    paragraph = " ".join(_comment_only_paragraph().split())

    assert "tool directives" in paragraph
    assert "runtime" in paragraph
    assert "best-effort" in paragraph or "best effort" in paragraph
