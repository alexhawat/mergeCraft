"""W3 — ``SECURITY.md`` is the public review-only contract (D9 / #350).

The guarantee lives in ``SECURITY.md`` (and CHANGELOG).
Not README.md. Not AGENTS.md. File 7 owns those (D6).
"""

from __future__ import annotations

import re

from tests.ci.workflow_support import REPO_ROOT

_SECURITY_MD = REPO_ROOT / "SECURITY.md"
_REVIEW_ONLY = re.compile(r"review[\s-]+only", re.IGNORECASE)


def _security_text() -> str:
    assert _SECURITY_MD.is_file(), "SECURITY.md must exist at the repo root"
    return _SECURITY_MD.read_text(encoding="utf-8")


def _collapsed(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold())


def test_security_md_states_review_only_guarantee() -> None:
    """D9 — public product contract names mergeCraft as review-only."""
    text = _security_text()
    assert _REVIEW_ONLY.search(text), (
        "SECURITY.md must state the review-only guarantee (D9); do not put it in README.md"
    )


def test_security_md_forbids_source_edits_commits_pushes_and_code_changing_prs() -> None:
    """#350 — reviewer must not edit source, commit, push, or open a code-changing PR."""
    collapsed = _collapsed(_security_text())
    assert "edit" in collapsed
    assert "source" in collapsed or "reviewed" in collapsed
    assert "commit" in collapsed
    assert "push" in collapsed
    assert "pull request" in collapsed or "code-changing" in collapsed


def test_security_md_allows_identify_investigate_verify_explain_prioritize_suggest() -> None:
    """#350 product definition — identify / investigate / verify / explain / prioritize / suggest."""
    collapsed = _collapsed(_security_text())
    for verb in ("identify", "investigate", "verify", "explain", "prioritize", "suggest"):
        assert verb in collapsed, f"SECURITY.md must allow review verb {verb!r}"
