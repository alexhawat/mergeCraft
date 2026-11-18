"""Action risk grading with the real Jev client and a recorded transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.support.publication import APP_DIFF, RecordingReviewGitHub, publication_ctx

from mergecraft.action.review_pull import _resolve_run_risk_grade
from mergecraft.action.review_state import RunContext
from mergecraft.config.settings import JevSettings, RepoSettings, RiskSettings
from mergecraft.evidence.run_packet import build_run_packet
from mergecraft.jev.client import AsyncJevClient
from mergecraft.jev.types import NoulAnswer, SystemOneResponse

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.config.settings import TrustTier


class _RiskTransport:
    """Capture the outbound state and questions without any network call."""

    def __init__(self) -> None:
        self.calls = 0
        self.last_model: str | None = None
        self.state: dict[str, Any] = {}
        self.questions: dict[str, Any] = {}

    async def system_one(
        self, *, state: dict[str, Any], questions: dict[str, Any], model: str
    ) -> SystemOneResponse:
        """Return a recorded affirmative risk answer."""
        self.calls += 1
        self.last_model = model
        self.state = state
        self.questions = questions
        return SystemOneResponse(model=model, answers={"authz": NoulAnswer(noul=0.9)})


@pytest.mark.asyncio
@pytest.mark.parametrize("trust_tier", ["trusted", "untrusted"], ids=("trusted", "untrusted"))
async def test_action_risk_grade_passes_resolved_trust_to_jev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trust_tier: TrustTier
) -> None:
    """Exercise review context, resolver, client fencing and the packet in one run."""
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier=trust_tier)
    settings = RepoSettings(risk=RiskSettings(mode="jev"), jev=JevSettings(enabled=True))
    run = RunContext(
        settings=settings,
        tool_state=ctx.tool_state,
        tool_context=ctx,
        trust_tier=trust_tier,
        settings_snapshot_operator_owned=True,
    )
    transport = _RiskTransport()
    client = AsyncJevClient(api_key="test-jev-key", settings=settings.jev, transport=transport)
    monkeypatch.setattr("mergecraft.evidence.risk_resolve.AsyncJevClient", lambda **_: client)

    await _resolve_run_risk_grade(run)
    packet = build_run_packet(ctx, run_succeeded=True)

    assert transport.calls == 1
    assert set(transport.state) == {"diff"}
    if trust_tier == "untrusted":
        assert "tier=untrusted trust=untrusted" in transport.state["diff"]
        assert "field=jev.risk/v1.diff" in transport.state["diff"]
        assert APP_DIFF in transport.state["diff"]
    else:
        assert transport.state["diff"] == APP_DIFF
    assert set(transport.questions) == {"authz", "data_loss", "flag_enabled", "secrets"}
    assert all(question["type"] == "noul" for question in transport.questions.values())
    assert packet.blast_radius == ctx.tool_state.risk_classification
    assert packet.blast_radius is not None
    assert packet.blast_radius.lane == "high"
    assert "jev.authz" in {reason.code for reason in packet.blast_radius.reasons}


@pytest.mark.asyncio
async def test_jev_credential_absence_preserves_action_deterministic_grade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The credential gate leaves the base-derived grade in the real packet."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    ctx = publication_ctx(tmp_path, github=RecordingReviewGitHub(), trust_tier="untrusted")
    settings = RepoSettings(jev=JevSettings(enabled=True))
    run = RunContext(
        settings=settings,
        tool_state=ctx.tool_state,
        tool_context=ctx,
        settings_snapshot_operator_owned=True,
    )
    await _resolve_run_risk_grade(run)
    deterministic = ctx.tool_state.risk_classification
    assert deterministic is not None

    ctx.tool_state.risk_classification = None
    ctx.tool_state.risk_settings = RiskSettings(mode="jev")
    await _resolve_run_risk_grade(run)
    packet = build_run_packet(ctx, run_succeeded=True)

    grade = packet.blast_radius
    assert grade is not None
    assert grade.lane == deterministic.lane
    assert grade.reason == deterministic.reason
    assert grade.reasons[:-1] == deterministic.reasons
    assert grade.reasons[-1].code == "jev.credential.absent"
