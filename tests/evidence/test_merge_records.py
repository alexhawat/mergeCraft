"""Malformed serialized findings remain visible to downstream validation."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.evidence.merge import merge_finding_records, typed_findings_from_rows_with_drops
from tests.findings.support import make_finding


@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("bad_evidence", [None, 42, {"bad": "mapping"}, [42]])
def test_malformed_evidence_cannot_win_or_crash_a_merge(
    inline: bool,
    bad_evidence: Any,
) -> None:
    valid = make_finding(severity="Minor").model_dump()
    invalid = {**valid, "severity": "Critical", "evidence": bad_evidence}
    records = [{"finding": row} if inline else row for row in [invalid, valid]]

    merged = merge_finding_records(records, inline=inline)

    assert len(merged) == 2
    rows = [record["finding"] if inline else record for record in merged]
    assert invalid in rows
    findings, drops = typed_findings_from_rows_with_drops(rows)
    assert drops == 1
    assert [finding.severity for finding in findings] == ["Minor"]


def test_incomplete_stronger_record_does_not_replace_a_valid_copy() -> None:
    valid = make_finding(severity="Minor").model_dump()
    invalid = {**valid, "severity": "Critical"}
    del invalid["path"]
    merged = merge_finding_records([invalid, valid])
    findings, drops = typed_findings_from_rows_with_drops(merged)
    assert drops == 1
    assert [finding.severity for finding in findings] == ["Minor"]
