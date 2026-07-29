"""Buf breaking and lint JSONL parser (C4.5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import make_finding
from mergecraft.analyzers.parsers._common import map_confidence, taxonomy_category

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import AnalyzerManifest

_BUF_LINT_FINDING_CAP = 3


def _repo_relative(path: str, *, repo_root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return Path(path).name


def parse_buf_breaking_json(
    raw: str,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    head_path: str = "",
) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
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
        violation_type = str(item.get("type") or "")
        if violation_type == "FILE_NO_DELETE":
            continue
        path = str(item.get("path") or head_path)
        rel = _repo_relative(path, repo_root=repo_root)
        message = str(item.get("message") or violation_type)
        if "deleted" in message.casefold():
            message = message.replace("deleted", "removed").replace("Deleted", "removed")
        if "break" not in message.casefold() and "removed" not in message.casefold():
            message = f"Breaking change: {message}"
        line_no = int(item.get("start_line") or 1)
        end_line = int(item.get("end_line") or line_no)
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=violation_type or "buf-breaking",
                category=category,
                severity=manifest.severity_map.get("breaking", "Major"),
                confidence=map_confidence(None),
                message=message,
                path=rel,
                start_line=max(line_no, 1),
                end_line=max(end_line, 1),
                source="analyzer",
                introduced_by_pr="true",
            )
        )
    return findings


def parse_buf_lint_json(
    raw: str,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
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
        path = str(item.get("path") or "unknown")
        rel = _repo_relative(path, repo_root=repo_root)
        rule_id = str(item.get("type") or "buf-lint")
        message = str(item.get("message") or rule_id)
        line_no = int(item.get("start_line") or 1)
        end_line = int(item.get("end_line") or line_no)
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=manifest.severity_map.get("lint", "Minor"),
                confidence=map_confidence(None),
                message=message,
                path=rel,
                start_line=max(line_no, 1),
                end_line=max(end_line, 1),
                source="analyzer",
                introduced_by_pr="true",
            )
        )
        if len(findings) >= _BUF_LINT_FINDING_CAP:
            break
    return findings


def parse_buf_native(
    raw: str,
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
) -> list[Finding]:
    """Parse buf JSONL output (breaking + lint modes share the line format)."""
    breaking = parse_buf_breaking_json(raw, manifest=manifest, repo_root=repo_root)
    if breaking:
        return breaking
    return parse_buf_lint_json(raw, manifest=manifest, repo_root=repo_root)


__all__ = [
    "parse_buf_breaking_json",
    "parse_buf_lint_json",
    "parse_buf_native",
]
