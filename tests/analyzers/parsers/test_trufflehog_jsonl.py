"""TruffleHog JSONL parser: one bad line must not drop the scan (#1234)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mergecraft.analyzers.parsers.trufflehog_jsonl import parse_trufflehog_jsonl
from mergecraft.analyzers.registry import get_manifest


def _finding_line(path: str, line: int, detector: str) -> str:
    return json.dumps(
        {
            "SourceMetadata": {"Data": {"Filesystem": {"file": path, "line": line}}},
            "DetectorName": detector,
            "Verified": False,
        }
    )


def _parse(raw: str) -> list[tuple[str, int, str]]:
    findings = parse_trufflehog_jsonl(raw, manifest=get_manifest("trufflehog"), repo_root=Path("."))
    return [(finding.path, finding.start_line, finding.rule_id) for finding in findings]


@pytest.mark.parametrize(
    "bad_line",
    [
        pytest.param('{"SourceMetadata": {"Data": {"Filesystem": {"file": "x"', id="truncated"),
        pytest.param("TruffleHog. Unearth your secrets.", id="banner"),
    ],
)
def test_undecodable_line_is_skipped_and_other_findings_survive(bad_line: str) -> None:
    """#1234: ``json.loads`` on the bad line used to raise and drop every finding."""
    raw = "\n".join(
        [
            _finding_line("config/.env", 1, "AWS"),
            bad_line,
            _finding_line("deploy/key.pem", 7, "PrivateKey"),
        ]
    )
    assert _parse(raw) == [("config/.env", 1, "AWS"), ("deploy/key.pem", 7, "PrivateKey")]


def test_output_with_no_decodable_line_still_raises() -> None:
    """Total garbage stays unparsable so the adapter reports a skip, not a clean scan."""
    with pytest.raises(ValueError, match="no decodable JSONL line"):
        _parse("not json\n{truncated\n")


def test_empty_and_log_only_output_is_a_clean_scan() -> None:
    log_line = json.dumps({"level": "info-0", "msg": "finished scanning"})
    assert _parse("") == []
    assert _parse(f"\n{log_line}\n") == []
