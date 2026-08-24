"""CC #454 — ``Finding`` round-trip conformance across every output format (D5).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-c-findings-cli-wave-plan.md``
Pins that markdown, JSON, agent JSONL, PR comments, SARIF, and Hunk export all
project the same ``Finding`` semantics. Named adapter hacks are explicit — no
silent per-format invention.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from mergecraft.analyzers.sarif import export_sarif, validate_sarif_document
from mergecraft.findings.hunk_export import export_hunk_comments
from tests.analyzers.support_short_id import require_callable
from tests.findings.support_round_trip import (
    NAMED_FORMAT_HACKS,
    conformance_corpus,
    corpus_case_ids,
    finding_module,
    json_record_without_short_id,
    sarif_result_for_path,
    short_id_for,
)

_SEVERITY_TO_SARIF_LEVEL = {
    "Critical": "error",
    "Major": "error",
    "Minor": "warning",
    "Trivial": "note",
}


@pytest.mark.parametrize("case_id", corpus_case_ids())
def test_json_record_round_trips_finding(case_id: str) -> None:
    """Structured JSON is lossless aside from the export-only ``short_id`` field."""
    finding_json_record = require_callable("finding_json_record")
    finding_mod = finding_module()
    finding = next(f for cid, f in conformance_corpus() if cid == case_id)
    short_id = short_id_for(finding)

    record = finding_json_record(finding, short_id=short_id)
    assert record["short_id"] == short_id
    restored = finding_mod.Finding.model_validate(json_record_without_short_id(record))
    assert restored == finding


@pytest.mark.parametrize("case_id", corpus_case_ids())
def test_agent_jsonl_record_matches_json_record(case_id: str) -> None:
    """Agent JSONL uses the same finding projection as structured JSON."""
    finding_json_record = require_callable("finding_json_record")
    finding = next(f for cid, f in conformance_corpus() if cid == case_id)
    short_id = short_id_for(finding)

    json_record = finding_json_record(finding, short_id=short_id)
    jsonl_record = finding_json_record(finding, short_id=short_id)
    assert jsonl_record == json_record

    line = json.dumps({"event": "finding", "finding": jsonl_record}, ensure_ascii=False)
    parsed = json.loads(line)["finding"]
    restored = finding_module().Finding.model_validate(json_record_without_short_id(parsed))
    assert restored == finding


@pytest.mark.parametrize("case_id", corpus_case_ids())
def test_markdown_render_preserves_core_semantics(case_id: str) -> None:
    """Markdown quotes path, severity, rule, message, and the short id."""
    render_finding_markdown = require_callable("render_finding_markdown")
    finding = next(f for cid, f in conformance_corpus() if cid == case_id)
    short_id = short_id_for(finding)

    rendered = render_finding_markdown(finding, short_id=short_id)
    assert short_id in rendered
    assert finding.message in rendered
    assert finding.path in rendered
    assert finding.rule_id in rendered
    assert finding.severity in rendered
    if finding.start_line is not None:
        assert f"{finding.path}:{finding.start_line}" in rendered
    else:
        assert f"{finding.path}:" not in rendered


@pytest.mark.parametrize("case_id", corpus_case_ids())
def test_pr_comment_render_preserves_core_semantics(case_id: str) -> None:
    """PR inline comments surface the short id, location, and message."""
    render_finding_pr_comment = require_callable("render_finding_pr_comment")
    finding = next(f for cid, f in conformance_corpus() if cid == case_id)
    short_id = short_id_for(finding)

    body = render_finding_pr_comment(finding, short_id=short_id)
    assert short_id in body
    assert finding.message in body
    if finding.start_line is not None:
        assert f"{finding.path}:{finding.start_line}" in body
    else:
        assert finding.path in body
        assert f"{finding.path}:" not in body


@pytest.mark.parametrize("case_id", corpus_case_ids())
def test_sarif_export_preserves_core_semantics(case_id: str) -> None:
    """SARIF carries message, rule id, path, and line region when anchored."""
    finding = next(f for cid, f in conformance_corpus() if cid == case_id)
    document = export_sarif([finding])
    validate_sarif_document(document)

    result = sarif_result_for_path(document, path=finding.path)
    assert result["ruleId"] == finding.rule_id
    assert result["message"]["text"] == finding.message
    assert result["level"] == _SEVERITY_TO_SARIF_LEVEL[finding.severity]

    physical = result["locations"][0]["physicalLocation"]
    assert physical["artifactLocation"]["uri"] == finding.path
    if finding.start_line is None:
        assert "region" not in physical
    else:
        region = physical["region"]
        assert region["startLine"] == finding.start_line
        if finding.end_line is not None:
            assert region["endLine"] == finding.end_line


@pytest.mark.parametrize(
    ("case_id", "expects_export"),
    [
        ("line_anchored_minimal", True),
        ("file_level", False),
        ("multi_line_range", True),
        ("empty_evidence", True),
        ("no_remediation", True),
        ("full_metadata", True),
        ("unicode_message", True),
    ],
)
def test_hunk_default_export_respects_file_level_drop(
    case_id: str, *, expects_export: bool
) -> None:
    """Default Hunk export drops file-level findings (``HUNK_FILE_LEVEL_DROP``)."""
    finding = next(f for cid, f in conformance_corpus() if cid == case_id)
    payload = export_hunk_comments([finding])
    comments = payload["comments"]
    if expects_export:
        assert len(comments) == 1
        comment = comments[0]
        assert comment["filePath"] == finding.path
        assert comment["newLine"] == finding.start_line
        assert finding.message in str(comment["rationale"])
    else:
        assert comments == []


def test_hunk_first_changed_line_exports_file_level_with_named_hack() -> None:
    """File-level findings use ``HUNK_FILE_LEVEL_FIRST_CHANGED_LINE`` when opted in."""
    finding = next(f for cid, f in conformance_corpus() if cid == "file_level")
    payload = export_hunk_comments(
        [finding],
        file_findings="first-changed-line",
        first_changed_lines={"README.md": 7},
    )
    comment = payload["comments"][0]
    assert comment["filePath"] == "README.md"
    assert comment["newLine"] == 7
    assert str(comment["summary"]).startswith("[file-level]")
    assert finding.message in str(comment["rationale"])


def test_hunk_export_never_invents_location_fallbacks() -> None:
    """Hunk comments never add ``hunkNumber`` / ``oldLine`` anchors the schema lacks."""
    findings = [f for _, f in conformance_corpus() if f.start_line is not None]
    payload = export_hunk_comments(findings)
    for comment in payload["comments"]:
        assert set(comment) <= {"filePath", "newLine", "summary", "rationale", "author"}
        assert "hunkNumber" not in comment
        assert "oldLine" not in comment
        assert "hunk" not in comment


def test_named_format_hacks_are_documented() -> None:
    """D5 — every known adapter hack is named in ``NAMED_FORMAT_HACKS``."""
    names = {hack.name for hack in NAMED_FORMAT_HACKS}
    expected = {
        "JSON_ADDS_SHORT_ID",
        "AGENT_JSONL_ADDS_SHORT_ID",
        "MARKDOWN_ONE_WAY_RENDER",
        "PR_COMMENT_ONE_WAY_RENDER",
        "HUNK_FILE_LEVEL_DROP",
        "HUNK_FILE_LEVEL_FIRST_CHANGED_LINE",
        "SARIF_SEVERITY_TO_LEVEL",
        "SARIF_FILE_LEVEL_NO_REGION",
    }
    assert names == expected


def test_all_formats_share_short_id_for_one_finding() -> None:
    """Acceptance — one finding renders the same ``MC-…`` id on every surface."""
    render_finding_markdown = require_callable("render_finding_markdown")
    finding_json_record = require_callable("finding_json_record")
    render_finding_pr_comment = require_callable("render_finding_pr_comment")

    finding = next(f for cid, f in conformance_corpus() if cid == "full_metadata")
    short_id = short_id_for(finding)

    markdown = render_finding_markdown(finding, short_id=short_id)
    json_record = finding_json_record(finding, short_id=short_id)
    jsonl_record = finding_json_record(finding, short_id=short_id)
    pr_comment = render_finding_pr_comment(finding, short_id=short_id)

    assert short_id in markdown
    assert json_record["short_id"] == short_id
    assert jsonl_record["short_id"] == short_id
    assert short_id in pr_comment

    hunk_comment = export_hunk_comments([finding])["comments"][0]
    assert short_id in str(hunk_comment["summary"])
    assert finding.path == hunk_comment["filePath"]
    assert finding.start_line == hunk_comment["newLine"]

    sarif_result = sarif_result_for_path(export_sarif([finding]), path=finding.path)
    assert sarif_result["message"]["text"] == finding.message


def test_json_round_trip_rejects_export_only_fields_on_restore() -> None:
    """Restoring a Finding rejects unknown export keys (``extra='forbid'``)."""
    finding_mod = finding_module()
    finding_json_record = require_callable("finding_json_record")
    finding = next(f for cid, f in conformance_corpus() if cid == "line_anchored_minimal")
    short_id = short_id_for(finding)
    record = finding_json_record(finding, short_id=short_id)

    with pytest.raises(ValidationError):
        finding_mod.Finding.model_validate(record)
