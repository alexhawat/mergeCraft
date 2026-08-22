"""Anti-slop analyzer — deterministic low-quality pattern detection (#393)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.analyzers.antislop.matcher import RuleMatch, apply_rules
from mergecraft.analyzers.antislop.policy import AntislopRule, load_native_rules
from mergecraft.analyzers.cluster import cluster_findings
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import IntroducedByPr

_TOOL = "antislop"
_INTRODUCED: IntroducedByPr = "true"

_SEVERITY_MAP: dict[str, str] = {
    "major": "Major",
    "minor": "Minor",
    "trivial": "Trivial",
}

_SCOPED_SUFFIXES = (
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
)


@dataclass(frozen=True, slots=True)
class AntislopScanResult:
    """Outcome of scanning changed source files for anti-slop patterns."""

    findings: list[Finding]
    skipped: bool = False
    skip_reason: str | None = None


def scan_changed_files(
    *,
    repo_root: Path,
    changed_files: list[str],
) -> AntislopScanResult:
    """Scan changed Python and JS/TS files with native YAML anti-slop rules."""
    repo_root = repo_root.resolve()
    scoped = [path for path in changed_files if _is_scoped_path(path)]
    if not scoped:
        return AntislopScanResult(
            findings=[],
            skipped=True,
            skip_reason="skipped antislop: no changed source paths",
        )

    rule_overrides, ignore_patterns = _load_repo_settings(repo_root)
    rules = _active_rules(load_native_rules(), rule_overrides=rule_overrides)
    if not rules:
        return AntislopScanResult(
            findings=[],
            skipped=True,
            skip_reason="skipped antislop: all rules disabled",
        )

    matches: list[RuleMatch] = []
    scanned_any = False
    for rel_path in scoped:
        if _path_ignored(rel_path, ignore_patterns):
            continue
        scanned_any = True
        absolute = repo_root / rel_path
        if not absolute.is_file():
            continue
        try:
            source = absolute.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("antislop: could not read {}: {}", rel_path, exc)
            continue
        matches.extend(
            apply_rules(rel_path=rel_path, source=source, rules=rules),
        )

    if not scanned_any and ignore_patterns:
        return AntislopScanResult(
            findings=[],
            skipped=True,
            skip_reason="skipped antislop: all changed paths ignored",
        )

    findings = [_finding_from_match(match) for match in matches]
    return AntislopScanResult(findings=cluster_findings(findings))


def _load_repo_settings(repo_root: Path) -> tuple[dict[str, str] | None, list[str] | None]:
    settings = load_repo_settings(root=repo_root, load_learnings_files=False)
    override = settings.analyzers.overrides.get("antislop")
    if override is None:
        return None, None
    return override.rules, override.ignore


def _active_rules(
    rules: tuple[AntislopRule, ...],
    *,
    rule_overrides: dict[str, str] | None,
) -> tuple[AntislopRule, ...]:
    if not rule_overrides:
        return rules
    known_ids = {rule.rule_id for rule in rules}
    for override_id in rule_overrides:
        if override_id not in known_ids:
            logger.warning(
                "antislop: unknown rule override {rule_id!r} ignored",
                rule_id=override_id,
            )
    active: list[AntislopRule] = []
    for rule in rules:
        override = rule_overrides.get(rule.rule_id)
        if override is not None and override.strip().casefold() == "off":
            continue
        active.append(rule)
    return tuple(active)


def _path_ignored(rel_path: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return False
    normalized = rel_path.replace("\\", "/")
    pure = PurePath(normalized)
    for pattern in patterns:
        pat = pattern.replace("\\", "/")
        if pure.match(pat):
            return True
        if pat.startswith("**/") and pure.match(pat[3:]):
            return True
    return False


def _is_scoped_path(rel_path: str) -> bool:
    lowered = rel_path.strip().casefold()
    return bool(lowered) and lowered.endswith(_SCOPED_SUFFIXES)


def _finding_from_match(match: RuleMatch) -> Finding:
    native_severity = match.rule.severity.casefold()
    severity = _SEVERITY_MAP.get(native_severity, "Minor")
    return make_finding(
        tool=_TOOL,
        rule_id=match.rule.rule_id,
        category=match.rule.category,
        severity=severity,
        confidence=match.rule.confidence,
        message=match.rule.message,
        path=match.path,
        start_line=match.start_line,
        end_line=match.end_line,
        source="analyzer",
        evidence=[match.snippet] if match.snippet else [],
        remediation=match.rule.remediation or None,
        introduced_by_pr=_INTRODUCED,
    )


__all__ = [
    "AntislopRule",
    "AntislopScanResult",
    "load_native_rules",
    "scan_changed_files",
]
