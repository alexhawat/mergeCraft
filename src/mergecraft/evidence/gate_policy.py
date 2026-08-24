"""The five default gate-action policies (#46 / W9.2).

The thermostat is the structural successor to the ``Decision`` row Batch
A shipped: every gate outcome maps to a *named* action, never to a
number. The default policies here are the five example mappings #46
names literally — a schema failure blocks, a changed-unread-file asks
for changes, a low-risk passing change merges, a tool-loop asks for more
tests, and a high-risk migration asks for human review.

The mapping is **declarative data, not a long if/elif**: a repository
overrides any individual rule by ``lane`` or ``rule_id`` via
``RepoSettings.gate_action_override``, and the new value is validated
against the closed action vocabulary before it takes effect. A typo
in an override, or any value outside the seven names, is rejected
by ``decide_action()`` rather than silently widening the gate.

Exports:
    GateAction: The closed action vocabulary (Pydantic enum / Literal).
    GateActionPolicy: A schema -> action mapping. Treated as data.
    DEFAULT_GATE_POLICIES: The five example policies from #46.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class GateAction(StrEnum):
    """The closed action vocabulary (#46 / W9.1).

    Seven names — ``auto_merge`` / ``block`` / ``request_changes`` /
    ``require_human_review`` / ``require_more_tests`` / ``quarantine``
    / ``escalate``. The set is closed: a bare string cannot stand in.
    A mis-spelling or a free-form phrase is rejected at the boundary
    so the gate never goes off the rails by a sloppy override.

    The enum is a ``str`` mixin so it serializes as the action name
    in JSON without a custom encoder, and so ``str(action) == action``
    for the typed comparisons downstream callers reach for.
    """

    AUTO_MERGE = "auto_merge"
    BLOCK = "block"
    REQUEST_CHANGES = "request_changes"
    REQUIRE_HUMAN_REVIEW = "require_human_review"
    REQUIRE_MORE_TESTS = "require_more_tests"
    QUARANTINE = "quarantine"
    ESCALATE = "escalate"


# Closed vocabularies are exported as ``frozenset[str]`` so test
# assertions and operator previews can compare against the set without
# needing to import the enum.
GATE_ACTIONS: Final[frozenset[str]] = frozenset(action.value for action in GateAction)


# Keys that name a rule. The rule keys are the *canonical* schema
# failure / ``changed-unread-file`` / ``low_risk_passing`` / ``tool_loop``
# / ``high_risk_migration`` names #46 names literally, plus a couple of
# fall-through keys the policy engine reaches for when the rule did
# not match a named trigger.
RuleId = str


# A policy is a mapping from a rule key to a GateAction. The schema is
# deliberately a typed ``dict[str, GateAction]`` rather than a Pydantic
# model: validators on the values are cheaper than a custom validator
# and the type already enforces the closed vocabulary. Repositories
# override the mapping at the call site rather than mutating this
# module.
GateActionPolicy = dict[RuleId, GateAction]


# Default policies #46 ships, plus ``has_blockers`` so Critical/Major
# findings request changes under their own key instead of borrowing
# ``changed-unread-file``. Dict insertion order is not match priority:
# ``select_rule_id`` chooses the key (high_risk_migration, then
# low_risk_passing, then has_blockers over changed-unread-file / tool_loop,
# then schema_failure). ``decide_action`` looks that key up here.
DEFAULT_GATE_POLICIES: Final[GateActionPolicy] = {
    "schema_failure": GateAction.BLOCK,
    "changed-unread-file": GateAction.REQUEST_CHANGES,
    "has_blockers": GateAction.REQUEST_CHANGES,
    "low_risk_passing": GateAction.AUTO_MERGE,
    "tool_loop": GateAction.REQUIRE_MORE_TESTS,
    "high_risk_migration": GateAction.REQUIRE_HUMAN_REVIEW,
}


__all__ = [
    "DEFAULT_GATE_POLICIES",
    "GATE_ACTIONS",
    "GateAction",
    "GateActionPolicy",
    "RuleId",
]
