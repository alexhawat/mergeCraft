"""gherkin-lint ``-f json`` parser — Gherkin syntax and structure findings only (#854)."""

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

# gherkin-lint reports a feature file that does not parse under this rule id; every
# other rule is a structural lint.
_SYNTAX_RULES = frozenset({"unexpected-error", "parsing-error", "no-parser-errors"})


def parse_gherkin_lint_json(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    """Parse ``[{"filePath", "errors": [{"message", "rule", "line"}]}]`` into findings."""
    payload = require_json_array(raw, what="gherkin-lint JSON output")
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        path = resolve_repo_relative_path(str(entry.get("filePath") or ""), repo_root=repo_root)
        errors = entry.get("errors")
        if not isinstance(errors, list):
            continue
        for error in errors:
            if not isinstance(error, dict):
                continue
            rule_id = str(error.get("rule") or "gherkin-lint")
            line = coerce_line(error.get("line", 1))
            native = "error" if rule_id in _SYNTAX_RULES else "warning"
            findings.append(
                make_finding(
                    tool=manifest.id,
                    rule_id=rule_id,
                    category=category,
                    severity=map_native_severity(manifest, native),
                    confidence=map_confidence(None),
                    message=str(error.get("message") or rule_id),
                    path=path or "unknown.feature",
                    start_line=line,
                    end_line=line,
                    source="analyzer",
                )
            )
    return findings


__all__ = ["parse_gherkin_lint_json"]
