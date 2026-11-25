"""Withdrawn findings: markers withdraw, prose only informs (#1562, D9).

``withdrawn_fingerprints`` returns the fingerprints stamped into
``<!-- mergecraft-finding:v1:… -->`` markers. A plain-text line was hashed with
``path=""`` and could never equal a real finding's fingerprint (fingerprints
include the path), and the ``len(fp) == 24`` guard was always true. The prose in
the section still reaches the verifier brief verbatim, which is covered here
too.
"""

from __future__ import annotations

from mergecraft.agents.verifier import _withdrawn_section
from mergecraft.analyzers.scope import withdrawn_fingerprints
from mergecraft.review_taxonomy import WITHDRAWN_FINDINGS_HEADING

_FINGERPRINT = "0123456789abcdef01234567"
_MARKER = f"<!-- mergecraft-finding:v1:{_FINGERPRINT} -->"


def _learnings(body: str) -> str:
    """Return a learnings file with ``body`` under the withdrawn heading."""
    return f"# Learnings\n\n{WITHDRAWN_FINDINGS_HEADING}\n\n{body}\n"


def test_marker_lines_yield_their_fingerprints() -> None:
    """A machine-readable marker is the one withdrawal that always works."""
    assert _FINGERPRINT in withdrawn_fingerprints(_learnings(_MARKER))


def test_plain_text_lines_yield_no_fingerprints() -> None:
    """Two prose lines and one marker withdraw exactly one finding."""
    body = "Prose withdrawal one.\nAnother prose withdrawal.\n" + _MARKER

    assert withdrawn_fingerprints(_learnings(body)) == frozenset({_FINGERPRINT})


def test_withdrawn_section_text_still_reaches_the_verifier_brief() -> None:
    """Prose under the heading is pasted verbatim, even though it withdraws nothing."""
    section = _withdrawn_section(_learnings("Credit the retry is intentional, not a bug."))

    assert WITHDRAWN_FINDINGS_HEADING in section
    assert "Credit the retry is intentional, not a bug." in section
