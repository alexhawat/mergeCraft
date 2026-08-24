"""Shared corpus and helpers for CC #454 Finding output conformance tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from tests.analyzers.support import import_module
from tests.analyzers.support_short_id import require_callable as require_finding_callable

FindingFormat = Literal["json", "agent_jsonl", "markdown", "pr_comment", "hunk", "sarif"]


@dataclass(frozen=True, slots=True)
class NamedFormatHack:
    """Documented adapter behaviour that is not a lossless Finding projection (D5)."""

    name: str
    format: FindingFormat
    description: str


# D5 — named hacks only; tests reference these explicitly instead of hiding behaviour.
NAMED_FORMAT_HACKS: tuple[NamedFormatHack, ...] = (
    NamedFormatHack(
        name="JSON_ADDS_SHORT_ID",
        format="json",
        description="Structured JSON adds ``short_id`` beside the Finding fields.",
    ),
    NamedFormatHack(
        name="AGENT_JSONL_ADDS_SHORT_ID",
        format="agent_jsonl",
        description="Agent JSONL uses the same record shape as JSON (includes ``short_id``).",
    ),
    NamedFormatHack(
        name="MARKDOWN_ONE_WAY_RENDER",
        format="markdown",
        description="Markdown is a human view; there is no markdown→Finding parser.",
    ),
    NamedFormatHack(
        name="PR_COMMENT_ONE_WAY_RENDER",
        format="pr_comment",
        description="PR inline comments are a human view; there is no comment→Finding parser.",
    ),
    NamedFormatHack(
        name="HUNK_FILE_LEVEL_DROP",
        format="hunk",
        description="Default Hunk export omits findings with ``start_line is None``.",
    ),
    NamedFormatHack(
        name="HUNK_FILE_LEVEL_FIRST_CHANGED_LINE",
        format="hunk",
        description=(
            "Opt-in ``first-changed-line`` anchors file-level findings on a diff-derived line "
            "and prefixes the summary with ``[file-level]``."
        ),
    ),
    NamedFormatHack(
        name="SARIF_SEVERITY_TO_LEVEL",
        format="sarif",
        description="SARIF maps taxonomy severities to SARIF ``level`` strings.",
    ),
    NamedFormatHack(
        name="SARIF_FILE_LEVEL_NO_REGION",
        format="sarif",
        description="SARIF omits ``region`` when ``start_line is None``.",
    ),
)


def finding_module() -> Any:
    """Return ``mergecraft.analyzers.finding``."""
    return import_module("mergecraft.analyzers.finding")


def short_id_for(finding: Any) -> str:
    """Resolve the stable short id for one finding."""
    finding_short_id = require_finding_callable("finding_short_id")
    return finding_short_id(finding.fingerprint)


def corpus_case_ids() -> list[str]:
    """Return stable ids for the representative conformance corpus."""
    return [case_id for case_id, _ in conformance_corpus()]


def conformance_corpus() -> list[tuple[str, Any]]:
    """Representative findings including awkward ``Finding`` shapes (#454)."""
    make_finding = finding_module().make_finding
    return [
        (
            "line_anchored_minimal",
            make_finding(
                tool="ruff",
                rule_id="F401",
                category="Maintainability & Code Quality",
                severity="Minor",
                confidence="likely",
                message="unused import os",
                path="src/demo.py",
                start_line=3,
                end_line=3,
                source="analyzer",
            ),
        ),
        (
            "file_level",
            make_finding(
                tool="agent",
                rule_id="agent:scope",
                category="Functional Correctness",
                severity="Major",
                confidence="likely",
                message="README documents behaviour that this PR removes",
                path="README.md",
                start_line=None,
                end_line=None,
                source="agent",
            ),
        ),
        (
            "multi_line_range",
            make_finding(
                tool="semgrep",
                rule_id="python.lang.security.audit",
                category="Security & Privacy",
                severity="Critical",
                confidence="certain",
                message="unsafe deserialization spans multiple lines",
                path="pkg/handler.py",
                start_line=10,
                end_line=14,
                source="analyzer",
                evidence=["sink at line 14"],
            ),
        ),
        (
            "empty_evidence",
            make_finding(
                tool="ruff",
                rule_id="E501",
                category="Maintainability & Code Quality",
                severity="Trivial",
                confidence="likely",
                message="line too long",
                path="src/wide.py",
                start_line=42,
                end_line=42,
                source="analyzer",
                evidence=[],
            ),
        ),
        (
            "no_remediation",
            make_finding(
                tool="actionlint",
                rule_id="syntax-check",
                category="Maintainability & Code Quality",
                severity="Major",
                confidence="certain",
                message="workflow references a missing secret",
                path=".github/workflows/ci.yml",
                start_line=22,
                end_line=22,
                source="analyzer",
                remediation=None,
            ),
        ),
        (
            "full_metadata",
            make_finding(
                tool="agent",
                rule_id="agent:confirmed",
                category="Security & Privacy",
                severity="Major",
                confidence="certain",
                message="credential logged in error path",
                path="src/auth.py",
                start_line=88,
                end_line=90,
                source="agent",
                evidence=["stderr capture shows token"],
                remediation="Redact secrets before logging.",
                autofix="Replace with '[REDACTED]'.",
                introduced_by_pr="true",
                cluster_id="cluster-auth-1",
                lens="security",
                collateral=["src/logging.py"],
                fingerprint="deadbeef" + "0" * 16,
            ),
        ),
        (
            "unicode_message",
            make_finding(
                tool="ruff",
                rule_id="RUF001",
                category="Maintainability & Code Quality",
                severity="Trivial",
                confidence="likely",
                message="ambiguous unicode: café — use ASCII",
                path="src/café.py",
                start_line=1,
                end_line=1,
                source="analyzer",
            ),
        ),
    ]


def json_record_without_short_id(record: dict[str, Any]) -> dict[str, Any]:
    """Strip the export-only short id before re-validating a Finding."""
    return {key: value for key, value in record.items() if key != "short_id"}


def sarif_result_for_path(document: dict[str, Any], *, path: str) -> dict[str, Any]:
    """Return the SARIF result whose physical location matches ``path``."""
    runs = document.get("runs")
    if not isinstance(runs, list) or not runs:
        msg = "SARIF document has no runs"
        raise AssertionError(msg)
    results = runs[0].get("results")
    if not isinstance(results, list):
        msg = "SARIF run has no results list"
        raise AssertionError(msg)
    for result in results:
        if not isinstance(result, dict):
            continue
        locations = result.get("locations")
        if not isinstance(locations, list) or not locations:
            continue
        physical = locations[0].get("physicalLocation")
        if not isinstance(physical, dict):
            continue
        artifact = physical.get("artifactLocation")
        if isinstance(artifact, dict) and artifact.get("uri") == path:
            return result
    msg = f"no SARIF result for path {path!r}"
    raise AssertionError(msg)


__all__ = [
    "NAMED_FORMAT_HACKS",
    "FindingFormat",
    "NamedFormatHack",
    "conformance_corpus",
    "corpus_case_ids",
    "finding_module",
    "json_record_without_short_id",
    "sarif_result_for_path",
    "short_id_for",
]
