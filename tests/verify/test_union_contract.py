"""Every input and output field from issues 61, 62, and 63 exists on the models."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.verify.support import (
    INPUT_UNION_FIELDS,
    OUTPUT_UNION_FIELDS,
    SAMPLE_YAML_INPUT,
    V2_XFAIL,
    import_verify,
    make_input,
    model_has_dotted_field,
    require_symbol,
)


@V2_XFAIL
@pytest.mark.parametrize(("field_path", "issues"), INPUT_UNION_FIELDS)
def test_input_covers_union_field(field_path: str, issues: str) -> None:
    """Each named input field from the three-issue union exists on the input model."""
    del issues
    models = import_verify("models")
    input_cls = require_symbol(models, "VerificationInput")
    assert model_has_dotted_field(input_cls, field_path), field_path
    spec = make_input()
    head = field_path.split(".", maxsplit=1)[0]
    assert getattr(spec, head, None) is not None or field_path == "yaml_input"


@V2_XFAIL
@pytest.mark.parametrize(("field_path", "issues"), OUTPUT_UNION_FIELDS)
def test_report_covers_union_field(field_path: str, issues: str) -> None:
    """Each named output field from the three-issue union exists on the report model."""
    del issues
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")
    assert model_has_dotted_field(report_cls, field_path), field_path


@V2_XFAIL
def test_yaml_input_loads_union_fields(tmp_path: Path) -> None:
    """Issue 62's YAML shape populates the same input model as the flags."""
    models = import_verify("models")
    loader = require_symbol(models, "load_verification_input")
    path = tmp_path / "spec.yaml"
    path.write_text(SAMPLE_YAML_INPUT, encoding="utf-8")
    spec = loader(path)
    assert spec.mode == "verify"
    assert spec.base_url == "http://127.0.0.1:8765"
    assert spec.auth.strategy == "env"
    assert spec.viewport.width == 1280
    assert spec.viewport.height == 720
    assert SECRET_FROM_YAML in spec.credential_env_names


SECRET_FROM_YAML = "APP_TEST_PASSWORD"
