"""Normalise the consumer's *already-finished* CI into review evidence (#36).

The Action image usually lacks `make`, the repo's venv, and its pinned
toolchains, so a repo-native gate reports ``unavailable`` even when the
consumer's own CI just proved the very same thing. This module turns that
finished CI into two things mergeCraft can use:

* **Findings.** A failing check run, a clustered pipeline failure, or a SARIF
  artifact becomes a :class:`~mergecraft.analyzers.finding.Finding` with
  ``source="ci"`` — the one finding model, read and produced, never extended
  (D12). CI evidence that needs somewhere to live goes in ``evidence``.
* **Gate substitution.** An ``unavailable`` / ``declared-but-cannot-run`` row
  becomes ``satisfied-by-ci`` — *only* when the repo declared which CI check
  run proves that gate (D10). Fuzzy name matching is deliberately absent: a
  check run merely *named* like a gate must buy nothing, or "CI was green"
  would silently satisfy a gate CI never ran.

Two rules keep this from turning into author-blame:

* Only a **successful** declared check run may substitute. A declared gate that
  CI proved *broken* leaves the row alone and is reported as a finding instead,
  so the report never claims a green gate on red evidence.
* Findings derived from CI start at a non-blocking severity with
  ``introduced_by_pr="unknown"``. Attribution is the CI-intelligence layer's
  job (``ci/blame.py``, ``ci/flaky.py``); until it speaks, a CI failure is
  *reported, not blamed* (D11). The approval gate is monotone in blockers, so
  this is what stops a flaky pipeline from blocking a clean PR.

Everything here is pure. The MCP tools stay the I/O boundary.

Exports:
    GateSubstitution: One audited gate outcome change, with its check run.
    check_run_to_finding: Normalise one GitHub check run into a Finding.
    ci_evidence_findings: Read back the run's recorded CI findings.
    ci_evidence_lines: Truncate + redact a log excerpt for a finding.
    declared_check_run: Resolve a gate to its declared check run (D10).
    declared_gate_findings: Findings for declared gates CI proved broken.
    record_ci_findings: Record CI findings on the run's tool state.
    record_gate_substitutions: Record substitutions for audit.
    sarif_findings: Parse a CI SARIF artifact into CI-sourced findings.
    substitute_declared_gates: Replace unavailable rows CI already proved.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.finding import Finding, FindingValidationError, make_finding
from mergecraft.analyzers.manifest import AnalyzerManifest, DetectRules
from mergecraft.analyzers.parsers.sarif import parse_sarif
from mergecraft.analyzers.redact import redact_secrets
from mergecraft.ci.paths import failure_line, primary_failure_path
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from mergecraft.analyzers.run import AnalyzerOutcome, CheckStatus
    from mergecraft.mcp.tool_state import CiEvidenceState, ToolState

CI_TOOL = "ci"
"""``Finding.tool`` for evidence read straight off a check run."""

CI_CATEGORY = "Stability & Availability"
"""A pipeline outcome is an availability signal, whatever the gate measured."""

SATISFIED_BY_CI: CheckStatus = "satisfied-by-ci"
"""Gate status meaning: not run here, proved by a declared CI check run."""

# Statuses a declared CI result is allowed to replace. A gate mergeCraft
# actually executed always outranks a CI claim about it — otherwise a stale
# green check run could paper over a gate failing on this very diff.
_REPLACEABLE: frozenset[str] = frozenset({"unavailable", "declared-but-cannot-run"})

# GitHub check-run conclusions that mean "this gate did not pass".
_FAILING_CONCLUSIONS: frozenset[str] = frozenset(
    {"failure", "timed_out", "action_required", "startup_failure"}
)

# The only conclusion that may stand in for a gate mergeCraft could not run.
_PASSING_CONCLUSION = "success"

# Severity ceiling for anything derived from CI (D11). Nothing here may reach
# `agents.gates.BLOCKING_SEVERITIES` on its own; only the blame layer promotes.
_UNBLAMED_SEVERITY = "Minor"

_EXCERPT_LINES = 12
_EXCERPT_LINE_CHARS = 200
_EXCERPT_TOTAL_CHARS = 2_000


@dataclass(frozen=True, slots=True)
class GateSubstitution:
    """One gate outcome a declared CI check run changed, recorded for audit."""

    gate: str
    check_run: str
    conclusion: str
    url: str | None = None

    @property
    def summary(self) -> str:
        """Human-readable provenance for the substituted row."""
        tail = f" — {self.url}" if self.url else ""
        return (
            f"not run here; the repo declares CI check run `{self.check_run}` as proof "
            f"of this gate, and it concluded `{self.conclusion}`{tail}"
        )

    def as_row(self) -> dict[str, Any]:
        """Serialise for the MCP payload and the recorded audit trail."""
        return {
            "gate": self.gate,
            "checkRun": self.check_run,
            "conclusion": self.conclusion,
            "url": self.url,
        }


# ── log excerpts ──────────────────────────────────────────────────────────────


def ci_evidence_lines(
    text: str,
    *,
    limit: int = _EXCERPT_LINES,
    max_chars: int = _EXCERPT_TOTAL_CHARS,
) -> list[str]:
    """Return the tail of a CI log excerpt, truncated and redacted.

    The tail, not the head: a build log's informative part is where it died.
    Redaction runs *after* truncation on the surviving lines, so a secret can
    never ride along in a line that was going to be kept anyway.
    """
    if limit <= 0 or not text.strip():
        return []
    kept = [line.strip() for line in text.splitlines() if line.strip()][-limit:]
    lines: list[str] = []
    budget = max_chars
    for line in kept:
        clipped = redact_secrets(line[:_EXCERPT_LINE_CHARS])
        if len(clipped) > budget:
            clipped = clipped[:budget]
        if not clipped:
            continue
        lines.append(clipped)
        budget -= len(clipped)
        if budget <= 0:
            break
    return lines


# ── check runs → findings ─────────────────────────────────────────────────────


def _check_run_name(check_run: Mapping[str, Any]) -> str:
    return str(check_run.get("name") or "").strip()


def _check_run_conclusion(check_run: Mapping[str, Any]) -> str:
    return str(check_run.get("conclusion") or "").strip().lower()


def _check_run_url(check_run: Mapping[str, Any]) -> str | None:
    url = check_run.get("html_url") or check_run.get("details_url")
    return str(url) if url else None


def _output_title(check_run: Mapping[str, Any]) -> str:
    output = check_run.get("output")
    if isinstance(output, Mapping):
        title = output.get("title")
        if title:
            return redact_secrets(str(title))
    return ""


def check_run_to_finding(
    check_run: Mapping[str, Any],
    *,
    gate: str | None = None,
    log_excerpt: str | None = None,
) -> Finding | None:
    """Normalise one completed check run into a CI finding, or ``None``.

    ``None`` for anything that is not a completed failure: a green, skipped, or
    still-running check run is *evidence*, and manufacturing a finding from it
    would put noise where the issue asked for signal.

    The finding is deliberately unblamed — ``Minor`` / ``unknown`` — because a
    bare check run carries no retry history and no base-branch comparison, so
    nothing here can honestly say this PR caused it (D11). ``ci/blame.py`` and
    ``ci/flaky.py`` promote it when they can prove attribution.
    """
    if str(check_run.get("status") or "completed").strip().lower() != "completed":
        return None
    conclusion = _check_run_conclusion(check_run)
    if conclusion not in _FAILING_CONCLUSIONS:
        return None

    name = _check_run_name(check_run) or "unnamed check run"
    excerpt = log_excerpt or ""
    path = primary_failure_path(excerpt) if excerpt else "ci/pipeline"
    line = failure_line(excerpt, path=path) if excerpt and path != "ci/pipeline" else 1

    title = _output_title(check_run)
    gate_clause = f" (declared proof of gate `{gate}`)" if gate else ""
    message = f"CI check run `{name}` concluded `{conclusion}`{gate_clause}"
    if title:
        message = f"{message} — {title}"

    evidence = [f"check run: {name} ({conclusion})"]
    url = _check_run_url(check_run)
    if url:
        evidence.append(url)
    evidence.extend(ci_evidence_lines(excerpt))

    return make_finding(
        tool=CI_TOOL,
        rule_id=f"check-run/{conclusion}",
        category=CI_CATEGORY,
        severity=_UNBLAMED_SEVERITY,
        confidence="likely",
        message=message,
        path=path,
        start_line=line,
        end_line=line,
        source="ci",
        evidence=evidence,
        introduced_by_pr="unknown",
    )


# ── declared gate mapping (D10) ───────────────────────────────────────────────


def declared_check_run(
    gate: str,
    *,
    mapping: Mapping[str, str],
    check_runs: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Return the completed check run the repo *declared* as proof of ``gate``.

    Exact, declared, completed — all three. No mapping means no match however
    suggestive the names are; that absence is the whole security property of
    D10, so it is expressed as an early return rather than a scoring rule.
    """
    declared = str(mapping.get(gate) or "").strip()
    if not declared:
        return None
    for check_run in check_runs:
        if _check_run_name(check_run) != declared:
            continue
        if str(check_run.get("status") or "completed").strip().lower() != "completed":
            continue
        return dict(check_run)
    return None


