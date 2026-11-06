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


@pytest.mark.parametrize("inline", [False, True])
def test_merged_occurrences_keep_first_seen_positions(inline: bool) -> None:
    first = make_finding(path="z.py", severity="Minor", evidence=["first"]).model_dump()
    second = make_finding(path="a.py", severity="Major").model_dump()
    stronger = {**first, "severity": "Critical", "evidence": ["second"]}
    invalid = {"malformed": "must remain visible in place"}
    records = [first, invalid, second, stronger]
    wrapped = [{"finding": row} if inline else row for row in records]

    merged = merge_finding_records(wrapped, inline=inline)
    rows = [row["finding"] if inline else row for row in merged]

    assert [row.get("path") for row in rows] == ["z.py", None, "a.py"]
    assert rows[0]["severity"] == "Critical"
    assert rows[0]["evidence"] == ["first", "second"]
    assert rows[1] == invalid
    assert merge_finding_records(merged, inline=inline) == merged
