"""RED — pipeline predicate validation (AG6 / MCB-29)."""

from __future__ import annotations

import pytest

from mergecraft.orchestrator.pipeline import PipelineValidationError, validate_predicate

pytestmark = pytest.mark.xfail(
    reason="green after AG6: delete predicate blocklist",
    strict=False,
)


def test_path_containing_subprocess_is_accepted() -> None:
    validate_predicate("changed_paths matches 'vendor/subprocess/run.py'")


def test_path_containing_import_is_accepted() -> None:
    validate_predicate("changed_paths matches 'tools/import_helper/**'")


def test_code_is_still_inexpressible() -> None:
    with pytest.raises(PipelineValidationError):
        validate_predicate("eval('1')")
    with pytest.raises(PipelineValidationError):
        validate_predicate("os.system('id')")


def test_error_message_lists_all_five_allowed_forms() -> None:
    try:
        validate_predicate("totally invalid predicate")
    except PipelineValidationError as exc:
        message = str(exc)
        for fragment in (
            "changed_paths matches",
            "risk_band >=",
            "languages includes",
            "analyzer_findings.severity >=",
            "decision.",
        ):
            assert fragment in message
    else:
        pytest.fail("expected PipelineValidationError")
