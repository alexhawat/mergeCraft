"""B3 TruffleHog JSONL skip contracts (green after TP3)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.analyzers.support import import_module

_VALID_FINDING = {
    "DetectorName": "AWS",
    "Verified": False,
    "SourceMetadata": {
        "Data": {
            "Filesystem": {
                "file": "secrets.env",
                "line": 5,
            }
        }
    },
}


def _manifest():
    return import_module("mergecraft.analyzers.registry").get_manifest("trufflehog")


def _parse(raw: str):
    parser = import_module("mergecraft.analyzers.parsers.trufflehog_jsonl")
    return parser.parse_trufflehog_jsonl(raw, manifest=_manifest(), repo_root=Path("."))


@pytest.mark.xfail(reason="green after TP3: skip truncated JSONL lines", strict=False)
def test_truncated_first_line_plus_valid_detector_yields_one_finding() -> None:
    raw = "\n".join(
        [
            '{"DetectorName": "AWS", "SourceMetadata": {"truncated": true',
            json.dumps(_VALID_FINDING),
        ]
    )
    findings = _parse(raw)
    assert len(findings) == 1
    assert findings[0].rule_id == "AWS"
    assert findings[0].path == "secrets.env"
    assert findings[0].start_line == 5


def test_empty_lines_are_skipped() -> None:
    raw = "\n\n" + json.dumps(_VALID_FINDING) + "\n\n"
    findings = _parse(raw)
    assert len(findings) == 1


def test_json_array_line_is_skipped_without_crash() -> None:
    raw = "\n".join(
        [
            json.dumps([_VALID_FINDING]),
            json.dumps(_VALID_FINDING),
        ]
    )
    findings = _parse(raw)
    assert len(findings) == 1
    assert findings[0].rule_id == "AWS"
