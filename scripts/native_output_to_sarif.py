#!/usr/bin/env python3
"""Convert mypy JSON-lines or Bandit JSON into a SARIF 2.1.0 document.

CI uploads ruff's native SARIF; mypy and Bandit do not emit SARIF in the
pinned versions, so this adapter produces artifacts named ``mypy-sarif`` /
``bandit-sarif`` for #464 first-wave ingest.

Malformed or missing native input is a converter failure — not an empty
clean SARIF document.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TypedDict

from mergecraft.analyzers.parsers._common import (
    bandit_native_severity,
    bandit_row_span,
    iter_bandit_result_rows,
    require_json_object,
    require_line,
)

_BANDIT_LEVEL = {"high": "error", "medium": "warning", "low": "note", "undefined": "note"}


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
                start_line=max(start, 1),
                end_line=max(end, start, 1),
            )
        )
    if not matched:
        msg = "mypy native output is not JSON lines"
        raise ConverterError(msg)
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
            start, end = bandit_row_span(item, fail_closed=True)
        except ValueError as exc:
            raise ConverterError(str(exc)) from exc
        results.append(
            _result(
                rule_id=str(item.get("test_id") or "bandit"),
                level=_BANDIT_LEVEL.get(native, "note"),
                message=str(item.get("issue_text") or "bandit finding"),
                uri=str(item.get("filename") or "unknown"),
                start_line=max(start, 1),
                end_line=max(end, start, 1),
            )
        )
    return _sarif(tool="bandit", results=results)


def main(argv: list[str] | None = None) -> int:
    """Convert ``INPUT`` to SARIF at ``OUTPUT``. Return process status."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3 or args[0] not in {"mypy", "bandit"}:
        sys.stderr.write("usage: native_output_to_sarif.py mypy|bandit INPUT OUTPUT\n")
        return 2
    kind, src, dest = args
    src_path = Path(src)
    if not src_path.is_file():
        sys.stderr.write(f"native_output_to_sarif: missing input {src}\n")
        return 1
    raw = src_path.read_text(encoding="utf-8")
    try:
        document = mypy_to_sarif(raw) if kind == "mypy" else bandit_to_sarif(raw)
    except ConverterError as exc:
        sys.stderr.write(f"native_output_to_sarif: {exc}\n")
        return 1
    out = Path(dest)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
