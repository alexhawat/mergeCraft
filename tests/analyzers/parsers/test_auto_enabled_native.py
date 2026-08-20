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

_JSON_OBJECT_TOOLS: tuple[tuple[str, str], ...] = (
    ("cargo-audit", "cargo_audit_json"),
    ("knip", "knip_json"),
    ("jscpd", "jscpd_json"),
    ("bundler-audit", "bundler_audit_json"),
)
_JSONL_TOOLS: tuple[tuple[str, str], ...] = (
    ("cargo-deny", "cargo_deny_json"),
    ("clippy", "rustc_json"),
)
_TEXT_TOOLS: tuple[tuple[str, str], ...] = (
    ("vulture", "vulture_text"),
    ("tsc", "tsc_pretty"),
)
_GARBAGE = (
    "",
    "not-json",
    "{",
    "[",
    "error: no such command: 'audit'",
    "error: no such command: 'deny'",
    "error: no such command: 'clippy'",
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


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSON_OBJECT_TOOLS)
@pytest.mark.parametrize("raw", _GARBAGE)
def test_json_object_parser_raises_on_garbage(tool_id: str, parser_id: str, raw: str) -> None:
    with pytest.raises(ValueError, match="JSON"):
        _parse(parser_id, raw, tool_id=tool_id)


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSON_OBJECT_TOOLS)
def test_json_object_parser_empty_object_is_clean(tool_id: str, parser_id: str) -> None:
    assert _parse(parser_id, "{}", tool_id=tool_id) == []


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSON_OBJECT_TOOLS)
def test_json_object_parser_empty_array_is_wrong_shape(tool_id: str, parser_id: str) -> None:
    with pytest.raises(ValueError, match="JSON object"):
        _parse(parser_id, "[]", tool_id=tool_id)


def test_sqlfluff_parser_raises_on_garbage() -> None:
    with pytest.raises(ValueError, match="JSON"):
        _parse("sqlfluff_json", "error: no such command: 'sqlfluff'", tool_id="sqlfluff")


@pytest.mark.parametrize("raw", ["[]", "{}"])
def test_sqlfluff_parser_empty_document_is_clean(raw: str) -> None:
    assert _parse("sqlfluff_json", raw, tool_id="sqlfluff") == []


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSONL_TOOLS)
@pytest.mark.parametrize("raw", ["not-json", "{", "error: no such command: 'deny'"])
def test_jsonl_parser_raises_on_garbage(tool_id: str, parser_id: str, raw: str) -> None:
    with pytest.raises(ValueError, match="JSON"):
        _parse(parser_id, raw, tool_id=tool_id)


@pytest.mark.parametrize(("tool_id", "parser_id"), _JSONL_TOOLS)
@pytest.mark.parametrize("raw", ["", "   ", "[]", "{}"])
def test_jsonl_parser_empty_document_is_clean(tool_id: str, parser_id: str, raw: str) -> None:
    assert _parse(parser_id, raw, tool_id=tool_id) == []


@pytest.mark.parametrize(("tool_id", "parser_id"), _TEXT_TOOLS)
@pytest.mark.parametrize("raw", ["", "   ", "not-json", "{", "[", "[]", "{}"])
def test_text_parser_empty_or_unmatched_does_not_crash(
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
