"""J1.4 — bucketing, ordering, residual policy, no skip path (D3, D5, D7)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.jev.support import import_jev, load_transport_body


def _policy() -> Any:
    return import_jev("policy")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, "certain"),
        (0.9, "certain"),
        (0.8999, "likely"),
        (0.6, "likely"),
        (0.5999, "possible"),
        (0.5, "possible"),
        (0.0, "possible"),
    ],
    ids=["1.0", "0.9", "0.8999", "0.6", "0.5999", "0.5", "0.0"],
)
def test_bucket_confidence_at_every_band_boundary(value: float, expected: str) -> None:
    assert _policy().bucket_confidence(value) == expected


def test_bucket_confidence_rejects_none() -> None:
    with pytest.raises(_policy().JevError) as exc_info:
        _policy().bucket_confidence(None)
    assert exc_info.value.code == "invalid_confidence"


def test_bucket_confidence_rejects_out_of_range() -> None:
    policy = _policy()
    with pytest.raises(policy.JevError) as exc_info:
        policy.bucket_confidence(1.01)
    assert exc_info.value.code == "invalid_confidence"
    with pytest.raises(policy.JevError) as exc_info:
        policy.bucket_confidence(-0.01)
    assert exc_info.value.code == "invalid_confidence"


def test_order_units_by_choice_then_confidence_then_severity() -> None:
    policy = _policy()
    types = import_jev("types")
    units = [
        types.UnitAssessment(
            unit_id="clean-high",
            choice="clean",
            confidence=0.99,
            severity_score=0.0,
        ),
        types.UnitAssessment(
            unit_id="defective-low",
            choice="defective",
            confidence=0.61,
            severity_score=2.0,
        ),
        types.UnitAssessment(
            unit_id="defective-high",
            choice="defective",
            confidence=0.91,
            severity_score=2.0,
        ),
        types.UnitAssessment(
            unit_id="defective-critical",
            choice="defective",
            confidence=0.91,
            severity_score=3.0,
        ),
        types.UnitAssessment(
            unit_id="suspicious",
            choice="suspicious",
            confidence=0.80,
            severity_score=2.0,
        ),
    ]
    ordered = policy.order_units(units)
    assert [item.unit_id for item in ordered] == [
        "defective-critical",
        "defective-high",
        "defective-low",
        "suspicious",
        "clean-high",
    ]


def test_high_confidence_clean_does_not_skip_reviewer() -> None:
    policy = _policy()
    types = import_jev("types")
    assessment = types.UnitAssessment(
        unit_id="clean-unit",
        choice="clean",
        confidence=0.99,
        severity_score=0.0,
        severity="Trivial",
    )
    prediction = policy.predict_jev_action(assessment, trust_tier="trusted")
    assert prediction.skip_reviewer is False
    assert prediction.suppressed is False
    assert prediction.action != "skip_reviewer"
    assert prediction.action != "suppress"


def test_predict_never_lowers_severity_below_prior() -> None:
    policy = _policy()
    types = import_jev("types")
    prior = types.PolicyVerdict(
        choice="defective",
        confidence=0.91,
        severity="Critical",
        severity_score=3.0,
    )
    incoming = types.PolicyVerdict(
        choice="clean",
        confidence=0.97,
        severity="Trivial",
        severity_score=0.0,
    )
    prediction = policy.predict_jev_action(
        incoming,
        trust_tier="trusted",
        prior=prior,
    )
    assert prediction.severity == "Critical"
    assert prediction.severity_score >= 3.0
    assert prediction.suppressed is False


def test_parse_unit_assessment_from_recorded_answers() -> None:
    policy = _policy()
    body = load_transport_body("unit_happy.json")
    assessment = policy.assessment_from_response(body)
    assert assessment.choice == "defective"
    assert assessment.confidence == 0.92
    assert assessment.severity == "Critical"
    assert assessment.severity_score == 3.0
    assert policy.bucket_confidence(assessment.confidence) == "certain"


def test_predict_jev_action_honors_shadow_gate_mode() -> None:
    """F-GATE-DISCARD: ``GatesSettings.jev`` default ``shadow`` is applied; enforced stays false."""
    from mergecraft.config.settings import default_settings

    assert default_settings().gates.jev == "shadow"
    policy = _policy()
    types = import_jev("types")
    assessment = types.UnitAssessment(
        unit_id="unit-1",
        choice="defective",
        confidence=0.92,
        severity="Critical",
        severity_score=3.0,
        pack_id="unit/v1",
    )
    prediction = policy.predict_jev_action(assessment, trust_tier="trusted")
    assert prediction.enforced is False
    assert prediction.skip_reviewer is False
    assert prediction.metadata.get("gate_mode") == "shadow"


def test_predict_jev_action_stays_unenforced_when_gate_set_to_enforce(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-GATE-DISCARD / D6: mode is applied, but this plan never flips ``enforced``."""
    from mergecraft.config.settings import default_settings

    base = default_settings()
    configured = base.model_copy(update={"gates": base.gates.model_copy(update={"jev": "enforce"})})
    monkeypatch.setattr("mergecraft.config.settings.default_settings", lambda: configured)
    policy = _policy()
    types = import_jev("types")
    assessment = types.UnitAssessment(
        unit_id="unit-1",
        choice="defective",
        confidence=0.92,
        severity="Critical",
        severity_score=3.0,
        pack_id="unit/v1",
    )
    prediction = policy.predict_jev_action(assessment, trust_tier="trusted")
    assert prediction.enforced is False
    assert prediction.metadata.get("gate_mode") == "enforce"


def test_bucket_confidence_reads_configured_unit_thresholds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-UNIT-THRESHOLDS: changing ``unit/v1.certain`` / ``unit/v1.likely`` moves the bucket."""
    from mergecraft.config.settings import default_settings

    base = default_settings()
    configured = base.model_copy(
        update={
            "jev": base.jev.model_copy(
                update={
                    "thresholds": {
                        **dict(base.jev.thresholds),
                        "unit/v1.certain": 0.95,
                        "unit/v1.likely": 0.75,
                    }
                }
            )
        }
    )
    monkeypatch.setattr("mergecraft.config.settings.default_settings", lambda: configured)
    policy = _policy()
    assert policy.bucket_confidence(0.92) == "likely"
    assert policy.bucket_confidence(0.95) == "certain"
    assert policy.bucket_confidence(0.7499) == "possible"
    assert policy.bucket_confidence(0.75) == "likely"


def test_iter_thresholds_unit_floors_follow_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-UNIT-THRESHOLDS: ``iter_thresholds`` reads the same config keys as bucketing."""
    from mergecraft.config.settings import default_settings

    base = default_settings()
    configured = base.model_copy(
        update={
            "jev": base.jev.model_copy(
                update={
                    "thresholds": {
                        **dict(base.jev.thresholds),
                        "unit/v1.certain": 0.95,
                        "unit/v1.likely": 0.75,
                    }
                }
            )
        }
    )
    monkeypatch.setattr("mergecraft.config.settings.default_settings", lambda: configured)
    values = {(item.pack_id, item.name): item.value for item in _policy().iter_thresholds()}
    assert values[("unit/v1", "certain")] == 0.95
    assert values[("unit/v1", "likely")] == 0.75
