"""W1.1 — scope axis and one blocking predicate (implementation W2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.agents import gates
from mergecraft.analyzers.finding import Finding, FindingValidationError, make_finding
from mergecraft.mcp.verdict import _blocks_approve, build_validation_state
from tests.review_record.conftest import (
    base_finding_kwargs,
    make_scoped_finding,
    make_test_finding,
    require_symbol,
)

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding as FindingType


def _blocking_findings(findings: list[FindingType]) -> list[FindingType]:
    return list(require_symbol(gates, "blocking_findings")(findings))


def test_finding_defaults_scope_change() -> None:
    finding = make_test_finding(source="analyzer")
    assert getattr(finding, "scope", None) == "change"


def test_existing_analyzer_row_loads_unchanged_without_scope_in_payload() -> None:
    payload = make_test_finding(source="analyzer").model_dump()
    payload.pop("scope", None)
    loaded = Finding.model_validate(payload)
    assert loaded.source == "analyzer"
    assert getattr(loaded, "scope", "change") == "change"


def test_trajectory_source_validates() -> None:
    make_finding(**base_finding_kwargs(source="trajectory", path=""))


def test_unknown_source_still_raises() -> None:
    with pytest.raises((FindingValidationError, ValueError)):
        make_finding(**base_finding_kwargs(source="not-a-source"))  # type: ignore[arg-type]


def test_blocking_findings_drops_run_scoped_critical() -> None:
    run_critical = make_scoped_finding(
        scope="run", severity="Critical", rule_id="ignored-tool-error"
    )
    assert _blocking_findings([run_critical]) == []


def test_blocking_findings_applies_causality_policy() -> None:
    pre_existing = make_scoped_finding(
        scope="change",
        severity="Major",
        introduced_by_pr="false",
        rule_id="PRE-EXISTING",
    )
    assert _blocking_findings([pre_existing]) == []


def test_has_blocker_and_blocks_approve_agree_on_mixed_scope_set() -> None:
    """#447-shaped regression — one predicate must not disagree with the other."""
    findings = [
        make_scoped_finding(scope="run", severity="Critical", rule_id="unresolved-failure"),
        make_scoped_finding(
            scope="change",
            severity="Major",
            introduced_by_pr="false",
            rule_id="PRE-EXISTING",
        ),
        make_scoped_finding(
            scope="change",
            severity="Major",
            introduced_by_pr="true",
            rule_id="CHANGE-SCOPED",
        ),
    ]
    state = build_validation_state(analyzer_findings=findings)
    gates_answer = bool(_blocking_findings(findings))
    verdict_answer = _blocks_approve(state)
    has_blocker_answer = gates._has_blocker(findings)
    assert gates_answer == verdict_answer == has_blocker_answer


def test_decide_approval_success_on_run_only_findings() -> None:
    run_only = [
        make_scoped_finding(scope="run", severity="Critical", rule_id="ignored-tool-error"),
        make_scoped_finding(scope="run", severity="Major", rule_id="repeated-tool-loop"),
    ]
    conclusion = gates.decide_approval(run_only, run_succeeded=True, tier="trusted")
    assert conclusion == "success"
