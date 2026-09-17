"""J1.4 — one-way ratchet on untrusted tiers (D5). Guard-deletion test."""

from __future__ import annotations

from typing import Any

from tests.jev.support import import_jev, load_transport_body


def _policy() -> Any:
    return import_jev("policy")


def _types() -> Any:
    return import_jev("types")


def _prior_defective() -> Any:
    return _types().PolicyVerdict(
        choice="defective",
        confidence=0.91,
        severity="Critical",
        severity_score=3.0,
    )


def _steered_clean() -> Any:
    return _policy().assessment_from_response(load_transport_body("unit_steering_clean.json"))


def test_steering_payload_cannot_move_untrusted_verdict_downward() -> None:
    """Guard-deletion: identity ``apply_ratchet`` must fail this test (D5)."""
    policy = _policy()
    prior = _prior_defective()
    incoming = _steered_clean()
    result = policy.apply_ratchet(
        prior=prior,
        incoming=incoming,
        trust_tier="untrusted",
    )
    assert result.choice == "defective"
    assert result.severity == "Critical"
    assert result.severity_score >= prior.severity_score
    assert result.discarded_deescalation is True
    assert result.concluded_clean is False
    assert result.skip_reviewer is False
    assert result.suppressed is False
    assert (result.choice, result.severity_score) != (
        incoming.choice,
        incoming.severity_score,
    )


def test_untrusted_clean_cannot_be_concluded_without_prior() -> None:
    policy = _policy()
    incoming = _steered_clean()
    result = policy.apply_ratchet(
        prior=None,
        incoming=incoming,
        trust_tier="untrusted",
    )
    assert result.concluded_clean is False
    assert result.skip_reviewer is False
    assert result.suppressed is False
    assert result.cleared is False
    assert result.choice != "clean"


def test_untrusted_escalation_is_kept() -> None:
    policy = _policy()
    types = _types()
    prior = types.PolicyVerdict(
        choice="suspicious",
        confidence=0.70,
        severity="Minor",
        severity_score=1.0,
    )
    incoming = types.PolicyVerdict(
        choice="defective",
        confidence=0.92,
        severity="Critical",
        severity_score=3.0,
    )
    result = policy.apply_ratchet(
        prior=prior,
        incoming=incoming,
        trust_tier="untrusted",
    )
    assert result.choice == "defective"
    assert result.severity == "Critical"
    assert result.discarded_deescalation is False


def test_ratchet_records_discarded_steering_on_untrusted() -> None:
    policy = _policy()
    result = policy.apply_ratchet(
        prior=_prior_defective(),
        incoming=_steered_clean(),
        trust_tier="untrusted",
    )
    assert result.recorded is True
    assert result.discarded_deescalation is True
    assert result.trust_tier == "untrusted"
