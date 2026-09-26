"""N14 / C8 / D8 — budget and stale-affordance prompt text (PD1 RED).

Wave plan: ``.ignorelocal/waves/44-prompts-docs-contracts-wave-plan.md`` (PD1).
Locked decisions:

* **PD-D4** — ``compute_modes`` gains ``inline_budget: int | None``; the live
  value is interpolated and ``None`` renders the key name
  (``analyzers.inlineBudget``) with no number.
* **PD-D5** — the verifier cap is ``review.verificationBudget`` scaled per round
  by ``review.roundBudgets``; the prompt names the keys, never a number.
* **PD-D6** — the diff-coverage-nudge note is deleted.
* **PD-D11** — the Fix-button rationale is removed.

These assertions fail until PD2; do not xfail: RED is the point.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from mergecraft.modes import PR_SUMMARY_FORMAT, Mode, compute_modes

_BUDGET_CAP_DIGIT_RE = re.compile(r"budget cap\D{0,12}\d")
_FIX_BUTTON_RE = re.compile(r"Fix[-\s]?button", re.IGNORECASE)

# ``compute_modes`` gains ``inline_budget`` in PD2.4; the generic signature
# keeps this RED suite type-checking against today's narrower callable while
# still failing at runtime until the keyword lands.
_Renderer = Callable[..., list[Mode]]
_render_modes: _Renderer = compute_modes


def _render(inline_budget: int | None = None) -> list[Mode]:
    return _render_modes("claude", inline_budget=inline_budget)


def _rendered_surfaces() -> dict[str, str]:
    surfaces = {"PR_SUMMARY_FORMAT": PR_SUMMARY_FORMAT}
    for mode in compute_modes("claude"):
        if mode.prompt is not None:
            surfaces[mode.name] = mode.prompt
    return surfaces


def _review_prompt(inline_budget: int | None = None) -> str:
    for mode in _render(inline_budget):
        if mode.name == "Review":
            assert mode.prompt is not None, "Review rendered no prompt"
            return mode.prompt
    msg = "Review mode missing from compute_modes"
    raise AssertionError(msg)


def _single_span_diff(left: str, right: str) -> tuple[str, str]:
    """Return the two one-span substrings that differ between *left* and *right*."""
    limit = min(len(left), len(right))
    prefix = 0
    while prefix < limit and left[prefix] == right[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < limit - prefix and left[len(left) - 1 - suffix] == right[len(right) - 1 - suffix]
    ):
        suffix += 1
    return left[prefix : len(left) - suffix], right[prefix : len(right) - suffix]


def test_no_digit_follows_the_budget_cap_phrase() -> None:
    offenders = sorted(
        name for name, text in _rendered_surfaces().items() if _BUDGET_CAP_DIGIT_RE.search(text)
    )
    assert not offenders, (
        f"these surfaces bake a number into the budget-cap text: {offenders} (N14 / PD-D4)"
    )


def test_inline_budget_value_is_interpolated() -> None:
    with_five = _review_prompt(inline_budget=5)
    with_seven = _review_prompt(inline_budget=7)
    assert with_five != with_seven, (
        "compute_modes(inline_budget=...) did not change the rendered prompt (PD-D4)"
    )
    left, right = _single_span_diff(with_five, with_seven)
    assert (left, right) == ("5", "7"), (
        "the inline budget must be the only difference between the two renders; "
        f"got {(left, right)!r}"
    )
    assert "${" not in with_five, "the INLINE_BUDGET marker must always expand"
    assert "${" not in with_seven, "the INLINE_BUDGET marker must always expand"


def test_none_renders_the_key_name_and_no_marker_or_number() -> None:
    prompt = _review_prompt(inline_budget=None)
    assert "analyzers.inlineBudget" in prompt, (
        "inline_budget=None must render the key name `analyzers.inlineBudget` (PD-D4)"
    )
    assert "${" not in prompt, "the INLINE_BUDGET marker must always expand"
    assert "(8)" not in prompt, "inline_budget=None must not bake today's default"


def test_default_render_has_no_leftover_marker() -> None:
    """Mirror ``tests/test_modes.py``: no rendered prompt leaves a ``${...}`` marker."""
    for mode in compute_modes("claude"):
        assert "${" not in (mode.prompt or ""), (
            f"{mode.name} left an unexpanded ${{...}} marker at the default render"
        )


def test_verifier_cap_names_the_config_keys() -> None:
    prompt = _review_prompt()
    assert "review.verificationBudget" in prompt, (
        "the verifier-cap sentence must name review.verificationBudget (PD-D5)"
    )
    assert "review.roundBudgets" in prompt, (
        "the verifier-cap sentence must name the per-round scaler review.roundBudgets (PD-D5)"
    )


def test_no_prompt_mentions_a_diff_coverage_nudge() -> None:
    offenders = sorted(
        name for name, text in _rendered_surfaces().items() if "diff-coverage nudge" in text.lower()
    )
    assert not offenders, f"these surfaces still describe the removed nudge: {offenders}"


def test_no_prompt_mentions_a_fix_button() -> None:
    offenders = sorted(
        name for name, text in _rendered_surfaces().items() if _FIX_BUTTON_RE.search(text)
    )
    assert not offenders, (
        f"these surfaces still justify behaviour by a Fix button: {offenders} (PD-D11)"
    )
