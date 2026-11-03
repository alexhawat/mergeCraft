"""The policy surface says what review actually does with the rules.

Review enforces the rules in ``.mergecraft/policy/rules.yaml``: a rule applies
when a changed file matches its scope, and its enforcement mode decides what
the approval verdict does. The ``policy`` group help must say that, and the
enforcement module's docstring must name the mapping onto the approval gate.
The authoring verbs the group really performs stay advertised.
"""

from __future__ import annotations

from tests.support.cc_batch import invoke, plain

from mergecraft.policy import enforcement

_NEGATIONS = (
    "not enforc",
    "never enforc",
    "no enforcement",
    "does not enforce",
    "is not enforced",
)


def test_policy_group_help_says_review_enforces_the_rules_file() -> None:
    """The group help states the wired behaviour and still advertises the verbs."""
    result = invoke("policy", "--help")
    assert result.exit_code == 0, plain(result.stdout + result.stderr)
    text = plain(result.stdout + result.stderr).casefold()

    assert "enforce" in text
    assert ".mergecraft/policy" in text
    assert "rules.yaml" in text
    assert "scope" in text
    for phrase in _NEGATIONS:
        assert phrase not in text, f"the stale non-enforcement claim survived: {phrase!r}"
    # Surviving surface: the verbs the group really performs stay advertised.
    for verb in ("lint", "test", "explain", "simulate"):
        assert verb in text


def test_enforcement_module_docstring_names_the_review_gate_mapping() -> None:
    """The docstring describes the mapping the review now applies."""
    doc = enforcement.__doc__ or ""
    lowered = doc.casefold()

    assert "approval gate" in lowered
    assert "policy/review.py" in doc
    assert "nothing in review consumes" not in lowered
    assert "no review path calls this yet" not in lowered
    # Surviving surface: the evaluation engine stays and is described as enforcement.
    assert callable(enforcement.evaluate_enforcement)
    assert "enforc" in lowered
