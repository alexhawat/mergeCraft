"""HTMLHint ``--format json`` array parser."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    require_json_array,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

_LEVELS: dict[str, str] = {"error": "error", "warning": "warning"}


def parse_htmlhint_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = require_json_array(raw, what="htmlhint JSON output")
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for file_result in payload:
        if not isinstance(file_result, dict):
            continue
        path = resolve_repo_relative_path(str(file_result.get("file") or ""), repo_root=repo_root)
        messages = file_result.get("messages")
        if not isinstance(messages, list):
            continue
        for message in messages:
            if not isinstance(message, dict):
                continue
            native = _LEVELS.get(str(message.get("type") or "warning").casefold(), "warning")
            rule_raw = message.get("rule")
            rule = rule_raw if isinstance(rule_raw, dict) else {}
            rule_id = str(rule.get("id") or message.get("rule") or "htmlhint")
            start_line = coerce_line(message.get("line", 1))
            findings.append(
                make_finding(
                    tool=manifest.id,
                    rule_id=rule_id,
                    category=category,
                    severity=map_native_severity(manifest, native),
                    confidence=map_confidence(None),
                    message=str(message.get("message") or rule_id),
                    path=path or "unknown.html",
                    start_line=start_line,
                    end_line=start_line,
                    source="analyzer",
                )
            )
    return findings


__all__ = ["parse_htmlhint_json"]
