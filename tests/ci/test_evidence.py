"""RED suite for #36 — existing CI results as analyzer / gate evidence (W5).

Four properties carry the issue's acceptance criteria and this plan's locked
decisions:

* **D10** — a CI check run may change a mergeCraft gate's reported outcome only
  when the repo *declared* the mapping. Fuzzy name matching is explicitly out of
  scope, so an undeclared check run named exactly like a gate must still be
  context, never gate satisfaction.
* **D11** — findings derived from CI carry the CI-intelligence blame verdicts
  through to ``Finding.introduced_by_pr``. Flaky and pre-existing failures are
  *reported*, never *blamed*: they must never reach a blocking severity, because
  the approval gate is monotone in blockers.
* **D12** — ``Finding`` is read and produced here, never extended. ``extra=
  "forbid"`` makes any field change breaking for three separate wave plans.
* **Convention 8** — nothing leaves the process unredacted; log excerpts are
  truncated *and* redacted before they enter a finding.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.finding import Finding
from mergecraft.analyzers.run import AnalyzerOutcome
from mergecraft.ci.evidence import (
    SATISFIED_BY_CI,
    check_run_to_finding,
    ci_evidence_findings,
    ci_evidence_lines,
    declared_check_run,
    declared_gate_findings,
    record_ci_findings,
    record_gate_substitutions,
    sarif_findings,
    substitute_declared_gates,
)
from mergecraft.ci.verification import annotate_not_caused_by_pr
from mergecraft.mcp.tool_state import init_tool_state
from tests.ci.support import CANARY_SECRET

if TYPE_CHECKING:
    from pathlib import Path


def _check_run(
    *,
    name: str = "Verify (drift gates)",
    conclusion: str = "success",
    status: str = "completed",
    url: str | None = "https://github.com/acme/demo/runs/1",
) -> dict[str, Any]:
    return {
        "id": 1,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "html_url": url,
        "output": {"title": "3 gates", "summary": "lint, typecheck, tests"},
    }


def _unavailable(name: str = "lint") -> AnalyzerOutcome:
    return AnalyzerOutcome(
        name=name,
        command="make lint",
        status="unavailable",
        output="make: command not found",
    )


def _cannot_run(name: str = "lint") -> AnalyzerOutcome:
    return AnalyzerOutcome(
        name=name,
        command="make lint",
        status="declared-but-cannot-run",
        output="shell is disabled on pull-request events",
    )


_SARIF = json.dumps(
    {
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "ruff", "rules": [{"id": "F401"}]}},
                "results": [
                    {
                        "ruleId": "F401",
                        "level": "error",
                        "message": {"text": "unused import `os`"},
                        "locations": [
                            {
                                "physicalLocation": {
                                    "artifactLocation": {"uri": "src/app.py"},
                                    "region": {"startLine": 3, "endLine": 3},
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }
)


# ── W5.1 — a CI outcome becomes a Finding ────────────────────────────────────


def test_ci_check_run_becomes_a_finding() -> None:
    """A failed consumer check run normalises into a valid ``source: ci`` finding."""
    finding = check_run_to_finding(_check_run(conclusion="failure"))

    assert finding is not None
    assert isinstance(finding, Finding)
    assert finding.source == "ci"
    assert finding.tool == "ci"
    assert "Verify (drift gates)" in finding.message
    assert finding.evidence, "a CI finding must cite the check run it came from"


def test_successful_check_run_produces_no_finding() -> None:
    """Green CI is evidence, not a finding — a passing run must not manufacture one."""
    assert check_run_to_finding(_check_run(conclusion="success")) is None
    assert check_run_to_finding(_check_run(conclusion="skipped")) is None
    assert check_run_to_finding(_check_run(status="in_progress", conclusion="")) is None


# ── W5.2 — SARIF artifacts reuse the existing parser ──────────────────────────


def test_ci_sarif_artifact_becomes_findings(tmp_path: Path) -> None:
    """A SARIF artifact from the consumer's CI parses through ``analyzers/parsers``."""
    findings = sarif_findings(_SARIF, artifact="ruff-sarif", repo_root=tmp_path)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.source == "ci"
    assert finding.path == "src/app.py"
    assert finding.rule_id == "F401"
    assert "ruff-sarif" in finding.tool


