"""CB #451 RED — pure Hunk comment exporter (D3).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-c-findings-cli-wave-plan.md``
Implementation wave: **CB**. Pins ``Finding[] -> {"comments":[...]}`` field mapping,
file-level drop default, and the ban on ``hunkNumber`` fallbacks.
"""

from __future__ import annotations

import re

import pytest

from tests.findings.support_hunk_export import (
    export_hunk_comments,
    require_attr,
    sample_file_level_finding,
    sample_line_finding,
)

_LOCATION_KEYS = frozenset({"hunk", "hunkNumber", "oldLine", "newLine"})


def _comment_location_keys(comment: dict[str, object]) -> set[str]:
    return {key for key in _LOCATION_KEYS if key in comment}


def test_export_hunk_comments_returns_comments_envelope() -> None:
    """Happy — exporter returns the Hunk stdin envelope."""
    payload = export_hunk_comments([sample_line_finding()])
    assert set(payload) == {"comments"}
    assert isinstance(payload["comments"], list)


def test_export_hunk_comment_maps_finding_fields_to_golden_shape() -> None:
    """D3 / #451 — path, line, summary, rationale, and author map per issue table."""
    finding = sample_line_finding()
    payload = export_hunk_comments([finding])
    assert len(payload["comments"]) == 1
    comment = payload["comments"][0]

    assert comment["filePath"] == finding.path
    assert comment["newLine"] == finding.start_line
    assert comment["author"] == "mergeCraft"
    assert _comment_location_keys(comment) == {"newLine"}

    summary = str(comment["summary"])
    assert finding.rule_id in summary
    assert finding.severity in summary
    assert finding.confidence in summary

    rationale = str(comment["rationale"])
    assert finding.message in rationale
    assert finding.remediation in rationale
    for item in finding.evidence:
        assert item in rationale


def test_export_hunk_comment_never_emits_hunk_number_fallback() -> None:
    """D3 — never invent ``hunkNumber: 1`` (or any hunk/oldLine anchor) for file-level gaps."""
    line_payload = export_hunk_comments([sample_line_finding()])
    file_payload = export_hunk_comments(
        [sample_file_level_finding(), sample_line_finding(path="other.py", start_line=9)],
        file_findings="first-changed-line",
        first_changed_lines={"README.md": 1},
    )
    for comment in [*line_payload["comments"], *file_payload["comments"]]:
        assert "hunkNumber" not in comment
        assert "hunk" not in comment
        assert "oldLine" not in comment
        assert _comment_location_keys(comment) == {"newLine"}


def test_export_hunk_drops_file_level_findings_by_default() -> None:
    """D3 — ``--hunk-file-findings drop`` (default) omits ``start_line is None`` findings."""
    payload = export_hunk_comments(
        [sample_file_level_finding(path="README.md"), sample_line_finding()],
    )
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["filePath"] == "src/demo.py"


def test_export_hunk_first_changed_line_maps_file_level_with_prefix() -> None:
    """Opt-in ``first-changed-line`` anchors file-level findings on the first changed line."""
    payload = export_hunk_comments(
        [sample_file_level_finding(path="README.md")],
        file_findings="first-changed-line",
        first_changed_lines={"README.md": 12},
    )
    comment = payload["comments"][0]
    assert comment["filePath"] == "README.md"
    assert comment["newLine"] == 12
    assert str(comment["summary"]).startswith("[file-level]")


def test_export_hunk_empty_findings_returns_empty_comments() -> None:
    """Edge — no findings yields an empty comments array."""
    payload = export_hunk_comments([])
    assert payload == {"comments": []}


def test_export_hunk_author_constant_is_mergecraft() -> None:
    """Pinned author string matches the issue contract."""
    assert require_attr("HUNK_COMMENT_AUTHOR") == "mergeCraft"


def test_export_hunk_rejects_invalid_file_findings_mode() -> None:
    """Error — unknown ``file_findings`` modes fail closed."""
    with pytest.raises((ValueError, TypeError), match=r".+"):
        export_hunk_comments([sample_line_finding()], file_findings="bogus")


def test_export_hunk_dropped_file_level_count_helper() -> None:
    """Integration — exporter exposes how many file-level rows were omitted."""
    count_dropped = require_attr("count_dropped_file_level_findings")
    findings = [
        sample_file_level_finding(path="a.py"),
        sample_file_level_finding(path="b.py"),
        sample_line_finding(),
    ]
    assert count_dropped(findings) == 2


def test_export_hunk_file_level_warning_message_is_counted() -> None:
    """Human warning copy matches the issue example (counted, plural-aware)."""
    format_warning = require_attr("format_file_level_drop_warning")
    message = format_warning(3)
    assert re.search(r"\b3\b", message)
    assert "file-level" in message.casefold()
    assert "not exportable" in message.casefold()
