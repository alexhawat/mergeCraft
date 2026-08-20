"""rustc / cargo ``--message-format=json`` compiler-message parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    load_jsonl_objects,
    map_confidence,
    map_native_severity,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

_LEVEL_ALIASES: dict[str, str] = {
    "error": "error",
    "warning": "warning",
    "note": "note",
    "help": "note",
}


def _diagnostic_message(item: dict[str, Any]) -> dict[str, Any] | None:
    if str(item.get("reason") or "") == "compiler-message":
        message = item.get("message")
        return message if isinstance(message, dict) else None
    if "spans" in item and "level" in item:
        return item
    return None


def _primary_span(message: dict[str, Any]) -> dict[str, Any] | None:
    spans = message.get("spans")
    if not isinstance(spans, list):
        return None
    for span in spans:
        if isinstance(span, dict) and span.get("is_primary"):
            return span
    for span in spans:
        if isinstance(span, dict):
            return span
    return None


def parse_rustc_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for item in load_jsonl_objects(raw):
        message = _diagnostic_message(item)
        if message is None:
            continue
        native = _LEVEL_ALIASES.get(str(message.get("level") or "").casefold())
        if native is None or native not in manifest.severity_map:
            continue
        span = _primary_span(message)
        if span is None:
            continue
        code_raw = message.get("code")
        code_obj = code_raw if isinstance(code_raw, dict) else {}
        rule_id = str(code_obj.get("code") or "rustc")
        start_line = coerce_line(span.get("line_start", 1))
        end_line = coerce_line(span.get("line_end", start_line), default=start_line)
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(manifest, native),
                confidence=map_confidence(None),
                message=str(message.get("message") or rule_id),
                path=resolve_repo_relative_path(
                    str(span.get("file_name") or ""), repo_root=repo_root
                ),
                start_line=start_line,
                end_line=end_line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_rustc_json"]
