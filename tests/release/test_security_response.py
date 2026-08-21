"""W8.1 — security-response and vulnerability-disclosure path (#382).

``SECURITY.md`` already has a short private-reporting paragraph. W8.2 must add
a maintainer security-response process beyond that existing heading.
"""

from __future__ import annotations

import re

from tests.ci.workflow_support import read_text


def _security() -> str:
    return read_text("SECURITY.md")


def test_security_md_has_security_response_process() -> None:
    """Happy: SECURITY.md documents a security-response process (not only reporting)."""
    text = _security()
    assert re.search(r"security[\s-]+response", text, re.IGNORECASE), (
        "SECURITY.md must document a security-response process (#382)"
    )


def test_security_md_has_coordinated_vulnerability_disclosure() -> None:
    """Happy: vulnerability disclosure is coordinated, not only 'do not open an issue'."""
    text = _security()
    assert re.search(
        r"coordinated disclosure|vulnerability disclosure",
        text,
        re.IGNORECASE,
    ), "SECURITY.md must name a vulnerability-disclosure path (#382)"


def test_security_md_already_points_at_private_advisories() -> None:
    """GREEN: private GitHub Security Advisories reporting already exists; W8.2 extends it."""
    collapsed = re.sub(r"\s+", " ", _security().casefold())
    assert "acknowledg" in collapsed
    assert "advisories" in collapsed or "security advisory" in collapsed


def test_security_response_is_not_only_review_only_boundary() -> None:
    """Error contract: the new section is distinct from the review-only product boundary."""
    text = _security()
    match = re.search(r"##[^\n]*security[\s-]+response[^\n]*", text, re.IGNORECASE)
    assert match is not None, "SECURITY.md needs a security-response heading"
    assert "review-only" not in match.group(0).casefold()