def substitute_declared_gates(
    outcomes: Sequence[AnalyzerOutcome],
    *,
    mapping: Mapping[str, str],
    check_runs: Sequence[Mapping[str, Any]],
) -> tuple[list[AnalyzerOutcome], list[GateSubstitution]]:
    """Replace gates CI already proved with ``satisfied-by-ci`` rows.

    Returns the rewritten outcome list — same length, same order, one row per
    gate — and the substitutions that were applied. Replacing rather than
    appending is what removes the duplicate/``unavailable`` noise the issue
    names; a caller that appended would report the gate twice.
    """
    if not mapping or not check_runs:
        return list(outcomes), []

    updated: list[AnalyzerOutcome] = []
    substitutions: list[GateSubstitution] = []
    for outcome in outcomes:
        if outcome.status not in _REPLACEABLE:
            updated.append(outcome)
            continue
        check_run = declared_check_run(outcome.name, mapping=mapping, check_runs=check_runs)
        if check_run is None or _check_run_conclusion(check_run) != _PASSING_CONCLUSION:
            updated.append(outcome)
            continue
        substitution = GateSubstitution(
            gate=outcome.name,
            check_run=_check_run_name(check_run),
            conclusion=_check_run_conclusion(check_run),
            url=_check_run_url(check_run),
        )
        substitutions.append(substitution)
        updated.append(
            dataclasses.replace(
                outcome,
                status=SATISFIED_BY_CI,
                output=substitution.summary,
                exit_code=None,
            )
        )
    return updated, substitutions


