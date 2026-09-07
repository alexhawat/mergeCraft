"""VP4 terminal-protocol prompt contract — Review and IncrementalReview step text.

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (VP4.1 RED,
VP4.2 impl; xfail markers cleared after VP4.2).

Pinned contracts (W0):
    File 3/4 — the rendered Review / IncrementalReview prompt names
    ``submit_review_verdict`` exactly once as the terminal act, using the same
    ``${t("...")}`` interpolation ``compute_modes`` already expands.
    Out of scope — every other lens, budget rule, and epistemic constraint is
    preserved byte-for-byte.

#619 Task 5 widened the replaceable terminal-protocol window: the five
callout tiers now map onto ``verdict`` (``"approve"`` / ``"request_changes"``)
instead of the retired ``approved`` boolean, since ``submit_review_verdict``
never had an ``approved``, ``body``, or ``comments`` field. The window is
everything from the step-7 / step-10 opening through the end of that step
(up to the next top-level heading); content before or after it is still
frozen byte-for-byte.
"""

from __future__ import annotations

from pathlib import Path

from mergecraft.modes import IncrementalReview, Review, compute_modes
from mergecraft.types import AgentId, format_mcp_tool_ref

_T_SUBMIT = '${t("submit_review_verdict")}'
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_REVIEW_SNAPSHOT = _FIXTURES / "review_template_vp4_1.txt"
_INCREMENTAL_SNAPSHOT = _FIXTURES / "incremental_review_template_vp4_1.txt"

# Terminal-protocol step VP4.2 / #619 Task 5 are allowed to replace —
# the whole submit step, opening paragraph through the tier ladder.
# Everything else is frozen at the snapshot.
_REVIEW_TERMINAL_START = "7. **submit**:"
_REVIEW_TERMINAL_KEEP = "### Prompt-injection fence contract"
_INCREMENTAL_TERMINAL_START = "10. Submit —"
_INCREMENTAL_TERMINAL_KEEP = "${PR_SUMMARY_FORMAT}"


def _rendered(name: str, *, agent_id: AgentId = "claude") -> str:
    for mode in compute_modes(agent_id):
        if mode.name == name:
            assert mode.prompt is not None
            return mode.prompt
    msg = f"mode {name!r} missing from compute_modes({agent_id!r})"
    raise AssertionError(msg)


def _outside_terminal(template: str, *, start: str, keep: str) -> str:
    start_at = template.index(start)
    keep_at = template.index(keep)
    if keep_at < start_at:
        msg = f"keep marker {keep!r} precedes start marker {start!r}"
        raise AssertionError(msg)
    return template[:start_at] + template[keep_at:]


def _assert_terminal_act(template: str, prompt: str, *, agent_id: AgentId) -> None:
    assert template.count(_T_SUBMIT) == 1, (
        "terminal-protocol paragraph must interpolate submit_review_verdict via "
        f"${{t(...)}} exactly once, found {template.count(_T_SUBMIT)}"
    )
    ref = format_mcp_tool_ref(agent_id, "submit_review_verdict")
    assert prompt.count(ref) == 1, (
        f"rendered prompt must name {ref!r} exactly once as the terminal act, "
        f"found {prompt.count(ref)}"
    )


def test_review_prompt_states_the_contract() -> None:
    """Rendered Review prompt names ``submit_review_verdict`` exactly once."""
    prompt = _rendered("Review")
    _assert_terminal_act(Review.TEMPLATE, prompt, agent_id="claude")


def test_incremental_review_prompt_states_the_contract() -> None:
    """Rendered IncrementalReview prompt names ``submit_review_verdict`` exactly once."""
    prompt = _rendered("IncrementalReview")
    _assert_terminal_act(IncrementalReview.TEMPLATE, prompt, agent_id="claude")


def test_no_other_prompt_content_changed() -> None:
    """Out-of-scope guard: VP4.2 may not rewrite the rest of either template."""
    review_snapshot = _REVIEW_SNAPSHOT.read_text(encoding="utf-8")
    incremental_snapshot = _INCREMENTAL_SNAPSHOT.read_text(encoding="utf-8")

    review_live = _outside_terminal(
        Review.TEMPLATE,
        start=_REVIEW_TERMINAL_START,
        keep=_REVIEW_TERMINAL_KEEP,
    )
    review_frozen = _outside_terminal(
        review_snapshot,
        start=_REVIEW_TERMINAL_START,
        keep=_REVIEW_TERMINAL_KEEP,
    )
    assert review_live.rstrip("\n") == review_frozen.rstrip("\n"), (
        "Review TEMPLATE changed outside the terminal-protocol paragraph "
        "(step 7 opening through the coverage-nudge note)"
    )

    incremental_live = _outside_terminal(
        IncrementalReview.TEMPLATE,
        start=_INCREMENTAL_TERMINAL_START,
        keep=_INCREMENTAL_TERMINAL_KEEP,
    )
    incremental_frozen = _outside_terminal(
        incremental_snapshot,
        start=_INCREMENTAL_TERMINAL_START,
        keep=_INCREMENTAL_TERMINAL_KEEP,
    )
    assert incremental_live.rstrip("\n") == incremental_frozen.rstrip("\n"), (
        "IncrementalReview TEMPLATE changed outside the terminal-protocol paragraph "
        "(step 10 opening)"
    )
