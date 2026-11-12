"""SARIF 2.1.0 ingest parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from loguru import logger

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    OUTSIDE_REPO_ROOT_LABEL,
    coerce_line,
    map_confidence,
    map_native_severity,
    require_json_object,
    resolve_path_and_origin,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


# SARIF 2.1.0 §3.27.9: only these result kinds report a problem; ``pass``,
# ``notApplicable`` and ``informational`` results are not findings. An absent
# ``kind`` defaults to ``fail``.
_PROBLEM_KINDS: frozenset[str] = frozenset({"fail", "review", "open"})
# §3.27.10 ``level: none`` carries no severity of its own.
_LEVEL_NONE_SEVERITY = "Trivial"
# §3.34.4: a suppression whose status is ``underReview`` or ``rejected`` does
# not suppress the result; an absent status means ``accepted``.
_SUPPRESSING_STATUSES: frozenset[str] = frozenset({"accepted"})


class _RuleTable:
    """Rule descriptors of one run: the driver's plus every extension's (§3.19.23)."""

    def __init__(self, run: dict[str, Any]) -> None:
        tool = run.get("tool") or {}
        driver = tool.get("driver") or {}
        self._driver: list[dict[str, Any]] = _rule_list(driver)
        self._by_id: dict[str, dict[str, Any]] = {}
        self._extensions: list[list[dict[str, Any]]] = []
        for rule in self._driver:
            if rule.get("id"):
                self._by_id.setdefault(str(rule["id"]), rule)
        for extension in tool.get("extensions") or []:
            rules = _rule_list(extension) if isinstance(extension, dict) else []
            self._extensions.append(rules)
            for rule in rules:
                if rule.get("id"):
                    self._by_id.setdefault(str(rule["id"]), rule)

    def for_result(self, result: dict[str, Any]) -> dict[str, Any] | None:
        """Resolve a result's rule by ``rule`` reference, ``ruleIndex`` or ``ruleId``."""
        reference = result.get("rule")
        if isinstance(reference, dict):
            component = reference.get("toolComponent")
            rules = self._driver
            if isinstance(component, dict) and isinstance(component.get("index"), int):
                index = component["index"]
                rules = self._extensions[index] if 0 <= index < len(self._extensions) else []
            indexed = _at(rules, reference.get("index"))
            if indexed is not None:
                return indexed
            if reference.get("id"):
                return self._by_id.get(str(reference["id"]))
        indexed = _at(self._driver, result.get("ruleIndex"))
        if indexed is not None:
            return indexed
        rule_id = result.get("ruleId")
        return self._by_id.get(str(rule_id)) if rule_id else None


def _rule_list(component: dict[str, Any]) -> list[dict[str, Any]]:
    return [rule for rule in component.get("rules") or [] if isinstance(rule, dict)]


def _at(rules: list[dict[str, Any]], index: object) -> dict[str, Any] | None:
    if isinstance(index, bool) or not isinstance(index, int):
        return None
    return rules[index] if 0 <= index < len(rules) else None


def _rule_id(result: dict[str, Any], rule: dict[str, Any] | None) -> str:
    if result.get("ruleId"):
        return str(result["ruleId"])
    reference = result.get("rule")
    if isinstance(reference, dict) and reference.get("id"):
        return str(reference["id"])
    if rule is not None and rule.get("id"):
        return str(rule["id"])
    return "unknown"


def _result_level(result: dict[str, Any], rule: dict[str, Any] | None) -> str:
    level = result.get("level")
    if level is not None:
        return str(level)
    if rule is not None:
        default = rule.get("defaultConfiguration") or {}
        if isinstance(default, dict) and default.get("level") is not None:
            return str(default["level"])
    return "warning"


def _severity(manifest: AnalyzerManifest, native_level: str) -> str:
    if native_level == "none" and "none" not in manifest.severity_map:
        return _LEVEL_NONE_SEVERITY
    return map_native_severity(manifest, native_level)


