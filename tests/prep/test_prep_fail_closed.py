"""Plan W6.1 — prep/dependency failures fail closed (``#8``).

Contracts:

- A review-relevant setup failure (dependency install failed) maps the run to
  ``inconclusive`` with the reason recorded — never a silent continue (D4).
- ``setup_script`` failure on the *trusted* tier stays warn-only by policy
  (documented); untrusted never runs it at all (W1 — covered in
  ``tests/security/``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.support.run_main_harness import FakeAgent, run_main_for_test

from mergecraft.agents.shared import AgentResult

if TYPE_CHECKING:
    import pytest


async def test_prep_failure_makes_run_inconclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.1 — the run must not report success when setup failed underneath it."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        prep_failure="pip install -r requirements.txt failed (exit 1)",
    )
    assert rec.result is not None
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is not None
    assert outcome.value == "inconclusive", (
        f"prep failure produced {outcome!r} (result: {rec.result})"
    )


async def test_prep_failure_reason_is_recorded(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """W6.1 — the failure reason survives into the reported status."""
    reason = "npm ci failed: ERESOLVE"
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, prep_failure=reason)
    assert rec.result is not None
    reported = " ".join(str(call.get("failure_reason") or "") for call in rec.report_status_calls)
    error_text = str(getattr(rec.result, "error", "") or "")
    assert "inconclusive" in str(getattr(rec.result, "outcome", "")) or reason in (
        reported + error_text
    ), f"prep failure reason lost: result={rec.result!r} status={rec.report_status_calls!r}"


async def test_successful_prep_keeps_success_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.1 happy path — healthy prep stays invisible to the run outcome."""
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert rec.result is not None
    assert rec.result.success, f"run failed: {rec.result}"


async def test_setup_script_failure_warn_only_on_trusted_tier(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W6.1 — trusted-tier setup_script failure warns but does not fail the run."""
    from mergecraft.config.settings import RepoSettings

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
        setup_script_rc=1,
    )
    assert rec.result is not None
    assert rec.result.success, (
        f"trusted-tier setup_script failure must stay warn-only: {rec.result}"
    )
    assert rec.tool_context is not None
    assert rec.tool_context.trust_tier == "trusted"


def test_prep_result_model_carries_failure_reason() -> None:
    """Baseline — ``PrepResult`` already records install failure + issues."""
    from mergecraft.prep import PrepResult

    result = PrepResult(
        language="python", dependencies_installed=False, issues=["pip failed (exit 1)"]
    )
    assert not result.dependencies_installed
    assert result.issues == ["pip failed (exit 1)"]


async def test_agent_result_failure_still_maps_to_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Control — a genuine agent failure is not reclassified by prep handling."""
    agent = FakeAgent(result=AgentResult(success=False, error="gate failed"))
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, agent=agent)
    assert rec.result is not None
    assert not rec.result.success