def test_ci_sarif_findings_are_never_blamed_on_this_pr(tmp_path: Path) -> None:
    """SARIF from someone else's pipeline says nothing about *who* introduced it (D11)."""
    findings = sarif_findings(_SARIF, artifact="ruff-sarif", repo_root=tmp_path)

    assert [f.introduced_by_pr for f in findings] == ["unknown"]
    assert all(f.severity not in {"Critical", "Major"} for f in findings)


# ── W5.3 — substitution requires a declared mapping (D10) ─────────────────────


def test_gate_substitution_requires_a_declared_mapping() -> None:
    """An undeclared CI result is context, never gate satisfaction.

    The check run here is named *exactly* like the gate. Without a declared
    mapping that similarity must buy it nothing — this is the assertion that
    keeps "CI was green" from silently satisfying a gate CI never ran.
    """
    outcomes = [_unavailable("lint")]
    check_runs = [_check_run(name="lint", conclusion="success")]

    updated, substitutions = substitute_declared_gates(outcomes, mapping={}, check_runs=check_runs)

    assert substitutions == []
    assert [o.status for o in updated] == ["unavailable"]
    assert declared_check_run("lint", mapping={}, check_runs=check_runs) is None


def test_failed_declared_check_run_does_not_satisfy_the_gate() -> None:
    """Only a *successful* declared run may stand in for a gate mergeCraft cannot run."""
    outcomes = [_cannot_run("lint")]
    check_runs = [_check_run(name="Verify (lint)", conclusion="failure")]

    updated, substitutions = substitute_declared_gates(
        outcomes,
        mapping={"lint": "Verify (lint)"},
        check_runs=check_runs,
    )

    assert substitutions == []
    assert [o.status for o in updated] == ["declared-but-cannot-run"]


def test_substitution_never_overwrites_a_gate_that_actually_ran() -> None:
    """A gate mergeCraft executed here outranks any CI claim about it."""
    executed = AnalyzerOutcome(
        name="lint", command="make lint", status="failed", output="E501", exit_code=1
    )
    updated, substitutions = substitute_declared_gates(
        [executed],
        mapping={"lint": "Verify (lint)"},
        check_runs=[_check_run(name="Verify (lint)", conclusion="success")],
    )

    assert substitutions == []
    assert [o.status for o in updated] == ["failed"]


# ── W5.4 — the declared mapping removes the unavailable row ───────────────────


@pytest.mark.parametrize("row", ["unavailable", "declared-but-cannot-run"])
def test_declared_mapping_removes_the_unavailable_row(row: str) -> None:
    """CI-proved gates report as satisfied-by-CI instead of duplicating noise."""
    outcomes = [_unavailable("lint") if row == "unavailable" else _cannot_run("lint")]

    updated, substitutions = substitute_declared_gates(
        outcomes,
        mapping={"lint": "Verify (lint)"},
        check_runs=[_check_run(name="Verify (lint)", conclusion="success")],
    )

    assert len(updated) == 1, "substitution replaces the row; it never appends a second one"
    assert updated[0].status == SATISFIED_BY_CI
    assert updated[0].passed is True
    assert updated[0].ran is True
    assert "Verify (lint)" in updated[0].output
    assert "https://github.com/acme/demo/runs/1" in updated[0].output

    assert len(substitutions) == 1
    assert substitutions[0].gate == "lint"
    assert substitutions[0].check_run == "Verify (lint)"


# ── W5.5 / W5.6 — reported, not blamed (D11) ─────────────────────────────────


def test_flaky_failure_is_reported_not_blamed() -> None:
    """A failure the flaky detector flags must never reach a blocking severity.

    ``annotate_not_caused_by_pr`` is the CI-intelligence rule; this asserts the
    property the rule exists for, at the severity the approval gate reads.
    """
    from mergecraft.agents.gates import BLOCKING_SEVERITIES

    blamed = check_run_to_finding(_check_run(conclusion="failure"))
    assert blamed is not None
    flaky = annotate_not_caused_by_pr(blamed)

    assert flaky.introduced_by_pr == "false"
    assert flaky.severity not in BLOCKING_SEVERITIES


def test_flaky_ci_finding_never_blocks_the_approval_gate() -> None:
    """The property, end to end: a flaky CI finding cannot fail a run's verdict."""
    from mergecraft.agents.gates import decide_approval

    blamed = check_run_to_finding(_check_run(conclusion="failure"))
    assert blamed is not None
    flaky = annotate_not_caused_by_pr(blamed)

    assert decide_approval([flaky], run_succeeded=True, tier="trusted") != "failure"


