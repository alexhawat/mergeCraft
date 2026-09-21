"""Security vocabularies — asserted through their consumers (N4).

``SECURITY_MESSAGE_PATTERNS`` feeds ``findings/severity_rubric.py`` and
``DOMAIN_HINT_GROUPS`` feeds ``findings/dedup.py``. Pinning the literal strings
would fail on any legitimate vocabulary change, so these tests drive the
consumers and assert the observable outcomes: a security-signal message is
never capped by the maintainability/docs rules, a message in one domain-hint
group merges with a paraphrase in the same group, and messages from unrelated
groups stay apart.
"""

from __future__ import annotations

import pytest

from tests.findings.support import make_finding

#: Messages naming a vulnerability class the security lane must catch.
_SECURITY_SIGNALS: tuple[str, ...] = (
    "Remote code execution via unsafe eval",
    "Path traversal in the static file handler",
    "SSRF through a user-controlled callback URL",
    "CSRF token is not validated",
    "XXE expansion in the XML parser",
    "Privilege escalation via a misordered check",
    "Prototype pollution in the config merge",
    "Open redirect on the login callback",
    "Hardcoded key committed in the source",
    "Unsafe deserialization of a session payload",
    "Pickle load of untrusted bytes",
    "SQL injection in the query builder",
    "Stored XSS in the comment renderer",
)


@pytest.mark.parametrize("message", _SECURITY_SIGNALS)
def test_security_signal_messages_infer_the_security_category(message: str) -> None:
    """A message matching a security pattern is classified as Security."""
    from mergecraft.findings.severity_rubric import infer_category_from_message

    assert infer_category_from_message(message) == "Security & Privacy"


def test_security_signal_keeps_a_finding_uncapped() -> None:
    """A security word pre-empts the maintainability and docs capping rules.

    Without ``SECURITY_MESSAGE_PATTERNS`` the docs rule would cap this row to
    ``Trivial``; with it the ``Critical`` assertion stands.
    """
    from mergecraft.findings.severity_rubric import apply_severity_rubric

    finding = make_finding(
        category="Maintainability & Code Quality",
        severity="Critical",
        message="Hardcoded secret in the docstring of the client",
        path="src/util.py",
        start_line=1,
        end_line=1,
    )

    normalized = apply_severity_rubric(finding, model_assigned_severity="Critical")

    assert normalized.severity == "Critical"


def test_docs_nit_still_caps_without_a_security_signal() -> None:
    """Negative control: the same shape without a security word is capped."""
    from mergecraft.findings.severity_rubric import apply_severity_rubric

    finding = make_finding(
        category="Maintainability & Code Quality",
        severity="Critical",
        message="Typo in the docstring of the client",
        path="src/util.py",
        start_line=1,
        end_line=1,
    )

    normalized = apply_severity_rubric(finding, model_assigned_severity="Critical")

    assert normalized.severity != "Critical"


def test_domain_hint_groups_merge_two_findings_in_one_domain() -> None:
    """Two paraphrases sharing one domain token on each side still merge."""
    from mergecraft.findings.dedup import dedupe_findings

    findings = [
        make_finding(
            message="missing timeout retry handler",
            path="src/app.py",
            start_line=1,
            end_line=1,
        ),
        make_finding(
            message="loop timeout missing handler",
            path="src/app.py",
            start_line=1,
            end_line=1,
        ),
    ]

    assert len(dedupe_findings(findings)) == 1


def test_findings_from_unrelated_domains_stay_apart() -> None:
    """No shared domain group and no content overlap means two findings."""
    from mergecraft.findings.dedup import dedupe_findings

    findings = [
        make_finding(
            message="timeout missing on the retry loop",
            path="src/app.py",
            start_line=1,
            end_line=1,
        ),
        make_finding(
            message="hardcoded key committed in source",
            path="src/app.py",
            start_line=1,
            end_line=1,
        ),
    ]

    assert len(dedupe_findings(findings)) == 2
