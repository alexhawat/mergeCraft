"""ember-template-lint ``--format json`` parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    load_json,
    map_confidence,
    map_native_severity,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

_ESLINT_SEVERITY: dict[int, str] = {1: "warning", 2: "error"}


def _file_messages(payload: object) -> list[tuple[str, list[Any]]]:
    if isinstance(payload, dict):
        rows: list[tuple[str, list[Any]]] = []
        for path, messages in payload.items():
            if isinstance(messages, list):
                rows.append((str(path), messages))
        return rows
    if isinstance(payload, list):
        rows = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            path = str(item.get("filePath") or item.get("file") or "")
            messages = item.get("messages")
            if isinstance(messages, list):
                rows.append((path, messages))
        return rows
    return []


def parse_ember_template_lint_json(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    payload = load_json(raw)
    if not isinstance(payload, dict | list):
        msg = "ember-template-lint JSON output must be an object or array"
        raise ValueError(msg)
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for raw_path, messages in _file_messages(payload):
        path = resolve_repo_relative_path(raw_path, repo_root=repo_root) or "unknown.hbs"
        for message in messages:
            if not isinstance(message, dict):
                continue
            severity_num = int(message.get("severity") or 2)
            native = _ESLINT_SEVERITY.get(severity_num, "error")
            start_line = coerce_line(message.get("line", 1))
            rule_id = str(message.get("rule") or message.get("ruleId") or "ember-template-lint")
            findings.append(
                make_finding(
                    tool=manifest.id,
                    rule_id=rule_id,
                    category=category,
                    severity=map_native_severity(manifest, native),
                    confidence=map_confidence(None),
                    message=str(message.get("message") or rule_id),
                    path=path,
                    start_line=start_line,
                    end_line=start_line,
                    source="analyzer",
                )
            )
    return findings


__all__ = ["parse_ember_template_lint_json"]
