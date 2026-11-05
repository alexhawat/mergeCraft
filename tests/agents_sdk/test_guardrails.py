"""Unit tests for Agents SDK output guardrails."""

from __future__ import annotations

from mergecraft.agents_sdk.guardrails import (
    filter_guarded_findings,
    finding_looks_like_secret,
    path_in_change_set,
)
from mergecraft.agents_sdk.types import ReviewFinding, ReviewFindingsReport


def test_path_in_change_set_accepts_prefix_and_exact() -> None:
    allowed = frozenset({"src/app.py", "docs/readme.md"})
    assert path_in_change_set("src/app.py", allowed)
    assert path_in_change_set("./src/app.py", allowed)
    assert path_in_change_set("src/app.py", allowed)
    assert not path_in_change_set("src/other.py", allowed)


def test_secret_probe_blocks_github_token_shape() -> None:
    finding = ReviewFinding(
        severity="Major",
        file="src/app.py",
        line=1,
        message="Remove hardcoded ghp_abcdefghijklmnopqrst",
        suggested_fix="Use env var",
    )
    assert finding_looks_like_secret(finding)


def test_filter_guarded_findings_drops_out_of_scope_and_secrets() -> None:
    report = ReviewFindingsReport(
        findings=[
            ReviewFinding(
                severity="Major",
                file="outside.py",
                message="bug",
            ),
            ReviewFinding(
                severity="Minor",
                file="src/app.py",
                message="ok",
            ),
            ReviewFinding(
                severity="Critical",
                file="src/app.py",
                message="leaked sk-1234567890abcdefghij",
            ),
        ]
    )
    filtered, violations = filter_guarded_findings(
        report,
        allowed_paths=frozenset({"src/app.py"}),
    )
    assert len(filtered.findings) == 1
    assert filtered.findings[0].severity == "Minor"
    assert len(violations) == 2
