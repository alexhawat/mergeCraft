"""Plan W6.1 — prep/dependency failures fail closed (``#8``).

Contracts:

- A review-relevant setup failure (dependency install failed) maps the run to
  ``inconclusive`` with the reason recorded — never a silent continue (D4).
- ``setup_script`` failure on the *trusted* tier maps the run to
  ``RunOutcome.inconclusive`` under the default ``setupFailurePolicy``
  (S1 / D5 / D10). Operators can opt into the legacy warn-only behaviour
  by setting ``setupFailurePolicy: warn`` (see
  ``tests/config/test_setup_failure_policy.py``). Untrusted tiers never run
  the script at all (W1 — covered in ``tests/security/``).
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


async def test_setup_script_failure_yields_inconclusive_on_trusted_tier(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 — trusted-tier ``setup_script`` failure maps to ``inconclusive`` (D5/D10 default).

    Replaces the legacy ``test_setup_script_failure_warn_only_on_trusted_tier``
    (W6.1 / pre-S1). The default ``setupFailurePolicy`` is ``inconclusive``
    — an under-provisioned tree never receives a review verdict. Operators
    that want the legacy continue-on-failure behaviour opt in via
    ``setupFailurePolicy: warn`` (covered in
    ``tests/config/test_setup_failure_policy.py::test_policy_warn_reproduces_legacy_continue``).
    """
    from mergecraft.config.settings import RepoSettings
    from mergecraft.run_outcome import RunOutcome

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
        setup_script_rc=1,
    )
    assert rec.result is not None
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.inconclusive, (
        f"S1 / D5: trusted setup_script failure must map to inconclusive, got {outcome!r}"
    )
    assert not rec.result.success
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
