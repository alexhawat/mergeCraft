"""DG1 deduplication — one defect, one finding (G1).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG1).
Implementation: **DG1.2** — dedup on normalized location + symbol + category, then
semantic body comparison, before the judge.
"""

from __future__ import annotations

from tests.findings.support import make_finding


def test_two_lenses_reporting_one_defect_produce_one_finding() -> None:
    """Two review lenses flag the same defect once each — publish one finding."""
    from mergecraft.analyzers.dedup import dedupe_findings

    findings = [
        make_finding(
            tool="security-lens",
            rule_id="sql-injection",
            message="User input reaches SQL query unsanitized",
            path="src/db/query.py",
            start_line=22,
            end_line=24,
            source="agent",
        ),
        make_finding(
            tool="correctness-lens",
            rule_id="unsafe-query",
            message="SQL built from request parameter without binding",
            path="src/db/query.py",
            start_line=22,
            end_line=24,
            source="agent",
        ),
    ]

    deduped = dedupe_findings(findings)

    assert len(deduped) == 1


def test_same_defect_different_wording_is_deduped() -> None:
    """Paraphrases of one defect at the same place collapse to a single finding."""
    from mergecraft.analyzers.dedup import dedupe_findings

    findings = [
        make_finding(
            message="Missing timeout on the retry loop",
            path="src/app.py",
            start_line=42,
            end_line=42,
        ),
        make_finding(
            message="The retry loop never sets a timeout",
            path="src/app.py",
            start_line=42,
            end_line=42,
        ),
    ]

    deduped = dedupe_findings(findings)

    assert len(deduped) == 1


def test_distinct_defects_on_one_line_are_not_merged() -> None:
    """Different categories on the same line stay separate — the false-merge guard."""
    from mergecraft.analyzers.dedup import dedupe_findings

    findings = [
        make_finding(
            category="Security & Privacy",
            rule_id="hardcoded-secret",
            message="API token committed in source",
            path="src/config.py",
            start_line=7,
            end_line=7,
        ),
        make_finding(
            category="Maintainability & Code Quality",
            rule_id="magic-number",
            message="Unnamed numeric literal in config default",
            path="src/config.py",
            start_line=7,
            end_line=7,
        ),
    ]

    deduped = dedupe_findings(findings)

    assert len(deduped) == 2


def test_same_category_distinct_defects_on_one_line_are_not_merged() -> None:
    """Same category on one line with different defects stay separate."""
    from mergecraft.analyzers.dedup import dedupe_findings

    findings = [
        make_finding(
            category="Functional Correctness",
            rule_id="sql-injection",
            message="Unsanitized user input reaches SQL query",
            path="src/db/query.py",
            start_line=22,
            end_line=22,
        ),
        make_finding(
            category="Functional Correctness",
            rule_id="missing-validation",
            message="Missing validation on SQL query parameters",
            path="src/db/query.py",
            start_line=22,
            end_line=22,
        ),
    ]

    deduped = dedupe_findings(findings)

    assert len(deduped) == 2
