"""C3 — prompts request only finding fields the schemas accept (PD1 RED).

Wave plan: ``.ignorelocal/waves/44-prompts-docs-contracts-wave-plan.md`` (PD1).
Locked decision **PD-D2** — collateral renders in the inline body as the
**Also update:** list; the prompts must stop pointing at a ``collateral``
finding field, because every agent-facing schema is ``extra="forbid"`` without
it (``agents/verifier.py:176``). The body-only **Also update:** mechanism is
correct and stays.

The last test is a read-only pin on plan 39's schema: ``AgentFinding`` must keep
rejecting ``collateral`` so a future widening is a visible decision.
These assertions fail until PD2; do not xfail: RED is the point.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mergecraft.agents.verifier import AgentFinding
from mergecraft.modes import PR_SUMMARY_FORMAT, compute_modes

#: The exact field reference the prompts must stop asking agents to populate.
_COLLATERAL_FIELD = "`collateral`"


def _rendered_surfaces() -> dict[str, str]:
    surfaces = {"PR_SUMMARY_FORMAT": PR_SUMMARY_FORMAT}
    for mode in compute_modes("claude"):
        if mode.prompt is not None:
            surfaces[mode.name] = mode.prompt
    return surfaces


def test_no_prompt_asks_for_a_collateral_field_or_list() -> None:
    offenders = sorted(
        name for name, text in _rendered_surfaces().items() if _COLLATERAL_FIELD in text
    )
    assert not offenders, (
        f"these surfaces still ask for a `collateral` finding field/list: {offenders} (PD-D2)"
    )


def test_also_update_body_instruction_remains() -> None:
    """The shipped body-only mechanism must survive the fix (plan §C3)."""
    assert "Also update:" in PR_SUMMARY_FORMAT
    for name in ("Review", "IncrementalReview"):
        assert "Also update:" in _rendered_surfaces()[name], (
            f"{name} no longer renders the body-only 'Also update:' instruction"
        )


def test_agent_finding_still_forbids_a_collateral_key() -> None:
    """Read-only pin on plan 39's schema — a widening must be a visible decision."""
    with pytest.raises(ValidationError) as excinfo:
        AgentFinding.model_validate(
            {
                "path": "src/app.py",
                "body": "a body",
                "severity": "Major",
                "collateral": ["src/other.py"],
            }
        )
    message = str(excinfo.value)
    assert "collateral" in message
    assert "extra" in message.lower(), (
        f"AgentFinding must reject `collateral` as an extra field; got: {message}"
    )
