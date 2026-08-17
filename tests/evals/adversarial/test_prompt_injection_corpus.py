"""EV3 — the adversarial prompt-injection corpus: the fence holds on every case.

RED suite for PR EV3 (sub-wave EV3.1; implementation EV3.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

The injection fence shipped in W4 (``mergecraft.utils.fence``: nonce-bound
``render_untrusted`` / ``fence_unless_trusted`` with delimiter neutralization)
and is unit-tested there. What does not exist yet is the **corpus that proves
the fence holds against a growing set of hostile shapes** (plan §EV3) — one
hostile case per attack vector, run through the fence path on every suite run
so a future fence regression is caught here, not in production.

Pinned contract (all new in EV3.2, module ``mergecraft.evals.adversarial``):

- ``DEFAULT_ADVERSARIAL_CORPUS_DIR`` = ``evals/cases/adversarial/`` — one JSON
  case file per hostile shape. (The bank's ``list_cases`` only reads
  top-level ``*.md`` files, so the subdirectory cannot leak into structural
  replay.)
- ``AdversarialCase`` — ``case_id``, ``vector`` (one of ``pr_body`` /
  ``review_comment`` / ``commit_message`` / ``poisoned_context`` /
  ``misleading_tests`` / ``generated_code``), ``payload`` (the hostile field
  text, including a forged closing-delimiter attempt), ``author``,
  ``author_association`` (untrusted for every corpus case), ``legit_marker``
  (legitimate content — e.g. the seeded bug's diff line — that must survive
  fencing), ``expected_decision`` (corpus-recorded truth for
  decision-bearing cases).
- ``discover_adversarial_cases(corpus_dir=DEFAULT_ADVERSARIAL_CORPUS_DIR)``.
- ``check_fence(case) -> FenceCheck`` — runs the case through the real fence
  mechanics and reports ``fenced`` (payload wrapped in the nonce-bound
  untrusted block), ``forged_delimiters_neutralized`` (the payload cannot
  terminate its own fence early), ``legit_content_preserved`` and
  ``handled_as`` (``"reviewed"`` | ``"classified"``).

The discipline is structural and keyless — the tests assert the
fencing/classification **mechanics**, not a live model's judgement, so
``skipped: no live gate`` applies cleanly. New symbols are imported lazily
inside helpers/tests (ImportError at RED time; collection stays clean). Each
test asserts its vector is present in the corpus — an empty corpus is a
failure, never a vacuous pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from mergecraft.evals.adversarial import AdversarialCase

_XFAIL_EV3_2 = pytest.mark.xfail(
    reason="green after EV3.2: adversarial corpus + mergecraft.evals.adversarial fence harness",
    strict=False,
)


def _cases_for(vector: str) -> list[AdversarialCase]:
    """Every corpus case for one attack vector — at least one must exist.

    A vector with zero cases is a failure, not a vacuous pass: the corpus
    existing but silently dropping an attack shape is exactly the regression
    this suite exists to catch.
    """
    from mergecraft.evals.adversarial import discover_adversarial_cases

    cases = [case for case in discover_adversarial_cases() if case.vector == vector]
    assert cases, f"adversarial corpus carries no {vector!r} case"
    return cases


# ── injection vectors: the fence holds ──


@_XFAIL_EV3_2
def test_fence_holds_against_injection_in_pr_body() -> None:
    from mergecraft.evals.adversarial import check_fence

    for case in _cases_for("pr_body"):
        outcome = check_fence(case)
        assert outcome.fenced, f"{case.case_id}: pr_body payload rendered outside the fence"
        assert outcome.forged_delimiters_neutralized, (
            f"{case.case_id}: payload can terminate its own fence early"
        )


@_XFAIL_EV3_2
def test_fence_holds_against_injection_in_review_comment() -> None:
    from mergecraft.evals.adversarial import check_fence

    for case in _cases_for("review_comment"):
        outcome = check_fence(case)
        assert outcome.fenced, f"{case.case_id}: review_comment payload rendered outside the fence"
        assert outcome.forged_delimiters_neutralized, (
            f"{case.case_id}: payload can terminate its own fence early"
        )


@_XFAIL_EV3_2
def test_fence_holds_against_injection_in_commit_message() -> None:
    from mergecraft.evals.adversarial import check_fence

    for case in _cases_for("commit_message"):
        outcome = check_fence(case)
        assert outcome.fenced, f"{case.case_id}: commit_message payload rendered outside the fence"
        assert outcome.forged_delimiters_neutralized, (
            f"{case.case_id}: payload can terminate its own fence early"
        )


# ── the fence must not help the attack ──


@_XFAIL_EV3_2
def test_poisoned_context_does_not_suppress_a_real_finding() -> None:
    """A poisoned context block is fenced, and the case's real seeded defect
    (``legit_marker``) survives fencing intact — the poison must not push the
    real finding out of the review material, and the corpus-recorded verdict
    stays ``block``."""
    from mergecraft.evals.adversarial import check_fence

    for case in _cases_for("poisoned_context"):
        outcome = check_fence(case)
        assert outcome.fenced
        assert outcome.legit_content_preserved, (
            f"{case.case_id}: fencing the poisoned context dropped the real defect"
        )
        assert case.expected_decision == "block"


@_XFAIL_EV3_2
def test_misleading_tests_do_not_manufacture_approval() -> None:
    """Tests that merely *claim* coverage (misleading names/comments) are
    untrusted content like any other: fenced, and the corpus-recorded verdict
    is ``block`` — never ``approve``."""
    from mergecraft.evals.adversarial import check_fence

    for case in _cases_for("misleading_tests"):
        outcome = check_fence(case)
        assert outcome.fenced
        assert case.expected_decision == "block", (
            f"{case.case_id}: misleading tests manufactured an approval-shaped verdict"
        )


@_XFAIL_EV3_2
def test_generated_code_is_classified_not_reviewed() -> None:
    """Generated code is *classified*, not reviewed as human-authored — the
    harness reports ``handled_as == "classified"`` for the generated-code
    vector rather than running it through the reviewer path."""
    from mergecraft.evals.adversarial import check_fence

    for case in _cases_for("generated_code"):
        outcome = check_fence(case)
        assert outcome.handled_as == "classified", (
            f"{case.case_id}: generated code was handled as {outcome.handled_as!r}, not classified"
        )