def declared_gate_findings(
    outcomes: Sequence[AnalyzerOutcome],
    *,
    mapping: Mapping[str, str],
    check_runs: Sequence[Mapping[str, Any]],
) -> list[Finding]:
    """Findings for declared gates whose CI check run did *not* pass.

    The mirror of :func:`substitute_declared_gates`: a gate mergeCraft could not
    run and CI proved broken must not vanish into an ``unavailable`` row, but it
    also must not be silently upgraded to a green one. It is reported.
    """
    if not mapping or not check_runs:
        return []
    findings: list[Finding] = []
    for outcome in outcomes:
        if outcome.status not in _REPLACEABLE:
            continue
        check_run = declared_check_run(outcome.name, mapping=mapping, check_runs=check_runs)
        if check_run is None:
            continue
        finding = check_run_to_finding(check_run, gate=outcome.name)
        if finding is not None:
            findings.append(finding)
    return findings


# ── SARIF artifacts ───────────────────────────────────────────────────────────


def _ci_sarif_manifest(artifact: str) -> AnalyzerManifest:
    """A synthetic manifest so CI SARIF reuses the catalog's SARIF parser.

    ``parse_sarif`` reads exactly three things off a manifest — the tool id, the
    taxonomy category, and the native-severity map. Building those here reuses
    the audited parser instead of forking a second SARIF reader that would drift
    from it. The manifest never enters the catalog, so ``make catalog-check``
    neither sees nor validates it.
    """
    return AnalyzerManifest(
        id=f"{CI_TOOL}:{artifact}",
        category="lint",
        languages=[],
        detect=DetectRules(files=["**/*"]),
        command=[],
        scope="diff",
        parser="sarif",
        supports_fix=False,
        default_enabled=False,
        version="0",
        runtime="managed",
        timeout_s=1,
        trust="untrusted",
        severity_map={"error": "Major", "warning": "Minor", "note": "Trivial"},
        provenance={},
        network_allowlist=[],
    )


