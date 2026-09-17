"""Report JSON Schema is derived from Pydantic models and version-pinned."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from tests.verify.support import (
    PINNED_ARTIFACT_FIELDS,
    PINNED_INPUT_FIELDS,
    PINNED_REPORT_FIELDS,
    PINNED_SCHEMA_VERSION,
    import_verify,
    make_report,
    require_symbol,
    sample_report_payload,
)


def test_report_schema_is_derived_from_models() -> None:
    """``verification_report_schema()`` matches ``VerificationReport.model_json_schema()``."""
    models = import_verify("models")
    schema_fn = require_symbol(models, "verification_report_schema")
    report_cls = require_symbol(models, "VerificationReport")
    derived = schema_fn()
    direct = report_cls.model_json_schema()
    assert isinstance(derived, dict)
    assert derived.get("type") == "object"
    assert derived == direct or derived.get("properties") == direct.get("properties")


def test_report_round_trips() -> None:
    """A fully populated report serializes and re-validates, including unicode."""
    report = make_report(observed="清除按钮未移除图片")
    dumped = report.model_dump_json()
    json.loads(dumped)
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")
    restored = report_cls.model_validate_json(dumped)
    assert restored.observed == "清除按钮未移除图片"
    assert restored.model_dump() == report.model_dump()


def test_report_rejects_unknown_fields() -> None:
    """``extra="forbid"`` rejects keys that are not on the report model."""
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")
    payload = sample_report_payload()
    payload["not_a_contract_field"] = True
    with pytest.raises(ValidationError) as exc_info:
        report_cls.model_validate(payload)
    assert "not_a_contract_field" in str(exc_info.value)


def test_input_rejects_unknown_fields() -> None:
    """Input model also forbids extras so YAML cannot smuggle unknown keys."""
    models = import_verify("models")
    input_cls = require_symbol(models, "VerificationInput")
    from tests.verify.support import sample_input_payload

    payload = sample_input_payload()
    payload["unexpected_yaml_key"] = "nope"
    with pytest.raises(ValidationError) as exc_info:
        input_cls.model_validate(payload)
    assert "unexpected_yaml_key" in str(exc_info.value)


def test_report_requires_schema_version() -> None:
    """``schema_version`` is required — omitting it is invalid."""
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")
    payload = sample_report_payload()
    del payload["schema_version"]
    with pytest.raises(ValidationError) as exc_info:
        report_cls.model_validate(payload)
    assert "schema_version" in str(exc_info.value)
    assert report_cls.model_fields["schema_version"].is_required() is True


def test_report_schema_version_is_pinned() -> None:
    """Field-set drift without a version bump fails this pin."""
    models = import_verify("models")
    version = require_symbol(models, "VERIFICATION_SCHEMA_VERSION")
    report_cls = require_symbol(models, "VerificationReport")
    input_cls = require_symbol(models, "VerificationInput")
    artifacts_cls = require_symbol(models, "ReportArtifacts")
    assert version == PINNED_SCHEMA_VERSION
    assert version.count(".") == 2
    assert set(report_cls.model_fields) == PINNED_REPORT_FIELDS
    assert set(input_cls.model_fields) == PINNED_INPUT_FIELDS
    assert set(artifacts_cls.model_fields) == PINNED_ARTIFACT_FIELDS


def test_artifacts_video_and_trace_are_nullable() -> None:
    """Video is unused in v1; trace is nullable (present when the driver is free)."""
    report = make_report()
    assert report.artifacts.video is None
    assert report.artifacts.trace is None
    with_trace = make_report(
        artifacts={
            "screenshots": ["shot.png"],
            "video": None,
            "trace": "trace.zip",
            "logs": [],
            "network_summary": None,
        }
    )
    assert with_trace.artifacts.trace == "trace.zip"
    assert with_trace.artifacts.video is None
