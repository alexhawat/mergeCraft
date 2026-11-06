"""Normalization follows input occurrences, not a many-to-one prose fingerprint."""

from __future__ import annotations

from itertools import permutations
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.verifier import AgentFinding
from mergecraft.findings.agent_adapter import normalize_agent_findings_via_pipeline

if TYPE_CHECKING:
    from pathlib import Path

_BODY = "The retry loop loses requests after reconnect."


def _row(line: int, severity: str, fingerprint: str) -> AgentFinding:
    return AgentFinding(
        path="src/app.py",
        line=line,
        severity=severity,
        body=_BODY,
        fingerprint=fingerprint,
        raised_by=f"lens-{line}",
    )


def _value(row: Any, name: str) -> Any:
    return row[name] if isinstance(row, dict) else getattr(row, name)


@pytest.mark.parametrize("dedupe", [False, True])
@pytest.mark.parametrize("wire", [False, True])
def test_distinct_positions_and_supplied_fingerprints_survive_reordering(
    dedupe: bool,
    wire: bool,
) -> None:
    rows = [_row(10, "Minor", "first-model-id"), _row(90, "Major", "second-model-id")]
    for ordering in permutations(rows):
        inputs = [row.model_dump() if wire else row for row in ordering]
        result = normalize_agent_findings_via_pipeline(inputs, rule_id="test", dedupe=dedupe)
        assert [
            (
                _value(row, "line"),
                _value(row, "severity"),
                _value(row, "fingerprint"),
                _value(row, "raised_by"),
            )
            for row in result
        ] == [
            (90, "Major", "second-model-id", "lens-90"),
            (10, "Minor", "first-model-id", "lens-10"),
        ]
        if not dedupe:
            assert all(isinstance(row, dict) == wire for row in result)


@pytest.mark.parametrize("dedupe", [False, True])
def test_equal_position_rows_map_back_to_their_own_severity_source(dedupe: bool) -> None:
    minor = _row(10, "Minor", "minor-model-id")
    major = _row(10, "Major", "major-model-id")
    for ordering in permutations([minor, major]):
        result = normalize_agent_findings_via_pipeline(
            list(ordering), rule_id="test", dedupe=dedupe
        )
        expected = [("Major", "major-model-id")]
        if not dedupe:
            expected.append(("Minor", "minor-model-id"))
        assert [(row.severity, row.fingerprint) for row in result] == expected


@pytest.mark.parametrize("dedupe", [False, True])
def test_memory_filter_between_occurrences_keeps_input_mapping(
    tmp_path: Path, dedupe: bool
) -> None:
    from mergecraft.findings.agent_adapter import agent_finding_to_finding
    from mergecraft.utils.memory import FeedbackOutcome, record_finding_feedback
    from tests.memory.support import feedback_store_path

    dismissed = AgentFinding(path="src/app.py", line=50, severity="Major", body="Stale warning")
    record_finding_feedback(
        store_path=feedback_store_path(tmp_path),
        fingerprint=agent_finding_to_finding(dismissed, rule_id="test").fingerprint,
        outcome=FeedbackOutcome.DISMISSED,
        reason="Already resolved",
        pr_number=7,
    )
    inputs = [
        _row(10, "Minor", "first-model-id"),
        dismissed.model_dump(),
        _row(90, "Major", "second-model-id").model_dump(),
    ]
    result = normalize_agent_findings_via_pipeline(
        inputs,
        rule_id="test",
        dedupe=dedupe,
        repo_root=tmp_path,
    )
    assert [(_value(row, "line"), _value(row, "fingerprint")) for row in result] == [
        (90, "second-model-id"),
        (10, "first-model-id"),
    ]
    if not dedupe:
        assert isinstance(result[0], dict)
        assert isinstance(result[1], AgentFinding)


def test_genuine_duplicate_still_collapses_at_dedupe_boundary() -> None:
    finding = _row(10, "Major", "same-model-id")
    assert (
        len(normalize_agent_findings_via_pipeline([finding, finding], rule_id="test", dedupe=False))
        == 2
    )
    assert (
        len(normalize_agent_findings_via_pipeline([finding, finding], rule_id="test", dedupe=True))
        == 1
    )
