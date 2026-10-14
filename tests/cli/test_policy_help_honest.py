"""The policy surface says what review actually does.

Policy rules are linted, tested, explained and simulated; review does not
enforce them. The module docstring must not claim the enforcement engine is
mapped onto the approval gate, and the ``policy`` group help must say so.
"""

from __future__ import annotations

from tests.support.cc_batch import invoke, plain

from mergecraft.policy import enforcement


def test_policy_group_help_says_review_does_not_enforce_rules() -> None:
    """The group help states the limits and still advertises the supported verbs."""
    result = invoke("policy", "--help")
    assert result.exit_code == 0, plain(result.stdout + result.stderr)
    text = plain(result.stdout + result.stderr).casefold()
    says_not_enforced = any(
        phrase in text
        for phrase in (
            "not enforc",
            "never enforc",
            "no enforcement",
            "does not enforce",
            "is not enforced",
        )
    )
    assert says_not_enforced, text
    # Surviving surface: the verbs the group really performs stay advertised.
    for verb in ("lint", "test", "explain", "simulate"):
        assert verb in text


def test_enforcement_module_docstring_does_not_claim_an_approval_gate_mapping() -> None:
    """The module docstring names no approval-gate mapping; the engine still ships."""
    doc = (enforcement.__doc__ or "").casefold()
    assert "approval gate" not in doc
    assert "approval" not in doc
    # Surviving surface: the evaluation engine stays and is described as enforcement.
    assert callable(enforcement.evaluate_enforcement)
    assert "enforc" in doc
