"""VP3 shadow suite — terminal-verdict protocol (D6).

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP3.1 RED,
VP3.2 impl; xfail markers cleared after VP3.2).

Pinned contracts (W0):
    **D6** — reuse ``evidence/shadow.py`` (``record_shadow_prediction``,
    ``disagree_with_outcome``). Do not invent a second shadow log.
    **Convention 5** — same module as the gate-action recorder; the
    verdict-protocol predicate sits *alongside* ``predict_action``.
    Shadow mode records the new protocol's decision beside the legacy
    outcome; enforce mode is when the VP2 ``_classify_outcome`` branch
    actually fires.

House style matches ``tests/evidence/test_gate_actions.py``: helpers at
the top, one behaviour per test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.agents.shared import AgentResult
from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.evidence.packet import MergeEvidencePacket

_POLICY_ID = "verdict-protocol"
_MISSING_VERDICT_REASON = "no terminal review verdict was submitted for this attempt"


# ── helpers ──────────────────────────────────────────────────────────────────


def _packet(**overrides: Any) -> MergeEvidencePacket:
    """Minimal packet so ``record_shadow_prediction`` keeps its existing signature."""
    from mergecraft.evidence.packet import (
        PACKET_SCHEMA_VERSION,
        AgentMetadata,
        MergeEvidencePacket,
    )

    base: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "change_id": "acme/demo#42",
        "agent": AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        "files_changed": [],
        "findings": [],
        "deterministic_checks": [],
        "self_assessment": None,
        "decision": None,
        "blast_radius": None,
        "trajectory": None,
        "evals": None,
    }
    base.update(overrides)
    return MergeEvidencePacket(**base)


def _missing_verdict_result() -> AgentResult:
    """Provider success, no terminal submission — the VP2 / VP3 core case."""
    return AgentResult(success=True, output="LGTM", terminal_submission_received=False)


def _present_verdict_result() -> AgentResult:
    """A usable terminal verdict is on the result."""
    return AgentResult(
        success=True,
        output="reviewed",
        terminal_submission_received=True,
        terminal_submission_id="sub-1",
        diagnostics={"attempt_id": 0},
    )


def _classify(
    result: AgentResult,
    *,
    verdict_protocol: str,
    mode: str = "Review",
    final_summary_written: bool = False,
) -> tuple[RunOutcome, str | None]:
    """Drive the real ``_classify_outcome`` with the VP3 protocol-mode kwarg."""
    from mergecraft.main_outcome import _classify_outcome

    outcome, reason = _classify_outcome(
        result=result,
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode=mode,
        verdict_protocol=verdict_protocol,
        final_summary_written=final_summary_written,
    )
    return outcome, reason


def _prediction_outcome(prediction: Any) -> Any:
    if hasattr(prediction, "outcome"):
        return prediction.outcome
    if hasattr(prediction, "predicted_outcome"):
        return prediction.predicted_outcome
    if isinstance(prediction, dict):
        return prediction.get("outcome") or prediction.get("predicted_outcome")
    msg = f"unsupported verdict-protocol prediction shape: {type(prediction).__name__}"
    raise TypeError(msg)


def _prediction_diagnostic(prediction: Any) -> Any:
    if hasattr(prediction, "diagnostic"):
        return prediction.diagnostic
    if isinstance(prediction, dict):
        return prediction.get("diagnostic")
    msg = f"unsupported verdict-protocol prediction shape: {type(prediction).__name__}"
    raise TypeError(msg)


def _row_diagnostic(row: Any) -> Any:
    """Read the closed diagnostic off a shadow row, regardless of field name."""
    for attr in ("diagnostic", "verdict_diagnostic"):
        if hasattr(row, attr):
            value = getattr(row, attr)
            if value is not None:
                return value
    if isinstance(row, dict):
        return row.get("diagnostic") or row.get("verdict_diagnostic")
    dumped = row.model_dump() if hasattr(row, "model_dump") else None
    if isinstance(dumped, dict):
        return dumped.get("diagnostic") or dumped.get("verdict_diagnostic")
    return None


def _as_outcome(value: Any) -> RunOutcome:
    if isinstance(value, RunOutcome):
        return value
    return RunOutcome(str(value))


# ── D6 — shadow records without changing the legacy outcome ───────────────────


def test_shadow_records_prediction_without_changing_outcome(tmp_path: Path) -> None:
    """Shadow on, missing terminal verdict: legacy outcome unchanged, a row is written.

    Pre-VP2, provider success reported ``passed``. VP3 shadow mode must keep
    that legacy outcome while ``predict_verdict_protocol`` records the new
    protocol's prediction (``inconclusive`` / missing-verdict diagnostic)
    through the existing ``record_shadow_prediction`` writer (D6).
    """
    from mergecraft.config.settings import default_settings
    from mergecraft.evidence.shadow import (
        VerdictProtocolPrediction,
        predict_verdict_protocol,
        record_shadow_prediction,
    )
    from mergecraft.mcp.verdict import VerdictDiagnostic

    assert default_settings().gates.terminal_verdict == "shadow"

    result = _missing_verdict_result()
    outcome, _reason = _classify(result, verdict_protocol="shadow")
    assert outcome is RunOutcome.passed, (
        f"shadow mode must leave the legacy outcome unchanged, got {outcome!r}"
    )

    prediction = predict_verdict_protocol(result, mode="Review")
    assert isinstance(prediction, VerdictProtocolPrediction)
    assert _as_outcome(_prediction_outcome(prediction)) is RunOutcome.inconclusive
    diagnostic = _prediction_diagnostic(prediction)
    assert diagnostic == VerdictDiagnostic.provider_success_without_submission or (
        str(diagnostic) == VerdictDiagnostic.provider_success_without_submission.value
    )

    target = tmp_path / "shadow.jsonl"
    row = record_shadow_prediction(
        _packet(),
        change_id="acme/demo#42",
        run_id="run-1",
        policy_id=_POLICY_ID,
        output_path=target,
        prediction=prediction,
        actual_outcome=str(outcome),
    )
    assert target.is_file(), "shadow recorder did not write to disk"
    assert target.read_text(encoding="utf-8").strip(), "shadow record is empty"
    row_outcome = (
        _prediction_outcome(row)
        if hasattr(row, "outcome") or hasattr(row, "predicted_outcome")
        else _prediction_outcome(prediction)
    )
    assert _as_outcome(row_outcome) is RunOutcome.inconclusive
    assert _row_diagnostic(row) is not None
    assert getattr(row, "lane", None) == "review"


def test_shadow_records_agreement_when_verdict_present(tmp_path: Path) -> None:
    """Both decisions agree when a terminal verdict is present; the row says so."""
    from mergecraft.evidence.shadow import (
        disagree_with_outcome,
        predict_verdict_protocol,
        record_shadow_prediction,
    )
    from mergecraft.mcp.verdict import VerdictDiagnostic

    result = _present_verdict_result()
    outcome, reason = _classify(result, verdict_protocol="shadow")
    assert outcome is RunOutcome.passed
    assert reason is None

    prediction = predict_verdict_protocol(result, mode="Review")
    predicted = _as_outcome(_prediction_outcome(prediction))
    assert predicted is RunOutcome.passed
    diagnostic = _prediction_diagnostic(prediction)
    assert diagnostic == VerdictDiagnostic.approved or str(diagnostic) == (
        VerdictDiagnostic.approved.value
    )

    target = tmp_path / "shadow.jsonl"
    row = record_shadow_prediction(
        _packet(),
        change_id="acme/demo#42",
        run_id="run-2",
        policy_id=_POLICY_ID,
        output_path=target,
        prediction=prediction,
        actual_outcome=str(outcome),
    )
    disagreement = getattr(row, "disagreement", None)
    if disagreement is None:
        dumped = row.model_dump() if hasattr(row, "model_dump") else {}
        disagreement = dumped.get("disagreement") if isinstance(dumped, dict) else None
    if disagreement is None:
        report = disagree_with_outcome(
            predicted_action=str(predicted),
            actual_outcome=str(outcome),
            predicted_lane="review",
            predicted_rule_id=str(_prediction_diagnostic(prediction)),
            repo_area=_POLICY_ID,
        )
        disagreement = report["disagreement"]
    assert disagreement is False


def test_shadow_row_carries_diagnostic_code(tmp_path: Path) -> None:
    """The closed ``VerdictDiagnostic`` value is on the shadow row."""
    from mergecraft.evidence.shadow import predict_verdict_protocol, record_shadow_prediction
    from mergecraft.mcp.verdict import VerdictDiagnostic

    result = _missing_verdict_result()
    prediction = predict_verdict_protocol(result, mode="Review")
    target = tmp_path / "shadow.jsonl"
    row = record_shadow_prediction(
        _packet(),
        change_id="acme/demo#42",
        run_id="run-3",
        policy_id=_POLICY_ID,
        output_path=target,
        prediction=prediction,
        actual_outcome=str(RunOutcome.passed),
    )
    code = _row_diagnostic(row)
    assert code is not None, "shadow row is missing the VerdictDiagnostic"
    assert code == VerdictDiagnostic.provider_success_without_submission or (
        str(code) == VerdictDiagnostic.provider_success_without_submission.value
    )


def test_enforce_mode_changes_the_outcome() -> None:
    """With enforce on, the VP2 ``_classify_outcome`` branch fires.

    Missing verdict → ``RunOutcome.inconclusive`` with the VP2 reason.
    """
    from mergecraft.config.settings import RepoSettings
    from mergecraft.evidence.shadow import predict_verdict_protocol

    settings = RepoSettings.model_validate({"gates": {"terminal_verdict": "enforce"}})
    assert settings.gates.terminal_verdict == "enforce"

    result = _missing_verdict_result()
    outcome, reason = _classify(result, verdict_protocol="enforce")
    assert outcome is RunOutcome.inconclusive
    assert reason == _MISSING_VERDICT_REASON

    prediction = predict_verdict_protocol(result, mode="Review")
    assert _as_outcome(_prediction_outcome(prediction)) is RunOutcome.inconclusive


def test_disagreement_is_queryable() -> None:
    """``disagree_with_outcome`` surfaces shadow-vs-actual mismatches (D6).

    Predicted ``inconclusive`` (new protocol) against an actual legacy
    ``passed`` is a disagreement. Deleting the verdict-protocol mapping
    and folding both onto a generic "review" direction would hide it.
    """
    from mergecraft.evidence.shadow import disagree_with_outcome

    # Drive the real comparer first: protocol outcomes must not collapse onto
    # a generic "review" direction (today's merge/block/review mapping would).
    rows = disagree_with_outcome(
        predicted_action=str(RunOutcome.inconclusive),
        actual_outcome=str(RunOutcome.passed),
        predicted_lane="review",
        predicted_rule_id="provider_success_without_submission",
        repo_area=_POLICY_ID,
    )
    assert rows["predicted_action"] == str(RunOutcome.inconclusive)
    assert rows["actual_outcome"] == str(RunOutcome.passed)
    assert rows["disagreement"] is True

    agree = disagree_with_outcome(
        predicted_action=str(RunOutcome.passed),
        actual_outcome=str(RunOutcome.passed),
        predicted_lane="review",
        predicted_rule_id="approved",
        repo_area=_POLICY_ID,
    )
    assert agree["disagreement"] is False

    from mergecraft.evidence.shadow import predict_verdict_protocol
    from mergecraft.mcp.verdict import VerdictDiagnostic

    result = _missing_verdict_result()
    prediction = predict_verdict_protocol(result, mode="Review")
    predicted = str(_as_outcome(_prediction_outcome(prediction)))
    diagnostic = str(_prediction_diagnostic(prediction))
    assert diagnostic in {
        VerdictDiagnostic.provider_success_without_submission.value,
        str(VerdictDiagnostic.provider_success_without_submission),
    }
    assert predicted == str(RunOutcome.inconclusive)


def test_predictor_matches_enforce_for_incremental_progress() -> None:
    """IncrementalReview + ``final_summary_written`` is complete under enforce and shadow."""
    from mergecraft.evidence.shadow import predict_verdict_protocol
    from mergecraft.mcp.verdict import VerdictDiagnostic

    result = _missing_verdict_result()
    outcome, reason = _classify(
        result,
        verdict_protocol="enforce",
        mode="IncrementalReview",
        final_summary_written=True,
    )
    assert outcome is RunOutcome.passed
    assert reason is None

    prediction = predict_verdict_protocol(
        result,
        mode="IncrementalReview",
        final_summary_written=True,
    )
    assert _as_outcome(_prediction_outcome(prediction)) is RunOutcome.passed
    diagnostic = _prediction_diagnostic(prediction)
    assert diagnostic == VerdictDiagnostic.approved or (
        str(diagnostic) == VerdictDiagnostic.approved.value
    )


def test_predictor_mirrors_setup_and_prep_branches() -> None:
    """Setup/prep failures must not be predicted as a missing-verdict inconclusive."""
    from mergecraft.evidence.shadow import predict_verdict_protocol

    result = _present_verdict_result()
    failed = predict_verdict_protocol(
        result,
        mode="Review",
        setup_reason="setup script failed",
        setup_policy="fail",
    )
    assert _as_outcome(_prediction_outcome(failed)) is RunOutcome.configuration_error

    prep = predict_verdict_protocol(
        result,
        mode="Review",
        prep_reason="dependency installation failed",
    )
    assert _as_outcome(_prediction_outcome(prep)) is RunOutcome.inconclusive


def test_verdict_protocol_publish_records_only_in_shadow_mode() -> None:
    """The live finalize helper predicts always and records only under shadow."""
    from mergecraft.main_outcome import _verdict_protocol_publish
    from mergecraft.mcp.verdict import VerdictDiagnostic

    result = _missing_verdict_result()
    attrs, prediction = _verdict_protocol_publish(
        result=result,
        mode="Review",
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        final_summary_written=False,
        terminal_verdict="shadow",
    )
    assert prediction is not None
    assert _as_outcome(_prediction_outcome(prediction)) is RunOutcome.inconclusive
    assert attrs.get("verdict.diagnostic") == (
        VerdictDiagnostic.provider_success_without_submission.value
    )

    _enforce_attrs, enforce_prediction = _verdict_protocol_publish(
        result=result,
        mode="Review",
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        final_summary_written=False,
        terminal_verdict="enforce",
    )
    assert enforce_prediction is None
