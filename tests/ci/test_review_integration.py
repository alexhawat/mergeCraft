"""Review integration — CI failures section, budget, truncation (K3)."""

from __future__ import annotations

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
        category="Stability & Availability",
        severity="Major",
        confidence="likely",
        message=message,
        path=path,
        start_line=line,
        end_line=line,
        source="ci",
    )


def test_ci_failures_section_lists_clustered_root_causes() -> None:
    intelligence = import_module("mergecraft.ci.intelligence")
    fixture = load_fixture("multi_job_single_root_cause.json")
    payload = intelligence.intelligence_from_failures(
        fixture["jobs"],
        pr_diff_paths=["tests/analyzers/test_adapters_supply_chain.py"],
    )
    section = payload["section"]
    assert CI_SECTION_HEADING in section
    assert "Verify (tests" in section
    assert "**Flaky verdict:**" in section
    assert "**Blame verdict:**" in section
    assert payload["stats"]["clusterCount"] == 1
    assert payload["stats"]["failureCount"] == len(fixture["jobs"])


def test_analyze_ci_failures_orchestrator_path_renders_verdict_lines() -> None:
    intelligence = import_module("mergecraft.ci.intelligence")
    unrelated = load_fixture("pre_existing_unrelated_failure.json")
    payload = intelligence.intelligence_from_failures(
        unrelated["jobs"],
        pr_diff_paths=unrelated["pr_diff_paths"],
        base_branch_status=unrelated["base_branch"]["same_fingerprint_conclusion"],
    )
    section = payload["section"]
    assert "**Flaky verdict:**" in section
    assert "**Blame verdict:** probably_not_this_pr" in section
    assert "probably not this pr" in section.lower()
    assert payload["preMergeSummary"]
    assert payload["stats"]["prAttributedCount"] == 0


def test_analyze_ci_failures_end_to_end_from_raw_jobs() -> None:
    review_ci = import_module("mergecraft.ci.review")
    intelligence = import_module("mergecraft.ci.intelligence")
    fixture = load_fixture("blame_maps_to_diff_hunk.json")
    reports, stats, overflow = review_ci.analyze_ci_failures(
        [fixture["job"]],
        pr_diff_paths=fixture["pr_diff_paths"],
    )
    payload = intelligence.build_ci_intelligence_payload(
        reports,
        stats,
        overflow,
        raw_failures=[fixture["job"]],
    )
    assert stats.cluster_count == 1
    assert stats.pr_attributed_count == 1
    assert overflow == 0
    assert "**Blame verdict:** caused_by_pr" in payload["section"]
    assert len(payload["comments"]) == 1


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


def test_truncation_statement_when_failures_exceed_cap() -> None:
    review_ci = import_module("mergecraft.ci.review")
    fixture = load_fixture("truncation_overflow.json")
    overflow = len(fixture["failed_runs"]) - DEFAULT_TRUNCATION_CAP
    section = review_ci.render_ci_failures_section(
        [],
        raw_failures=fixture["failed_runs"][:DEFAULT_TRUNCATION_CAP],
        overflow=overflow,
    )
    assert str(overflow) in section or "not analyzed" in section.lower()


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