def _as_unblamed_ci_finding(finding: Finding, *, tool: str) -> Finding:
    """Re-stamp an analyzer-shaped finding as unblamed CI evidence.

    Severity is capped rather than preserved: SARIF uploaded by someone else's
    pipeline describes the tree, not this diff, so it may inform a reviewer but
    must never block a merge on its own (D11). The message is redacted and the
    fingerprint recomputed from the redacted text, so the stored hash always
    matches the text a human will read.
    """
    message = redact_secrets(finding.message)
    severity = finding.severity if finding.severity in {"Minor", "Trivial"} else _UNBLAMED_SEVERITY
    return finding.model_copy(
        update={
            "tool": tool,
            "source": "ci",
            "severity": severity,
            "introduced_by_pr": "unknown",
            "message": message,
            "evidence": [redact_secrets(item) for item in finding.evidence],
            "fingerprint": finding_fingerprint(path=finding.path, body=message),
        }
    )


def sarif_findings(raw: str, *, artifact: str, repo_root: Path) -> list[Finding]:
    """Parse a SARIF artifact produced by the consumer's CI into CI findings.

    Raises whatever ``parse_sarif`` raises for a malformed document — the
    caller decides whether a bad artifact is fatal (it is not, at the MCP
    boundary) rather than having that decision baked in here.
    """
    tool = f"{CI_TOOL}:{artifact}"
    parsed = parse_sarif(raw, manifest=_ci_sarif_manifest(artifact), repo_root=repo_root)
    return [_as_unblamed_ci_finding(finding, tool=tool) for finding in parsed]


# ── recording on the run's state ──────────────────────────────────────────────


def _evidence_state(state: ToolState) -> CiEvidenceState:
    from mergecraft.mcp.tool_state import CiEvidenceState

    if state.ci_evidence is None:
        state.ci_evidence = CiEvidenceState()
    return state.ci_evidence


def record_ci_findings(state: ToolState, findings: Iterable[Finding]) -> list[Finding]:
    """Record CI findings on the run, deduplicated on fingerprint.

    Deduplication matters because the approval gate and the evidence packet are
    monotone in blockers: the same failure read twice (once off a check run,
    once off the clustered logs) must not count twice. Returns the findings
    that were newly added.
    """
    evidence = _evidence_state(state)
    seen = {str(row.get("fingerprint")) for row in evidence.findings}
    added: list[Finding] = []
    for finding in findings:
        if finding.fingerprint in seen:
            continue
        seen.add(finding.fingerprint)
        evidence.findings.append(finding.model_dump())
        added.append(finding)
    if added:
        logger.info("ci evidence: recorded {} finding(s) from CI", len(added))
    return added


def record_gate_substitutions(
    state: ToolState, substitutions: Iterable[GateSubstitution]
) -> list[dict[str, Any]]:
    """Record which gates a declared CI result satisfied, for audit."""
    evidence = _evidence_state(state)
    rows = [substitution.as_row() for substitution in substitutions]
    evidence.substitutions.extend(rows)
    for row in rows:
        logger.info(
            "ci evidence: gate {} reported satisfied by CI check run {}",
            row["gate"],
            row["checkRun"],
        )
    return rows


def ci_evidence_findings(state: ToolState) -> list[Finding]:
    """Return the run's recorded CI findings as typed ``Finding`` objects.

    Malformed rows are dropped with a debug line rather than raised: CI
    evidence is supplementary, and one bad row must not take down the packet
    that carries the rest of the run's evidence.
    """
    evidence = state.ci_evidence
    if evidence is None:
        return []
    typed: list[Finding] = []
    for row in evidence.findings:
        if not isinstance(row, dict):
            continue
        try:
            typed.append(Finding.model_validate(row))
        except (FindingValidationError, ValueError) as err:
            logger.debug("ci evidence: dropping malformed finding row: {}", err)
    return typed


__all__ = [
    "CI_CATEGORY",
    "CI_TOOL",
    "SATISFIED_BY_CI",
    "GateSubstitution",
    "check_run_to_finding",
    "ci_evidence_findings",
    "ci_evidence_lines",
    "declared_check_run",
    "declared_gate_findings",
    "record_ci_findings",
    "record_gate_substitutions",
    "sarif_findings",
    "substitute_declared_gates",
]
