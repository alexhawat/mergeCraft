"""Ruff JSON output parser."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


# ruff (0.15.x and 0.16.x) reports ``"severity": "error"`` for every diagnostic,
# so the manifest ``severity_map`` alone would make a stray unused import as
# blocking as an undefined name. The native level only caps the severity; a
# diagnostic stays Major (the manifest's ``error`` mapping) only when its rule
# code starts with one of these bug-class prefixes. Everything else -- style,
# import order, unused imports/variables (F401/F841), pycodestyle E/W,
# docstrings, naming, upgrades, quotes, f-string without placeholders (F541) --
# is downgraded to Minor. Prefixes match on the rule code start, so ``F82``
# covers F821/F822/F823 and ``B`` the whole flake8-bugbear family.
_BUG_CLASS_RULE_PREFIXES: tuple[str, ...] = (
    "E9",  # syntax / IO errors (E902, E999-era)
    "F50",  # invalid %-format
    "F52",  # invalid str.format
    "F6",  # invalid literals / assertions / dict keys / star-expr misuse
    "F7",  # misplaced return/yield/break/continue, syntax in annotations
    "F82",  # undefined names (F821 / F822 / F823)
    "F811",  # redefinition of an unused name
    "F402",  # import shadowed by loop variable
    "B",  # flake8-bugbear
    "S",  # flake8-bandit security
    "PLE",  # pylint errors
    "ASYNC",  # flake8-async
    "RUF006",  # dangling asyncio task
)


def _severity_for_rule(manifest: AnalyzerManifest, native_level: str, code: str) -> str:
    """Map the native level, then cap non-bug-class rules at Minor."""
    mapped = map_native_severity(manifest, native_level)
    if mapped == "Major" and not code.startswith(_BUG_CLASS_RULE_PREFIXES):
        return "Minor"
    return mapped


def parse_ruff_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    _ = repo_root
    payload = json.loads(raw)
    if not isinstance(payload, list):
        msg = "ruff JSON output must be an array"
        raise ValueError(msg)

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        path = str(item.get("filename") or "")
        location = item.get("location") or {}
        start_line = coerce_line(location.get("row", 1))
        end_line = start_line
        native_level = str(item.get("severity") or "warning")
        rule_id = str(item.get("code") or "ruff")
        fix = item.get("fix") if manifest.supports_fix else None
        autofix = None
        if isinstance(fix, dict) and str(fix.get("applicability") or "") in {"safe", "unsafe"}:
            autofix = str(fix.get("message") or "Apply ruff fix")
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=_severity_for_rule(manifest, native_level, rule_id),
                confidence=map_confidence(None),
                message=str(item.get("message") or "ruff finding"),
                path=path,
                start_line=start_line,
                end_line=end_line,
                source="analyzer",
                autofix=autofix,
            )
        )
    return findings


__all__ = ["parse_ruff_json"]
