"""Tests for the finding taxonomy and inline-comment fingerprints."""

from __future__ import annotations

import pytest

from mergecraft.review_taxonomy import (
    BODY_ONLY_EFFORT,
    BODY_ONLY_SEVERITY,
    FINDING_CATEGORIES,
    FINDING_EFFORTS,
    FINDING_MARKER_PREFIX,
    FINDING_SEVERITIES,
    finding_fingerprint,
    stamp_finding_fingerprint,
)


def test_taxonomy_axes_are_distinct_and_ordered() -> None:
    assert len(set(FINDING_CATEGORIES)) == len(FINDING_CATEGORIES) == 6
    assert FINDING_SEVERITIES == ("Critical", "Major", "Minor", "Trivial")
    assert FINDING_EFFORTS == ("Quick win", "Heavy lift", "Low value")
    assert BODY_ONLY_SEVERITY in FINDING_SEVERITIES
    assert BODY_ONLY_EFFORT in FINDING_EFFORTS


def test_fingerprint_is_stable_across_whitespace_and_case() -> None:
    a = finding_fingerprint(path="src/app.py", body="Flag persisted before the start is confirmed.")
    b = finding_fingerprint(
        path="src/app.py",
        body="flag persisted   before the start\nis confirmed.",
    )
    assert a == b


def test_fingerprint_varies_by_path_and_content() -> None:
    body = "Flag persisted before the start is confirmed."
    assert finding_fingerprint(path="src/a.py", body=body) != finding_fingerprint(
        path="src/b.py", body=body
    )
    assert finding_fingerprint(path="src/a.py", body=body) != finding_fingerprint(
        path="src/a.py", body="Something else entirely."
    )


def test_stamp_appends_marker_once() -> None:
    stamped = stamp_finding_fingerprint(path="src/app.py", body="A finding.")
    assert stamped.startswith("A finding.")
    assert FINDING_MARKER_PREFIX in stamped
    assert stamp_finding_fingerprint(path="src/app.py", body=stamped) == stamped


def test_stamp_survives_round_trip_fingerprint() -> None:
    body = "A finding."
    stamped = stamp_finding_fingerprint(path="src/app.py", body=body)
    # The marker itself is stripped before hashing, so a stamped body still
    # fingerprints to the value embedded in it.
    assert finding_fingerprint(path="src/app.py", body=body) in stamped
    assert finding_fingerprint(path="src/app.py", body=stamped) == finding_fingerprint(
        path="src/app.py", body=body
    )


def test_stamp_handles_empty_body() -> None:
    stamped = stamp_finding_fingerprint(path="src/app.py", body="")
    assert stamped.startswith(FINDING_MARKER_PREFIX)
    assert "\n" not in stamped


def test_finding_confidences_axis_exists_and_is_pinned() -> None:
    from mergecraft.review_taxonomy import FINDING_CONFIDENCES

    assert FINDING_CONFIDENCES == ("certain", "likely", "possible")
    assert len(set(FINDING_CONFIDENCES)) == 3


@pytest.mark.xfail(reason="green after W7: Review prompt names confidence values", strict=False)
def test_review_prompt_names_every_confidence_value() -> None:
    from mergecraft.modes import PR_SUMMARY_FORMAT
    from mergecraft.review_taxonomy import FINDING_CONFIDENCES

    for value in FINDING_CONFIDENCES:
        assert value in PR_SUMMARY_FORMAT, value
