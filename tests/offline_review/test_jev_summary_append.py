"""#786 — appending the Jev summary section onto an offline review's output."""

from __future__ import annotations

from mergecraft.config.settings import RepoSettings
from mergecraft.offline_review import _append_jev_review_section
from mergecraft.review.offline_result import OfflineReviewResult


def _settings(*, jev_enabled: bool) -> RepoSettings:
    return RepoSettings.model_validate({"jev": {"enabled": jev_enabled}})


def test_disabled_jev_leaves_output_byte_identical() -> None:
    """Hard constraint: disabled must not change the review body at all."""
    original = "## Review\n\nLooks good.\n"
    result = OfflineReviewResult(success=True, output=original)

    appended = _append_jev_review_section(result, settings=_settings(jev_enabled=False))

    assert appended.output == original


def test_no_output_is_a_no_op_even_when_enabled() -> None:
    """A failed/empty review has nothing to attach a section to."""
    result = OfflineReviewResult(success=False, output=None)

    appended = _append_jev_review_section(result, settings=_settings(jev_enabled=True))

    assert appended.output is None


def test_enabled_and_skipped_appends_the_skip_reason() -> None:
    original = "## Review\n\nLooks good.\n"
    result = OfflineReviewResult(success=True, output=original, jev_skip_reason="credential_absent")

    appended = _append_jev_review_section(result, settings=_settings(jev_enabled=True))

    assert appended.output is not None
    assert original.strip() in appended.output
    assert "credential_absent" in appended.output
    assert "advisory" in appended.output.lower()


def test_enabled_and_ran_appends_the_predictions_table() -> None:
    original = "## Review\n\nLooks good.\n"
    result = OfflineReviewResult(
        success=True,
        output=original,
        jev_predictions=[
            {
                "unit_id": "hunk:src/auth.py:abcd1234",
                "lane": "security",
                "choice": "likely",
                "severity": "Major",
                "confidence": 0.82,
            }
        ],
    )

    appended = _append_jev_review_section(result, settings=_settings(jev_enabled=True))

    assert appended.output is not None
    assert "hunk:src/auth.py:abcd1234" in appended.output
    assert "advisory" in appended.output.lower()
