"""Finding taxonomy, fingerprints, and shared review-artifact text.

The three triage axes and the fix-prompt preamble below are the single source of
truth: ``modes.py`` renders them into the review-format prompt and
``tests/test_modes.py`` asserts the prompt still names every value, so the
taxonomy cannot drift away from what the reviewer is told to emit.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final, Literal

# ── triage axes ───────────────────────────────────────────────────────────────

FINDING_CATEGORIES: Final[tuple[str, ...]] = (
    "Functional Correctness",
    "Data Integrity & Atomicity",
    "Security & Privacy",
    "Stability & Availability",
    "Performance & Scalability",
    "Maintainability & Code Quality",
)

FINDING_SEVERITIES: Final[tuple[str, ...]] = ("Critical", "Major", "Minor", "Trivial")

FINDING_EFFORTS: Final[tuple[str, ...]] = ("Quick win", "Heavy lift", "Low value")

FINDING_CONFIDENCES: Final[tuple[str, ...]] = ("certain", "likely", "possible")

FindingSource = Literal["analyzer", "agent", "ci"]

# A finding at one of these grades never occupies an inline anchor — it belongs
# in the body's Nitpicks section instead.
BODY_ONLY_SEVERITY: Final[str] = "Trivial"
BODY_ONLY_EFFORT: Final[str] = "Low value"

# ── shared artifact text ──────────────────────────────────────────────────────

# Stamped onto every machine-readable fix prompt so a downstream fix-agent
# inherits the "treat findings as hypotheses" contract even when it only ever
# sees the posted review, not this repo's mode prompts.
VERIFY_FIRST_PREAMBLE: Final[str] = (
    "Verify each finding against current code. Fix only still-valid issues, skip "
    "the rest with a brief reason, keep changes minimal, and validate."
)

# Learnings heading under which a reviewer's retracted findings accumulate, so a
# false positive is refuted once rather than re-litigated every run.
WITHDRAWN_FINDINGS_HEADING: Final[str] = "## Withdrawn review findings (known non-issues)"

# ── finding fingerprints ──────────────────────────────────────────────────────

FINDING_MARKER_PREFIX: Final[str] = "<!-- mergecraft-finding:v1:"

_MARKER_RE = re.compile(r"<!-- mergecraft-finding:v1:[0-9a-f]+ -->")  # S6
_WHITESPACE_RE = re.compile(r"\s+")


def finding_fingerprint(*, path: str, body: str) -> str:
    """Return a stable content hash for one inline finding.

    Whitespace and case are normalized so re-wrapping a comment does not change
    the hash, letting a later run recognize a finding it already raised.
    """
    stripped = _MARKER_RE.sub("", body)
    normalized = _WHITESPACE_RE.sub(" ", stripped).strip().casefold()
    return hashlib.sha256(f"{path}\n{normalized}".encode()).hexdigest()[:24]


def stamp_finding_fingerprint(*, path: str, body: str, fingerprint: str | None = None) -> str:
    """Append the dedup marker to ``body``, unless it already carries one."""
    if _MARKER_RE.search(body):
        return body
    resolved = fingerprint or finding_fingerprint(path=path, body=body)
    marker = f"{FINDING_MARKER_PREFIX}{resolved} -->"
    return f"{body}\n\n{marker}" if body else marker


__all__ = [
    "BODY_ONLY_EFFORT",
    "BODY_ONLY_SEVERITY",
    "FINDING_CATEGORIES",
    "FINDING_CONFIDENCES",
    "FINDING_EFFORTS",
    "FINDING_MARKER_PREFIX",
    "FINDING_SEVERITIES",
    "VERIFY_FIRST_PREAMBLE",
    "WITHDRAWN_FINDINGS_HEADING",
    "FindingSource",
    "finding_fingerprint",
    "stamp_finding_fingerprint",
]
