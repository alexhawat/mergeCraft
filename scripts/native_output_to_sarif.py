#!/usr/bin/env python3
"""Convert mypy JSON-lines, Bandit JSON, or TruffleHog JSONL into SARIF 2.1.0.

CI uploads ruff's native SARIF; mypy, Bandit, and TruffleHog do not emit
SARIF in the pinned versions, so this adapter produces artifacts named
``mypy-sarif`` / ``bandit-sarif`` / ``trufflehog-sarif`` for CI evidence ingest.

Malformed or missing native input is a converter failure — not an empty
clean SARIF document. TruffleHog is the exception for *empty* stdout: a
clean scan writes no findings, so empty JSONL becomes a valid
empty-results SARIF with tool metadata (never a 0-byte file).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TypedDict

from mergecraft.analyzers.parsers._common import require_json_object, require_line
from mergecraft.analyzers.parsers.bandit_json import (
    bandit_native_severity,
    bandit_row_span,
    iter_bandit_result_rows,
)
from mergecraft.analyzers.parsers.trufflehog_jsonl import (
    _detector_name,
    _line_from_metadata,
    _path_from_metadata,
)

_BANDIT_LEVEL = {"high": "error", "medium": "warning", "low": "note", "undefined": "note"}
_MYPY_CLEAN_SUMMARY = re.compile(r"^Success: no issues found in \d+ source files\.?$")


class ConverterError(ValueError):
    """Native tool output could not be converted to SARIF."""


class SarifMessage(TypedDict):
    text: str


class SarifArtifactLocation(TypedDict):
    uri: str


class SarifRegion(TypedDict):
    startLine: int
    endLine: int


class SarifPhysicalLocation(TypedDict):
    artifactLocation: SarifArtifactLocation
    region: SarifRegion


class SarifLocation(TypedDict):
    physicalLocation: SarifPhysicalLocation


class SarifResult(TypedDict):
    ruleId: str
    level: str
    message: SarifMessage
    locations: list[SarifLocation]


class SarifDriver(TypedDict):
    name: str


class SarifTool(TypedDict):
    driver: SarifDriver


class SarifRun(TypedDict):
    tool: SarifTool
    results: list[SarifResult]


class SarifLog(TypedDict):
    version: str
    runs: list[SarifRun]


def _sarif(*, tool: str, results: list[SarifResult]) -> SarifLog:
    """Return a minimal SARIF 2.1.0 document for ``tool``."""
    return {
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": tool}}, "results": results}],
    }


def _result(
    *,
    rule_id: str,
    level: str,
    message: str,
    uri: str,
    start_line: int,
    end_line: int,
) -> SarifResult:
    """Return one SARIF result object."""
    return {
        "ruleId": rule_id,
        "level": level,
        "message": {"text": message},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": uri},
                    "region": {"startLine": start_line, "endLine": end_line},
                }
            }
        ],
    }


def mypy_to_sarif(raw: str) -> SarifLog:
    """Convert mypy ``--output json`` NDJSON into SARIF.

    Empty or missing native output is a converter failure (same as Bandit).
    An explicit JSON array ``[]`` is a real clean run with no diagnostics.
    """
    stripped = raw.strip()
    if not stripped:
        msg = "mypy native output is empty"
        raise ConverterError(msg)
    if stripped == "[]":
        return _sarif(tool="mypy", results=[])
    results: list[SarifResult] = []
    matched = False
    for line in raw.splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            continue
        if stripped_line[0] not in "{[":
            continue
        try:
            parsed = json.loads(stripped_line)
        except json.JSONDecodeError as exc:
            msg = "mypy native output contains invalid or truncated JSON"
            raise ConverterError(msg) from exc
        if not isinstance(parsed, dict):
            continue
        matched = True
        item = parsed
        severity = str(item.get("severity") or "error")
        level = "error" if severity == "error" else "warning"
        try:
            start = require_line(item.get("line"), default=1)
            end = require_line(item.get("end_line"), default=start)
        except ValueError as exc:
            raise ConverterError(str(exc)) from exc
        results.append(
            _result(
                rule_id=str(item.get("code") or "mypy"),
                level=level,
                message=str(item.get("message") or "mypy finding"),
                uri=str(item.get("file") or "unknown"),
                start_line=start,
                end_line=max(end, start),
            )
        )
    if not matched:
        leftover = [
            line.strip()
            for line in raw.splitlines()
            if line.strip()
            and line.strip()[0] not in "{["
            and _MYPY_CLEAN_SUMMARY.match(line.strip()) is None
        ]
        if leftover:
            msg = "mypy native output is not JSON lines"
            raise ConverterError(msg)
        return _sarif(tool="mypy", results=[])
    return _sarif(tool="mypy", results=results)


def bandit_to_sarif(raw: str) -> SarifLog:
    """Convert Bandit JSON (``-f json``) into SARIF.

    Empty input and invalid JSON are converter failures. A valid document
    with ``"results": []`` is a real clean scan.
    """
    if not raw.strip():
        msg = "bandit native output is empty"
        raise ConverterError(msg)
    try:
        payload = require_json_object(raw, what="bandit JSON output")
    except ValueError as exc:
        raise ConverterError(str(exc)) from exc
    try:
        rows = list(iter_bandit_result_rows(payload))
    except ValueError as exc:
        raise ConverterError(str(exc)) from exc
    results: list[SarifResult] = []
    for item in rows:
        native = bandit_native_severity(item)
        try:
            start, end = bandit_row_span(item, parse_line=require_line)
        except ValueError as exc:
            raise ConverterError(str(exc)) from exc
        results.append(
            _result(
                rule_id=str(item.get("test_id") or "bandit"),
                level=_BANDIT_LEVEL.get(native, "note"),
                message=str(item.get("issue_text") or "bandit finding"),
                uri=str(item.get("filename") or "unknown"),
                start_line=start,
                end_line=end,
            )
        )
    return _sarif(tool="bandit", results=results)


def _is_trufflehog_log_line(item: dict[str, object]) -> bool:
    """Return True for TruffleHog progress logs (not findings)."""
    return bool(item.get("level") and item.get("msg"))


def trufflehog_to_sarif(raw: str) -> SarifLog:
    """Convert TruffleHog ``-j`` JSONL into SARIF.

    Empty stdout (or only progress logs) is a real clean scan: emit a valid
    empty-results document with tool metadata. Truncated or invalid JSON is
    a converter failure. Finding ``Raw`` / ``RawV2`` values never enter the
    SARIF message — only detector name, path, and line.
    """
    results: list[SarifResult] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            msg = "trufflehog native output contains invalid or truncated JSON"
            raise ConverterError(msg) from exc
        if not isinstance(parsed, dict):
            continue
        if _is_trufflehog_log_line(parsed):
            continue
        metadata = parsed.get("SourceMetadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        path = _path_from_metadata(metadata, repo_root=None)
        try:
            start = require_line(_line_from_metadata(metadata), default=1)
        except ValueError as exc:
            raise ConverterError(str(exc)) from exc
        detector = _detector_name(parsed)
        verified = bool(parsed.get("Verified"))
        results.append(
            _result(
                rule_id=detector,
                level="error" if verified else "warning",
                message=f"{detector} secret detected at {path}:{start}",
                uri=path,
                start_line=start,
                end_line=start,
            )
        )
    return _sarif(tool="trufflehog", results=results)


_CONVERTERS = {
    "mypy": mypy_to_sarif,
    "bandit": bandit_to_sarif,
    "trufflehog": trufflehog_to_sarif,
}


def main(argv: list[str] | None = None) -> int:
    """Convert ``INPUT`` to SARIF at ``OUTPUT``. Return process status."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3 or args[0] not in _CONVERTERS:
        sys.stderr.write("usage: native_output_to_sarif.py mypy|bandit|trufflehog INPUT OUTPUT\n")
        return 2
    kind, src, dest = args
    src_path = Path(src)
    if not src_path.is_file():
        sys.stderr.write(f"native_output_to_sarif: missing input {src}\n")
        return 1
    raw = src_path.read_text(encoding="utf-8")
    try:
        document = _CONVERTERS[kind](raw)
    except ConverterError as exc:
        sys.stderr.write(f"native_output_to_sarif: {exc}\n")
        return 1
    out = Path(dest)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
