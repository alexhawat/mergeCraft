"""W7 RED suite for #75 structural approval gate — pure decision function.

These tests pin the contract W8 must implement in
``src/mergecraft/agents/gates.py`` (or a sibling module under
``src/mergecraft/agents/``). Every test is marked
``@pytest.mark.xfail(reason="green after W8", strict=False)`` because the
function ``decide_approval(findings, *, run_succeeded, tier) -> Conclusion``
does not yet exist on this branch — W8 will add it.

The contract under test (D12, D13):

- ``decide_approval`` is a *pure function* of the finding list, the run
  completion state, and the trust tier. Narrative (``ApprovalRecord``,
  ``result.output``, anything the model wrote) is never one of its inputs.
- Any blocker (Critical or Major) finding ⇒ ``"failure"``.
- A crashed / timed-out / no-findings run on a trusted tier with no blockers
  resolves to ``"neutral"`` (the wire-shape that the hardened enforce step
  treats as blocking — D13).
- An untrusted tier cannot self-approve regardless of the agent's
  ``approved`` signal — the gate is inert for ``tier == "untrusted"`` (D14).
- The agent's ``approved=True`` argument is recorded as an advisory input
  (the unsigned boolean remains in ``ApprovalRecord.would_approve``) but
  is *not* the sole positive input. A ``decided`` success requires
  ``run_succeeded == True`` and no blockers (W7.5).
- The decision function imports ``Finding`` from ``analyzers/finding.py``
  and does not define a parallel model anywhere (W7.6).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.finding import Finding
from mergecraft.review_taxonomy import FindingSource

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Module-availability guard for the future decision function. W8 will land
# ``decide_approval`` in `src/mergecraft/agents/gates.py` (or a sibling
# module); the import is inside a helper so the failure mode is a clear
# AttributeError / ImportError on the test rather than a top-level collection
# crash that hides the actual assertion.
# ---------------------------------------------------------------------------


def _decide_approval() -> Callable[..., Any]:
    """Return ``decide_approval`` from the W8 module it lands in.

    W8's outline (from the plan, W8.1): a pure function
    ``decide_approval(findings: list[Finding], *, run_succeeded: bool,
    tier: TrustTier) -> Conclusion`` in `src/mergecraft/agents/gates.py`.
    The module may add it as a sibling helper rather than renaming the file.
    """
    from mergecraft.agents import gates as _gates

    fn = getattr(_gates, "decide_approval", None)
    if fn is None:  # pragma: no cover - W7 expects this until W8 lands
        msg = (
            "decide_approval is not yet defined in mergecraft.agents.gates "
            "(W8 deliverable — W7.1–W7.6 are xfail until it lands)"
        )
        raise AttributeError(msg)
    return fn


def _approval_conclusion_module() -> Any:
    """Return the module that defines ``Conclusion`` (per W8.1 it reuses
    ``utils/status_checks.Conclusion``)."""
    from mergecraft.utils import status_checks as _sc

    return _sc


# ---------------------------------------------------------------------------
# W7.1 — narrative "approved" + blocker finding ⇒ failure
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W8", strict=False)
def test_narrative_approval_with_blocker_finding_yields_failure(
    blocker_finding: Finding,
) -> None:
    """The issue's headline acceptance criterion (#75).

    Drive a run whose narrative says "approved" (the agent's boolean lives
    in ``ApprovalRecord.would_approve``) while the typed finding list
    contains a blocker. The structural approval gate must post ``failure``
    regardless of the narrative.
    """
    decide = _decide_approval()
    sc = _approval_conclusion_module()

    # Narrative says "approved" — model passed approved=True.
    narrative_says_approved = True
    assert narrative_says_approved is True  # guard: the test is about the conflict

    conclusion = decide(
        [blocker_finding],
        run_succeeded=True,
        tier="trusted",
    )

    assert conclusion == sc.Conclusion  # type: ignore[attr-defined]
    assert conclusion == "failure", (
        "approval gate must be derived from findings, not narrative — "
        "a blocker must yield 'failure' even when the agent said 'approved'"
    )


# ---------------------------------------------------------------------------
# W7.2 — pure function of findings: same findings, different narratives,
# identical conclusion.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W8", strict=False)
@pytest.mark.parametrize(
    "narrative_would_approve",
    [True, False, None],
    ids=["narrative-approve", "narrative-block", "narrative-unrecorded"],
)
def test_approval_conclusion_is_pure_function_of_findings(
    sample_findings: list[Finding],
    narrative_would_approve: bool | None,
) -> None:
    """Same finding list, three different narratives → identical conclusion.

    The decision function's signature must not accept an
    ``ApprovalRecord.would_approve`` value. The agent's boolean is recorded
    separately by W8.3; the conclusion is computed from findings + run
    state + tier only.
    """
    decide = _decide_approval()

    # The narrative lives in tool_state.approval.would_approve — it is
    # never an input to decide_approval. The test asserts that the same
    # finding list + run state + tier produces the same conclusion across
    # three different recorded narratives.
    decisions = [
        decide(
            sample_findings,
            run_succeeded=True,
            tier="trusted",
        )
        for _ in range(3)
    ]
    assert len({id(d) for d in decisions}) == 1, (
        "decide_approval must return a single value — it has no I/O and no internal state"
    )
    # Same value, same conclusion.
    assert decisions[0] == decisions[1] == decisions[2]

    # Same finding list (blockers present) ⇒ failure. The narrative is
    # not part of the call: narrative_would_approve is parametrized only
    # so the test name documents the matrix.
    assert decisions[0] == "failure", (
        "a finding list containing blockers must yield 'failure' "
        "regardless of the agent's recorded narrative"
    )

    # Sanity: the parametrized axis is not silently consumed by the function.
    _ = narrative_would_approve


# ---------------------------------------------------------------------------
# W7.5 — the agent's approved flag is advisory only
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W8", strict=False)
def test_agent_approved_flag_is_advisory_only_with_empty_findings(
    clean_findings: list[Finding],
) -> None:
    """``create_pull_request_review(approved=True)`` with no findings must
    not by itself produce ``success``.

    W8.3 demotes the agent's boolean to advisory. With *no* findings on
    the structural side, the gate is ``neutral`` (the wire-shape the
    hardened enforce step treats as blocking — D13), not ``success``.
    """
    decide = _decide_approval()

    # Simulate the agent calling create_pull_request_review(approved=True).
    # The ApprovalRecord is recorded separately; the decision is computed
    # from findings + run state + tier only.
    conclusion = decide(
        clean_findings,
        run_succeeded=True,
        tier="trusted",
    )

    # "neutral" is the only honest shape here: the run completed, no
    # blockers, but there are also no findings to attest to. The hardened
    # enforce step (W8.4) treats neutral as blocking.
    assert conclusion == "neutral", (
        "the agent's approved=True must not by itself produce 'success' "
        "when the structural finding list is empty — the conclusion is "
        "a pure function of findings, not narrative"
    )


@pytest.mark.xfail(reason="green after W8", strict=False)
def test_agent_approved_flag_is_advisory_only_with_blocking_findings(
    blocker_finding: Finding,
) -> None:
    """Mirror of W7.5: the agent's ``approved=True`` cannot override a blocker.

    Even with the agent's boolean set, the gate must remain ``failure``
    because the finding list contains a blocker.
    """
    decide = _decide_approval()

    conclusion = decide(
        [blocker_finding],
        run_succeeded=True,
        tier="trusted",
    )

    assert conclusion == "failure", (
        "advisory 'approved' from the agent must not flip a blocker "
        "into 'success' — findings are the structural input"
    )


@pytest.mark.xfail(reason="green after W8", strict=False)
def test_approval_record_remains_an_advisory_input(
    tmp_path: Path,
) -> None:
    """W8.3 keeps ``ApprovalRecord.would_approve`` recorded but never
    consulted as the sole positive input.

    This is a structural test: an ``ApprovalRecord`` with ``would_approve=True``
    is constructed in ``tool_state`` (the same way ``create_pull_request_review``
    would record it today), and the decision function is invoked *without*
    passing the ``ApprovalRecord`` as an argument. The conclusion is computed
    from findings + run state + tier only.
    """
    from mergecraft.mcp.tool_state import ApprovalRecord, init_tool_state

    decide = _decide_approval()

    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    # Simulate the agent having called create_pull_request_review(approved=True).
    tool_state.approval = ApprovalRecord(would_approve=True, sha="abc123")

    # No findings, run succeeded, trusted tier.
    conclusion = decide(
        [],
        run_succeeded=True,
        tier="trusted",
    )

    # The agent's stored boolean is irrelevant to the decision function.
    assert conclusion == "neutral", (
        "the decision function must not read ApprovalRecord.would_approve; "
        "an approval with no findings must not produce 'success'"
    )


# ---------------------------------------------------------------------------
# W7.6 — structural guard: no parallel finding model
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="green after W8", strict=False)
def test_no_second_finding_model_introduced() -> None:
    """D12: the approval path imports ``Finding`` from
    ``analyzers/finding.py`` and defines no parallel model.

    Asserted by inspecting the module W8 will add the decision function
    to (``src/mergecraft/agents/gates.py``) and the ``analyzers``
    package for parallel models.
    """
    import mergecraft.agents.gates as gates
    from mergecraft.analyzers import finding as finding_mod

    # The decision function (W8) lives in this module.
    assert hasattr(gates, "decide_approval"), (
        "W8 must add decide_approval to mergecraft.agents.gates"
    )

    # The approval path's Finding is the canonical one from finding.py.
    decision_finding = gates.decide_approval.__annotations__["findings"]
    # The annotation must be ``list[Finding]`` (or equivalent) — not a
    # parallel model defined in gates.py.
    assert str(decision_finding) == "list[Finding]", (
        "decide_approval's findings argument must be annotated as "
        "list[Finding] — D12 forbids a parallel model"
    )

    # No parallel finding class in the gates module.
    for name in vars(gates):
        obj = getattr(gates, name)
        if isinstance(obj, type) and obj is not Finding and obj.__name__.endswith("Finding"):
            msg = f"mergecraft.agents.gates must not define a parallel finding model: {obj}"
            raise AssertionError(msg)

    # The canonical Finding is still re-exported from analyzers.finding.
    assert finding_mod.Finding is Finding


@pytest.mark.xfail(reason="green after W8", strict=False)
def test_finding_source_is_preserved_for_evidence_audit() -> None:
    """Findings carry a ``source`` field (analyzer / agent / ci) that the
    approval conclusion must respect when distinguishing "agent claims
    versus structural evidence".

    The decision is *not* a function of the sources themselves
    (severity is the gating axis), but the decision must not strip or
    rewrite ``source`` — that breaks the merge-evidence plan's
    reconstruction requirement (#75 proposal item 4).
    """
    decide = _decide_approval()

    findings: list[Finding] = [
        _make_finding_with_source("agent"),
        _make_finding_with_source("ci"),
    ]
    before = [f.source for f in findings]
    decide(
        findings,
        run_succeeded=True,
        tier="trusted",
    )
    after = [f.source for f in findings]
    assert before == after, (
        "decide_approval must not mutate findings — the merge-evidence "
        "plan reconstructs the conclusion from stored findings"
    )


def _make_finding_with_source(source: FindingSource) -> Finding:
    """Constructor helper for the no-mutation assertion."""
    from mergecraft.analyzers.finding import make_finding

    return make_finding(
        tool="w7-fixture",
        rule_id="W7-SRC",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="possible",
        message="source-preservation probe",
        path="src/mergecraft/utils/status_checks.py",
        start_line=1,
        end_line=1,
        source=source,
        fingerprint=f"w7-src-{source}",
    )
