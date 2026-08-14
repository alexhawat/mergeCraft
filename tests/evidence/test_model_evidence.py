"""Plan W10 — model evidence in the packet + fallback policy (``#20``).

Contracts:

- W10.2: the packet's agent metadata records requested model, executed model,
  provider, and fallback index/occurrence **unconditionally** (not only via
  opt-in tracing).
- W10.1: ``allow_fallback: false`` on ``RepoSettings`` refuses to advance the
  model chain; an unavailable primary is a ``configuration_error``.
- W10.3: a fallback emits a structured warning visible to operators.

Interpretation pinned for the impl wave (recorded in
``docs/dev/test-plans/production-readiness.md``): the fields land on
``AgentMetadata`` as ``requested_model`` / ``executed_model`` / ``provider`` /
``fallback_index`` / ``fallback_occurred``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from loguru import logger

from mergecraft.evidence.run_packet import emit_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

_DIFF = """\
diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-old
+new
"""


def _make_ctx(tmp_path: Path, *, resolved_model: str | None = "claude-sonnet-4-5") -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    diff_path = tmp_path / "pr-7.diff"
    diff_path.write_text(_DIFF, encoding="utf-8")
    primary_repo_state(tool_state).diff_path = str(diff_path)
    tool_state.model = resolved_model
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        resolved_model=resolved_model,
    )


def _emit(tmp_path: Path, **kwargs: Any) -> dict[str, Any]:
    written = emit_run_packet(_make_ctx(tmp_path, **kwargs), run_succeeded=True)
    assert written is not None
    return json.loads(written.read_text(encoding="utf-8"))


def test_packet_agent_metadata_records_requested_vs_executed_model(tmp_path: Path) -> None:
    """W10.2 — the packet proves which model actually ran vs. was requested."""
    packet = _emit(tmp_path)
    agent = packet["agent"]
    assert agent["requested_model"], "requested_model missing from packet agent metadata"
    assert agent["executed_model"] == "claude-sonnet-4-5"
    assert agent["provider"], "provider missing from packet agent metadata"


def test_packet_agent_metadata_records_fallback_fields(tmp_path: Path) -> None:
    """W10.2 — fallback index/occurrence are always present (not opt-in)."""
    packet = _emit(tmp_path)
    agent = packet["agent"]
    assert "fallback_index" in agent, "fallback_index missing — evidence is opt-in only"
    assert "fallback_occurred" in agent
    assert agent["fallback_occurred"] is False
    assert agent["fallback_index"] == 0


def test_agent_metadata_rejects_unknown_keys_still() -> None:
    """Guard — W10 fields are accepted; the schema stays closed to unknowns.

    Fails if anyone loosens ``extra`` forbid on ``AgentMetadata``.
    """
    from pydantic import ValidationError

    from mergecraft.evidence.packet import AgentMetadata

    with pytest.raises(ValidationError):
        AgentMetadata.model_validate(
            {
                "id": "claude",
                "version": "1.0",
                "model": "m",
                "requested_model": "m",
                "executed_model": "m",
                "provider": "anthropic",
                "fallback_index": 0,
                "fallback_occurred": False,
                "totally_made_up": True,
            }
        )


async def test_allow_fallback_false_refuses_chain_advance() -> None:
    """W10.1 — ``allow_fallback: false`` turns an unavailable primary into a
    configuration error instead of silently reviewing with a different model.
    """
    from mergecraft.agents.shared import AgentResult
    from mergecraft.config.settings import RepoSettings
    from mergecraft.utils.agent_resolve import ModelFallbackPolicyError, run_with_model_chain

    settings = RepoSettings.model_validate(
        {"models": ["anthropic/claude-opus", "openai/gpt-5"], "allow_fallback": False}
    )
    assert settings.allow_fallback is False, (
        "allow_fallback silently dropped — the policy knob does not exist (W10.1)"
    )
    calls: list[str] = []

    async def _failing_primary(slug: str) -> AgentResult:
        calls.append(slug)
        return AgentResult(
            success=False, error="provider unavailable", metadata={"retryable": True}
        )

    with pytest.raises(ModelFallbackPolicyError, match=r"(?i)configuration|fallback"):
        await run_with_model_chain(settings=settings, run_once=_failing_primary)
    assert calls == ["anthropic/claude-opus"], (
        f"chain advanced despite allow_fallback=false: {calls}"
    )


async def test_fallback_emits_structured_warning() -> None:
    """W10.3 — an actual chain advance logs a structured, operator-visible warning."""
    from mergecraft.agents.shared import AgentResult
    from mergecraft.config.settings import RepoSettings
    from mergecraft.utils.agent_resolve import run_with_model_chain

    settings = RepoSettings.model_validate({"models": ["anthropic/claude-opus", "openai/gpt-5"]})

    async def _flaky(slug: str) -> AgentResult:
        if slug == "anthropic/claude-opus":
            return AgentResult(
                success=False, error="429 rate limited", metadata={"retryable": True}
            )
        return AgentResult(success=True, output="reviewed")

    records: list[Any] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="WARNING")
    try:
        winner, result = await run_with_model_chain(settings=settings, run_once=_flaky)
    finally:
        logger.remove(sink_id)
    assert result.success
    assert winner == "openai/gpt-5"
    fallback_warnings = [
        r
        for r in records
        if r["level"].name == "WARNING" and "fallback" in str(r["message"]).lower()
    ]
    assert fallback_warnings, (
        f"fallback happened silently — messages: {[str(r['message']) for r in records]}"
    )


def test_model_fallback_policy_error_is_runtime_error_naming_policy() -> None:
    """Direct ``ModelFallbackPolicyError`` — subclass + message contract (W10.1)."""
    from mergecraft.utils.agent_resolve import ModelFallbackPolicyError

    assert issubclass(ModelFallbackPolicyError, RuntimeError)
    err = ModelFallbackPolicyError(
        "configuration error: allow_fallback is false and primary model unavailable"
    )
    assert "configuration" in str(err).lower()
    assert "fallback" in str(err).lower()


def test_attach_model_evidence_stamps_metadata_fields() -> None:
    """Direct ``_attach_model_evidence`` — stamps packet-facing metadata (W10.2)."""
    from mergecraft.agents.shared import AgentResult
    from mergecraft.utils.agent_resolve import _attach_model_evidence

    result = AgentResult(success=True, output="ok", metadata={"retryable": False})
    stamped = _attach_model_evidence(
        result,
        requested_model="anthropic/claude-opus",
        executed_model="openai/gpt-5",
        fallback_index=1,
    )
    assert stamped is result
    meta = stamped.metadata
    assert meta["requested_model"] == "anthropic/claude-opus"
    assert meta["executed_model"] == "openai/gpt-5"
    assert meta["provider"] == "openai"
    assert meta["fallback_index"] == 1
    assert meta["fallback_occurred"] is True
    assert meta["retryable"] is False


def test_attach_model_evidence_primary_has_no_fallback_flag() -> None:
    """Direct ``_attach_model_evidence`` — index 0 means no fallback occurred."""
    from mergecraft.agents.shared import AgentResult
    from mergecraft.utils.agent_resolve import _attach_model_evidence

    stamped = _attach_model_evidence(
        AgentResult(success=True),
        requested_model="anthropic/claude-opus",
        executed_model="anthropic/claude-opus",
        fallback_index=0,
    )
    assert stamped.metadata["fallback_index"] == 0
    assert stamped.metadata["fallback_occurred"] is False
    assert stamped.metadata["provider"] == "anthropic"


@pytest.mark.parametrize(
    ("executed", "requested", "agent_id", "expected"),
    [
        ("anthropic/claude-opus", "anthropic/claude-opus", "claude", "anthropic"),
        ("(unresolved)", "openai/gpt-5", "claude", "openai"),
        ("(unresolved)", "(unresolved)", "claude", "claude"),
        ("(unresolved)", "", "", "unknown"),
    ],
)
def test_provider_for_model_evidence_resolves_label(
    executed: str, requested: str, agent_id: str, expected: str
) -> None:
    """Direct ``_provider_for_model_evidence`` — catalog → agent_id → unknown (W10.2)."""
    from mergecraft.evidence.run_packet import _provider_for_model_evidence

    assert (
        _provider_for_model_evidence(
            executed_model=executed,
            requested_model=requested,
            agent_id=agent_id,
        )
        == expected
    )
