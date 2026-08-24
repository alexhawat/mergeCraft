#!/usr/bin/env python3
"""Convert mypy JSON-lines or Bandit JSON into a SARIF 2.1.0 document.

CI uploads ruff's native SARIF; mypy and Bandit do not emit SARIF in the
pinned versions, so this adapter produces artifacts named ``mypy-sarif`` /
``bandit-sarif`` for #464 first-wave ingest.

Module: scripts.native_output_to_sarif
Depends: json, pathlib, sys

Exports:
    main — CLI: ``mypy|bandit INPUT OUTPUT``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_BANDIT_LEVEL = {"HIGH": "error", "MEDIUM": "warning", "LOW": "note"}


def _sarif(*, tool: str, results: list[dict[str, Any]]) -> dict[str, Any]:
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
) -> dict[str, Any]:
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


def mypy_to_sarif(raw: str) -> dict[str, Any]:
    """Convert mypy ``--output json`` NDJSON into SARIF."""
    results: list[dict[str, Any]] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "error")
        level = "error" if severity == "error" else "warning"
        start = int(item.get("line") or 1)
        end = int(item.get("end_line") or start)
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
    return _sarif(tool="mypy", results=results)


def bandit_to_sarif(raw: str) -> dict[str, Any]:
    """Convert Bandit JSON (``-f json``) into SARIF."""
    if not raw.strip():
        return _sarif(tool="bandit", results=[])
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _sarif(tool="bandit", results=[])
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return _sarif(tool="bandit", results=[])
    results: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        native = str(item.get("issue_severity") or "LOW").upper()
        line = int(item.get("line_number") or 1)
        results.append(
            _result(
                rule_id=str(item.get("test_id") or "bandit"),
                level=_BANDIT_LEVEL.get(native, "note"),
                message=str(item.get("issue_text") or "bandit finding"),
                uri=str(item.get("filename") or "unknown"),
                start_line=max(line, 1),
                end_line=max(line, 1),
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
    raw = Path(src).read_text(encoding="utf-8") if Path(src).is_file() else ""
    document = mypy_to_sarif(raw) if kind == "mypy" else bandit_to_sarif(raw)
    out = Path(dest)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
