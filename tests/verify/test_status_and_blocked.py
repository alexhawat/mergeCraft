"""Closed status vocabularies and first-class ``blocked`` that names the gap."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from tests.verify.support import (
    CRITERION_STATUSES,
    REPRODUCE_STATUSES,
    VERIFY_STATUSES,
    import_verify,
    make_blocked_report,
    make_report,
    require_symbol,
    sample_report_payload,
)


def test_status_vocabulary_is_closed() -> None:
    """Verify, reproduce, and per-criterion statuses are closed sets."""
    models = import_verify("models")
    assert require_symbol(models, "VERIFY_STATUSES") == VERIFY_STATUSES
    assert require_symbol(models, "REPRODUCE_STATUSES") == REPRODUCE_STATUSES
    assert require_symbol(models, "CRITERION_STATUSES") == CRITERION_STATUSES


@pytest.mark.parametrize("status", sorted(VERIFY_STATUSES))
def test_verify_status_members_are_accepted(status: str) -> None:
    report = make_report(mode="verify", status=status, blocked=_blocked_if(status))
    assert report.status == status


@pytest.mark.parametrize("status", sorted(REPRODUCE_STATUSES))
def test_reproduce_status_members_are_accepted(status: str) -> None:
    report = make_report(mode="reproduce", status=status, blocked=_blocked_if(status))
    assert report.status == status


def test_verify_rejects_reproduce_only_status() -> None:
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")
    payload = sample_report_payload(mode="verify", status="reproduced")
    with pytest.raises(ValidationError):
        report_cls.model_validate(payload)


def test_reproduce_rejects_verify_only_status() -> None:
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")
    payload = sample_report_payload(mode="reproduce", status="pass")
    with pytest.raises(ValidationError):
        report_cls.model_validate(payload)


def test_unknown_status_is_rejected() -> None:
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")
    payload = sample_report_payload(status="success")
    with pytest.raises(ValidationError):
        report_cls.model_validate(payload)


def test_criterion_rejects_unknown_status() -> None:
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")
    payload = sample_report_payload()
    payload["acceptance_criteria"] = [
        {
            "id": "c1",
            "text": "works",
            "status": "skipped",
            "evidence": [],
        }
    ]
    with pytest.raises(ValidationError):
        report_cls.model_validate(payload)


def test_blocked_report_with_empty_missing_is_invalid() -> None:
    """A blocked report must name what is missing — empty is invalid."""
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")
    payload = sample_report_payload(status="blocked", blocked={"missing": []})
    with pytest.raises(ValidationError) as exc_info:
        report_cls.model_validate(payload)
    assert "missing" in str(exc_info.value).lower()


def test_blocked_report_without_blocked_object_is_invalid() -> None:
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")
    payload = sample_report_payload(status="blocked", blocked=None)
    with pytest.raises(ValidationError):
        report_cls.model_validate(payload)


def test_blocked_is_not_a_pass() -> None:
    """``blocked`` never maps to a successful outcome."""
    models = import_verify("models")
    is_successful = require_symbol(models, "is_successful")
    report = make_blocked_report(missing=["startup_command"])
    assert report.status == "blocked"
    assert report.status not in {"pass", "reproduced"}
    assert is_successful(report) is False


@pytest.mark.parametrize("status", ["fail", "partial", "skipped", "not_reproduced", "blocked"])
def test_non_success_statuses_are_not_successful(status: str) -> None:
    models = import_verify("models")
    is_successful = require_symbol(models, "is_successful")
    mode = "reproduce" if status in REPRODUCE_STATUSES and status != "partial" else "verify"
    if status == "partial":
        mode = "verify"
    if status == "not_reproduced":
        mode = "reproduce"
    report = make_report(mode=mode, status=status, blocked=_blocked_if(status))
    assert is_successful(report) is False


def _blocked_if(status: str) -> dict[str, list[str]] | None:
    if status == "blocked":
        return {"missing": ["fixture-input"]}
    return None