def test_not_caused_by_pr_annotation_survives_normalisation() -> None:
    """The annotation round-trips through the recorded (dict) evidence store."""
    state = init_tool_state(owner="acme", name="demo", dir=".")
    blamed = check_run_to_finding(_check_run(conclusion="failure"))
    assert blamed is not None
    flaky = annotate_not_caused_by_pr(blamed)

    record_ci_findings(state, [flaky])
    restored = ci_evidence_findings(state)

    assert [f.introduced_by_pr for f in restored] == ["false"]
    assert [f.severity for f in restored] == [flaky.severity]
    assert [f.fingerprint for f in restored] == [flaky.fingerprint]


def test_recording_is_idempotent_on_fingerprint() -> None:
    """Re-recording the same CI finding must not double-count it for the gate."""
    state = init_tool_state(owner="acme", name="demo", dir=".")
    finding = check_run_to_finding(_check_run(conclusion="failure"))
    assert finding is not None

    record_ci_findings(state, [finding])
    record_ci_findings(state, [finding])

    assert len(ci_evidence_findings(state)) == 1


def test_declared_gate_findings_report_a_failing_mapped_check_run() -> None:
    """A declared gate CI proved *broken* is reported — unblamed — not hidden."""
    findings = declared_gate_findings(
        [_cannot_run("lint")],
        mapping={"lint": "Verify (lint)"},
        check_runs=[_check_run(name="Verify (lint)", conclusion="failure")],
    )

    assert len(findings) == 1
    assert findings[0].source == "ci"
    assert findings[0].introduced_by_pr == "unknown"
    assert findings[0].severity not in {"Critical", "Major"}
    assert "lint" in findings[0].message


def test_declared_gate_findings_ignore_undeclared_check_runs() -> None:
    """D10 again, on the finding side: no mapping, no derived gate finding."""
    assert (
        declared_gate_findings(
            [_cannot_run("lint")],
            mapping={},
            check_runs=[_check_run(name="lint", conclusion="failure")],
        )
        == []
    )


# ── W5.7 — truncation + redaction (convention 8) ─────────────────────────────


def test_log_excerpts_are_truncated_and_redacted() -> None:
    """No secret-shaped string survives into a finding's evidence list."""
    noisy = "\n".join([f"line {i}" for i in range(200)] + [f"token={CANARY_SECRET}"])

    lines = ci_evidence_lines(noisy, limit=5)

    assert len(lines) <= 5
    joined = "\n".join(lines)
    assert CANARY_SECRET not in joined
    assert len(joined) <= 2000


def test_check_run_finding_evidence_is_redacted() -> None:
    """The redaction boundary holds on the path a real run actually takes."""
    finding = check_run_to_finding(
        _check_run(conclusion="failure"),
        log_excerpt=f"##[error] auth failed\napi_key={CANARY_SECRET}",
    )

    assert finding is not None
    blob = "\n".join([finding.message, *finding.evidence])
    assert CANARY_SECRET not in blob


# ── W5.8 — Finding is never extended (D12) ───────────────────────────────────


def test_no_new_finding_fields_introduced(tmp_path: Path) -> None:
    """CI evidence uses ``evidence`` and ``source``; it adds no field to ``Finding``."""
    expected = {
        "tool",
        "rule_id",
        "category",
        "severity",
        "confidence",
        "message",
        "path",
        "start_line",
        "end_line",
        "fingerprint",
        "evidence",
        "remediation",
        "autofix",
        "introduced_by_pr",
        "source",
        "cluster_id",
    }
    assert set(Finding.model_fields) == expected

    produced = [
        check_run_to_finding(_check_run(conclusion="failure")),
        *sarif_findings(_SARIF, artifact="ruff-sarif", repo_root=tmp_path),
    ]
    for finding in produced:
        assert finding is not None
        assert set(finding.model_dump()) == expected


def test_gate_substitutions_are_recorded_for_audit() -> None:
    """A substitution that changed a reported outcome must be inspectable."""
    state = init_tool_state(owner="acme", name="demo", dir=".")
    _, substitutions = substitute_declared_gates(
        [_unavailable("lint")],
        mapping={"lint": "Verify (lint)"},
        check_runs=[_check_run(name="Verify (lint)", conclusion="success")],
    )

    record_gate_substitutions(state, substitutions)

    assert state.ci_evidence is not None
    assert state.ci_evidence.substitutions[0]["gate"] == "lint"
    assert state.ci_evidence.substitutions[0]["checkRun"] == "Verify (lint)"
