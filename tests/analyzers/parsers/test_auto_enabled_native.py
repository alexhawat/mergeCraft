"""Native parsers for auto-enabled tools whose stdout is not SARIF."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.analyzers.support import FIXTURES_DIR, import_module

_CASES: tuple[tuple[str, str, str, str], ...] = (
    ("cargo-audit", "cargo_audit_json", "native/cargo-audit-minimal.json", "RUSTSEC-2024-0001"),
    ("cargo-deny", "cargo_deny_json", "native/cargo-deny-minimal.jsonl", "license-denied"),
    ("vulture", "vulture_text", "native/vulture-minimal.txt", "unused"),
    ("tsc", "tsc_pretty", "native/tsc-minimal.txt", "TS2322"),
    ("knip", "knip_json", "native/knip-minimal.json", "files"),
    ("jscpd", "jscpd_json", "native/jscpd-minimal.json", "clone"),
    ("bundler-audit", "bundler_audit_json", "native/bundler-audit-minimal.json", "CVE-2021-22885"),
    ("sqlfluff", "sqlfluff_json", "native/sqlfluff-minimal.json", "LT01"),
    ("clippy", "rustc_json", "native/clippy-minimal.jsonl", "clippy::unwrap_used"),
)


def _manifest(tool_id: str):
    return import_module("mergecraft.analyzers.registry").get_manifest(tool_id)


def _parse(parser_id: str, raw: str, *, tool_id: str):
    parsers = import_module("mergecraft.analyzers.parsers")
    return parsers.get_parser(parser_id)(raw, manifest=_manifest(tool_id), repo_root=Path("."))


@pytest.mark.parametrize(("tool_id", "parser_id", "fixture", "rule_id"), _CASES)
def test_auto_enabled_parser_happy_path(
    tool_id: str, parser_id: str, fixture: str, rule_id: str
) -> None:
    raw = (FIXTURES_DIR / fixture).read_text(encoding="utf-8")
    findings = _parse(parser_id, raw, tool_id=tool_id)
    assert findings
    assert findings[0].path
    assert any(finding.rule_id == rule_id for finding in findings)
    assert _manifest(tool_id).parser == parser_id


@pytest.mark.parametrize(("tool_id", "parser_id"), [(row[0], row[1]) for row in _CASES])
@pytest.mark.parametrize("raw", ["", "   ", "not-json", "{", "[", "[]", "{}"])
def test_auto_enabled_parser_empty_or_malformed_does_not_crash(
    tool_id: str, parser_id: str, raw: str
) -> None:
    findings = _parse(parser_id, raw, tool_id=tool_id)
    assert findings == []


def test_tsc_command_keeps_no_emit() -> None:
    manifest = _manifest("tsc")
    assert "--noEmit" in manifest.command
    assert "--pretty" in manifest.command
    assert "false" in manifest.command


def test_typos_keeps_sarif_at_pinned_version() -> None:
    """typos 1.32.0 added ``--format sarif`` in 1.28.4; keep SARIF ingest."""
    manifest = _manifest("typos")
    assert manifest.parser == "sarif"
    assert "--format" in manifest.command
    assert "sarif" in manifest.command
