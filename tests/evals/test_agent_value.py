"""EV2 — per-lens agent value: unique accepted findings per lens.

RED suite for PR EV2 (sub-wave EV2.1; implementation EV2.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

A lens (one review agent/perspective) earns its cost only by finding things no
other lens found. Because ``score_findings``' matching is one-to-one within a
single run, "unique" is only meaningful **across per-lens runs** — so the
pinned contract takes typed per-lens attribution as input (the ``dict`` key is
the lens identity; the AP work on this branch is what tags production findings
with it — global convention 7: production emits normalized fields, scoring
happens here):

- ``LensValue`` (new model in ``evals/scoring.py``): ``lens: str``,
  ``accepted: int`` (baseline issues this lens's run located),
  ``unique_accepted: int`` (located issues **no other lens's** run located).
- ``unique_accepted_findings_per_lens(findings_by_lens, issues, *,
  slack=DEFAULT_LINE_SLACK) -> dict[str, LensValue]`` — every submitted lens
  is a key in the result, even one that contributed nothing unique.

Both symbols are imported lazily inside the tests (ImportError at RED time;
collection stays clean). Keyless and pure: ``skipped: no live gate``.

Reconciled post-EV2.2 (2026-08-17): EV2.2 (commit ``3d64488``) made all tests
in this file XPASS; the non-strict ``green after EV2.2`` xfail markers were
removed, so every test here is now a clean real pass.

"""

from __future__ import annotations

from mergecraft.evals.scoring import BaselineIssue, ReportedFinding


def _issue(identifier: str, *, start: int) -> BaselineIssue:
    return BaselineIssue(id=identifier, path="src/app.py", start_line=start, end_line=start + 1)


def _finding(*, start: int) -> ReportedFinding:
    return ReportedFinding(path="src/app.py", start_line=start, end_line=start + 1)


def _issues() -> list[BaselineIssue]:
    # 100-line spacing: the default ±3 slack can never bleed across issues.
    return [_issue("iss-a", start=10), _issue("iss-b", start=110), _issue("iss-c", start=210)]


def test_unique_accepted_findings_per_lens() -> None:
    """security locates A+B, correctness locates A, style locates C:
    security's unique value is exactly B; correctness adds nothing unique."""
    from mergecraft.evals.scoring import unique_accepted_findings_per_lens

    values = unique_accepted_findings_per_lens(
        {
            "security": [_finding(start=10), _finding(start=110)],
            "correctness": [_finding(start=10)],
            "style": [_finding(start=210)],
        },
        _issues(),
    )

    assert values["security"].accepted == 2
    assert values["security"].unique_accepted == 1
    assert values["correctness"].accepted == 1
    assert values["correctness"].unique_accepted == 0
    assert values["style"].accepted == 1
    assert values["style"].unique_accepted == 1


def test_a_lens_that_finds_nothing_unique_is_visible() -> None:
    """A lens with zero unique accepted findings still appears in the report —
    a lens that earns nothing must be *visible as a zero*, never silently
    omitted (a missing key reads as 'not run', which is a different claim)."""
    from mergecraft.evals.scoring import unique_accepted_findings_per_lens

    values = unique_accepted_findings_per_lens(
        {
            "security": [_finding(start=10)],
            # Only re-finds what security already found — nothing unique.
            "correctness": [_finding(start=10)],
            # Finds nothing at all.
            "docs": [],
        },
        _issues(),
    )

    assert set(values) == {"security", "correctness", "docs"}
    assert values["correctness"].accepted == 1
    assert values["correctness"].unique_accepted == 0
    assert values["docs"].accepted == 0
    assert values["docs"].unique_accepted == 0
