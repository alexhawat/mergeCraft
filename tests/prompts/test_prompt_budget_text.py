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
* **#899** — ``Mode.version`` hashes the prompt actually rendered, so a run's
  recorded version names the text the reviewer received; the default render
  still matches ``prompt_version_for``.

These assertions fail until PD2; do not xfail: RED is the point.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from mergecraft.modes import (
    PR_SUMMARY_FORMAT,
    IncrementalReview,
    Mode,
    Plan,
    Review,
    compute_modes,
    compute_prompt_version,
    prompt_version_for,
)

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


def test_zero_inline_budget_renders_the_zero_slot() -> None:
    """``inlineBudget: 0`` renders ``0`` — the prompt agrees with the resolver.

    A configured ``0`` means every finding overflows, so the reviewer's prompt
    must show the same ``0`` the resolver and the tool use, not the default 8.
    The ``None`` case (config-key name, no number) stays pinned by
    ``test_none_renders_the_key_name_and_no_marker_or_number`` above.
    """
    prompt = _review_prompt(inline_budget=0)
    assert "budget cap — 0" in prompt, (
        "inline_budget=0 must render the zero slot, not fall back to the default"
    )
    assert "analyzers.inlineBudget" not in prompt, (
        "inline_budget=0 must render the number, not the unset key name"
    )
    assert "${" not in prompt, "the INLINE_BUDGET marker must always expand"


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


# ── #899 — a run's recorded version must name the prompt that actually ran ───

_MODE_MODULES = (Review, IncrementalReview, Plan)
_INLINE_BUDGET_MARKER = "${INLINE_BUDGET}"


def _budget_marker_modes() -> set[str]:
    """Names of the built-in modes whose raw template embeds ``${INLINE_BUDGET}``.

    Derived from the templates rather than asserted as a literal, so a later
    change that adds the marker to another mode is covered automatically.
    """
    return {module.NAME for module in _MODE_MODULES if _INLINE_BUDGET_MARKER in module.TEMPLATE}


def _versions_by_mode(*, inline_budget: int | None) -> dict[str, str]:
    return {mode.name: mode.version for mode in _render(inline_budget)}


def test_distinct_configured_budgets_produce_distinct_versions() -> None:
    """A verdict must be attributable to the prompt that actually ran (#899).

    ``Mode.version`` hashed the ``inline_budget=None`` baseline, so two runs
    configured with different inline budgets recorded the *same* version even
    though the reviewer received different prompt text. A mode whose template
    embeds ``${INLINE_BUDGET}`` renders a budget-dependent body and so must
    version differently per budget; a marker-free mode's body (and version) is
    legitimately budget-independent. The expected set is derived from the
    templates so the pin stays honest if another mode gains the marker.
    """
    default = _versions_by_mode(inline_budget=None)
    five = _versions_by_mode(inline_budget=5)
    seven = _versions_by_mode(inline_budget=7)

    marker_modes = _budget_marker_modes()
    assert marker_modes, (
        f"no built-in mode embeds {_INLINE_BUDGET_MARKER}; the budget marker vanished"
    )

    for module in _MODE_MODULES:
        name = module.NAME
        versions = {default[name], five[name], seven[name]}
        if name in marker_modes:
            assert len(versions) == 3, (
                f"{name} embeds {_INLINE_BUDGET_MARKER} but its version does not move "
                f"with the configured budget: default={default[name]!r}, "
                f"5={five[name]!r}, 7={seven[name]!r} (#899)"
            )
        else:
            assert len(versions) == 1, (
                f"{name} does not embed {_INLINE_BUDGET_MARKER}, so its version must "
                f"not move with the budget: {versions!r}"
            )


def test_version_hashes_the_rendered_prompt_body() -> None:
    """Version is a function of the body, per ``compute_prompt_version``'s contract.

    Identical rendered bodies give identical versions and any body change gives a
    different one — so ``Mode.version`` must equal the hash of the prompt it
    ships, not a separately tracked field. Together with the budget-distinctness
    test above, that is what makes the recorded version name the prompt the
    reviewer received.
    """
    for inline_budget in (None, 5, 7):
        for mode in _render(inline_budget):
            assert mode.prompt is not None, f"{mode.name} rendered no prompt"
            assert mode.version == compute_prompt_version(mode.prompt), (
                f"{mode.name} at inline_budget={inline_budget!r}: version is not the "
                "content hash of its rendered prompt body"
            )
    assert compute_prompt_version("same body") == compute_prompt_version("same body")
    assert compute_prompt_version("same body") != compute_prompt_version("same body ")


def test_default_render_version_matches_prompt_version_for_baseline() -> None:
    """The default (no-budget) render is still the ``prompt_version_for`` baseline.

    ``compute_modes`` without a budget expands the same ``inline_budget=None``
    render that ``prompt_version_for`` hashes with a sentinel agent, so the two
    must agree for every built-in mode — the #899 fix must not move the default
    version a caller records.
    """
    for mode in _render_modes("opencode"):
        assert mode.version == prompt_version_for(mode.name), (
            f"{mode.name}: default compute_modes version diverged from "
            "prompt_version_for() — the baseline contract moved"
        )
