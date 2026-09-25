"""The local criterion heuristic stops passing negated criteria (EV1 → EV3).

With no Jev client the runner scores each criterion with a local text
heuristic. It dropped the cue words that carry a negation — ``no`` was thrown
away by the ``len(token) > 2`` filter and ``not`` is in ``_STOPWORDS`` — so
``"No error is shown"`` and ``"Error is not shown"`` both reduce to the tokens
``["error", "shown"]`` and **pass** on a page that says ``"Error shown"``.
The same predicate decides reproduce mode, so a negated repro expectation
claims a reproduction on the opposite page.

The fail-closed answer is not a cleverer guess (the doc promises the CLI never
invents a local verdict): a negated criterion is ``unverified`` with a named
reason, and a negated reproduce expectation is ``partial`` — never
``reproduced``. The two hard-coded ``"still visible"`` / ``"mismatch"``
special cases are unchanged.

All red today: no negation guard exists, so the audited criteria report
``pass`` / ``reproduced`` at call time. The positive criterion and the
``"still visible"`` cases below are regression guards that already pass.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.verify.fake_driver import FakeBrowserDriver
from tests.verify.support import import_verify, make_input, require_symbol

# The audit's two criteria plus the rest of the cue set the fix pins on the raw
# lowercased criterion before tokenising: ``no``, ``not``, ``never``, ``none``,
# ``nothing``, ``without``, ``cannot`` and ``n't`` contractions.
_NEGATED_CRITERIA = (
    "No error is shown",
    "Error is not shown",
    "Error is never shown",
    "None of the errors are shown",
    "Nothing is shown",
    "Error without a warning is shown",
    "Error cannot appear",
    "Error isn't shown",
)


def _run() -> Any:
    return require_symbol(import_verify("runner"), "run_verify_behavior")


async def _verify(criterion: str, page: str) -> Any:
    return await _run()(
        make_input(
            mode="verify",
            acceptance_criteria=[criterion],
            credential_env_names=[],
        ),
        driver=FakeBrowserDriver(page_text=page),
        offline=True,
    )


async def test_audited_negated_criteria_against_the_opposite_page_are_unverified() -> None:
    """``"No error is shown"`` / ``"Error is not shown"`` on a page that literally
    says ``"Error shown"``: neither may be ``pass``, both are ``unverified`` with
    a named reason, and the report is not ``pass``."""
    report = await _verify("No error is shown", "Error shown")
    assert report.acceptance_criteria[0].status == "unverified"
    assert report.status == "partial"
    assert report.status != "pass"
    assert report.skipped_or_unverified

    other = await _verify("Error is not shown", "Error shown")
    assert other.acceptance_criteria[0].status == "unverified"
    assert other.status != "pass"


@pytest.mark.parametrize("criterion", _NEGATED_CRITERIA)
async def test_every_negation_cue_is_never_a_local_pass(criterion: str) -> None:
    """A criterion carrying a negation cue can never be a local ``pass`` on a
    page whose positive words match — token absence is not evidence of truth."""
    report = await _verify(criterion, "Error shown")

    assert report.acceptance_criteria[0].status == "unverified"
    assert report.status == "partial"
    reasons = " ".join(report.skipped_or_unverified).lower()
    assert reasons, "an unverified criterion must name why"
    assert criterion.lower() in reasons or "negat" in reasons


async def test_plain_positive_criterion_still_passes_on_a_matching_page() -> None:
    """Regression guard: the negation guard must not swallow an ordinary
    positive criterion — ``"Error shown"`` on ``"Error shown"`` stays ``pass``."""
    report = await _verify("Error shown", "Error shown")

    assert report.acceptance_criteria[0].status == "pass"
    assert report.status == "pass"
    assert report.skipped_or_unverified == []


async def test_negated_reproduce_expectation_is_partial_never_reproduced() -> None:
    """Reproduce mode with a negated expectation must not claim a reproduction
    on the page that shows the opposite; it is ``partial`` and names the skip."""
    report = await _run()(
        make_input(
            mode="reproduce",
            repro_notes="Error is not shown",
            acceptance_criteria=[],
            credential_env_names=[],
        ),
        driver=FakeBrowserDriver(page_text="Error shown"),
        offline=True,
    )

    assert report.status != "reproduced"
    assert report.status == "partial"
    assert report.skipped_or_unverified


async def test_still_visible_special_case_is_unchanged_when_it_is_still_visible() -> None:
    """The hard-coded ``"still visible"`` special case stays: it still ``fail``s
    when the page still shows it, and the negation guard does not intercept it."""
    report = await _verify("image still visible on screen", "image still visible on screen")

    assert report.acceptance_criteria[0].status == "fail"
    assert report.status == "fail"


async def test_still_visible_special_case_is_unchanged_when_it_is_gone() -> None:
    report = await _verify("image still visible on screen", "image removed")

    assert report.acceptance_criteria[0].status == "pass"
    assert report.status == "pass"
