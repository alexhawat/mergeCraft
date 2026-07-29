"""Review integration — CI failures section, budget, truncation (K3)."""

from __future__ import annotations

import pytest

from mergecraft.review_taxonomy import finding_fingerprint
from tests.analyzers.support import import_module as import_analyzer_module
from tests.ci.support import (
    CI_SECTION_HEADING,
    DEFAULT_TRUNCATION_CAP,
    INLINE_BUDGET,
    import_module,
    load_fixture,
)


def _ci_finding(path: str, line: int, message: str) -> object:
    finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
    return finding_mod.make_finding(
        tool="ci",
        rule_id="pytest-failure",
        category="Reliability & Testing",
        severity="Major",
        confidence="likely",
        message=message,
        path=path,
        start_line=line,
        end_line=line,
        source="ci",
    )


@pytest.mark.xfail(
    reason="green after K3: CI failures section renders clustered causes", strict=False
)
def test_ci_failures_section_lists_clustered_root_causes() -> None:
    review_ci = import_module("mergecraft.ci.review")
    cluster = import_module("mergecraft.ci.cluster")
    normalize = import_module("mergecraft.ci.normalize")
    fixture = load_fixture("multi_job_single_root_cause.json")
    normalized = [normalize.normalize_failure(job) for job in fixture["jobs"]]
    clustered = cluster.cluster_failures(normalized)
    section = review_ci.render_ci_failures_section(clustered)
    assert CI_SECTION_HEADING in section
    assert "Verify (tests" in section
    assert (
        "flaky" in section.lower()
        or "root cause" in section.lower()
        or "cluster" in section.lower()
    )


@pytest.mark.xfail(
    reason="green after K3: CI and analyzer findings merge on same line", strict=False
)
def test_ci_finding_clusters_with_analyzer_on_same_line() -> None:
    cluster = import_analyzer_module("mergecraft.analyzers.cluster")
    message = "import error in adapter module"
    path = "tests/analyzers/test_adapters_supply_chain.py"
    line = 10
    ci = _ci_finding(path, line, message)
    finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
    ruff = finding_mod.make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="likely",
        message=message,
        path=path,
        start_line=line,
        end_line=line,
        source="analyzer",
        fingerprint=finding_fingerprint(path=path, body=message),
    )
    grouped = cluster.cluster_findings([ci, ruff])
    assert len(grouped) == 1
    assert len(grouped[0].evidence) >= 2


@pytest.mark.xfail(reason="green after K3: truncation count is visible (K5)", strict=False)
def test_truncation_statement_when_failures_exceed_cap() -> None:
    review_ci = import_module("mergecraft.ci.review")
    fixture = load_fixture("truncation_overflow.json")
    section = review_ci.render_ci_failures_section(
        [],
        raw_failures=fixture["failed_runs"],
        truncation_cap=DEFAULT_TRUNCATION_CAP,
    )
    overflow = len(fixture["failed_runs"]) - DEFAULT_TRUNCATION_CAP
    assert str(overflow) in section or "not analyzed" in section.lower()


@pytest.mark.xfail(reason="green after K3: CI section respects D14 inline budget", strict=False)
def test_ci_section_respects_inline_budget() -> None:
    review_ci = import_module("mergecraft.ci.review")
    budget = import_analyzer_module("mergecraft.analyzers.budget")
    cluster = import_module("mergecraft.ci.cluster")
    normalize = import_module("mergecraft.ci.normalize")
    fixture = load_fixture("truncation_overflow.json")
    normalized = [normalize.normalize_failure(run) for run in fixture["failed_runs"]]
    clustered = cluster.cluster_failures(normalized)
    section = review_ci.render_ci_failures_section(clustered)
    placement = budget.place_findings(clustered, inline_budget=INLINE_BUDGET)
    assert len(placement.inline) <= INLINE_BUDGET
    assert CI_SECTION_HEADING in section