def _is_problem(result: dict[str, Any]) -> bool:
    kind = result.get("kind")
    return kind is None or str(kind) in _PROBLEM_KINDS


def _message_text(result: dict[str, Any]) -> str:
    message = result.get("message") or {}
    if isinstance(message, dict):
        text = message.get("text") or message.get("markdown")
        if text:
            return str(text)
    return str(result.get("ruleId") or "finding")


def _parse_location(
    location: dict[str, Any],
    *,
    repo_root: Path,
) -> tuple[str, int, int, bool]:
    physical = location.get("physicalLocation") or {}
    artifact = physical.get("artifactLocation") or {}
    uri = str(artifact.get("uri") or "")
    if not uri.startswith("file://"):
        # SARIF URIs are RFC 3986 references: a relative one is percent-encoded
        # (``src/my%20file.py``); ``file://`` URIs are decoded downstream.
        uri = unquote(uri)
    uri_base_id = artifact.get("uriBaseId")
    path, outside_root = resolve_path_and_origin(
        uri,
        repo_root=repo_root,
        uri_base_id=str(uri_base_id) if uri_base_id is not None else None,
    )
    region = physical.get("region") or {}
    start = coerce_line(region.get("startLine", region.get("line", 1)))
    end = coerce_line(region.get("endLine", start), default=start)
    if end < start:
        end = start
    return path, start, end, outside_root


def _is_suppressed(result: dict[str, Any]) -> bool:
    suppressions = result.get("suppressions") or []
    for item in suppressions:
        if not isinstance(item, dict) or item.get("kind") not in {"inSource", "external"}:
            continue
        if str(item.get("status") or "accepted") in _SUPPRESSING_STATUSES:
            return True
    return False


def _confidence_from_result(result: dict[str, Any]) -> str:
    properties = result.get("properties") or {}
    if isinstance(properties, dict):
        for key in ("confidence", "precision", "security-severity"):
            if key in properties:
                return map_confidence(str(properties[key]))
    return map_confidence(None)


def _parse_run(
    run: dict[str, Any], *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    rules = _RuleTable(run)
    findings: list[Finding] = []
    category = taxonomy_category(manifest)
    for result in run.get("results") or []:
        if not isinstance(result, dict):
            continue
        if not _is_problem(result):
            logger.debug("sarif {}: skipping result of kind {!r}", manifest.id, result.get("kind"))
            continue
        if _is_suppressed(result):
            continue
        rule = rules.for_result(result)
        rule_id = _rule_id(result, rule)
        native_level = _result_level(result, rule)
        severity = _severity(manifest, native_level)
        confidence = _confidence_from_result(result)
        message = _message_text(result)
        locations = result.get("locations") or [{}]
        location = locations[0] if locations else {}
        if not isinstance(location, dict):
            location = {}
        path, start_line, end_line, outside_root = _parse_location(location, repo_root=repo_root)
        evidence: list[str] = []
        if outside_root:
            evidence.append(f"path={OUTSIDE_REPO_ROOT_LABEL}")
        fingerprints = result.get("partialFingerprints")
        if isinstance(fingerprints, dict):
            for key, value in sorted(fingerprints.items()):
                evidence.append(f"{key}={value}")

        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=severity,
                confidence=confidence,
                message=message,
                path=path,
                start_line=start_line,
                end_line=end_line,
                source="analyzer",
                evidence=evidence,
            )
        )
    return findings


def parse_sarif(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    """Parse SARIF 2.1.0 text into normalized findings."""
    document = require_json_object(raw, what="SARIF document")
    if document.get("version") != "2.1.0":
        runs = document.get("runs")
        if not isinstance(runs, list) or not runs:
            msg = f"unsupported SARIF version: {document.get('version')!r}"
            raise ValueError(msg)

    findings: list[Finding] = []
    for run in document.get("runs") or []:
        if isinstance(run, dict):
            findings.extend(_parse_run(run, manifest=manifest, repo_root=repo_root))
    return findings


__all__ = ["parse_sarif"]
