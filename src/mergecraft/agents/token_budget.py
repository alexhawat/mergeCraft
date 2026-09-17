"""Shared J2 ``TokenBudget`` + kill-switch for every provider path (E-D9).

Re-exports plan 23 J2's budget and cost helpers — this module does not
invent a second cap. Agent dispatch binds one budget per run; concurrent
callers that share the bound object share one cap. Unreported token fields
stay ``None`` (``cost_known=False``), never coerced to zero.

Exports:
    TokenBudget: J2 per-run token cap (identity, not a fork).
    compute_cost: J2 price lookup keyed by pinned model id.
    PROVIDER_PATHS: Reviewing harnesses plus ``jev``.
    bind_run_budget: Bind one budget for the dynamic scope.
    current_run_budget: Read the bound budget, if any.
    record_provider_usage: J2 ``record_usage`` with honest ``None`` tokens.
    token_budget_for: Build J2's budget for a pinned model id.
    apply_kill_switch: Return ``kill_switch`` or ``ok``.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Final, Literal

from mergecraft.jev.cost import TokenBudget, compute_cost

if TYPE_CHECKING:
    from collections.abc import Iterator

PROVIDER_PATHS: Final[frozenset[str]] = frozenset(
    {"claude", "codex", "cursor", "gemini", "opencode", "jev"}
)

_RUN_BUDGET: ContextVar[TokenBudget | None] = ContextVar(
    "mergecraft_run_token_budget", default=None
)

KillSwitchStatus = Literal["kill_switch", "ok"]


def current_run_budget() -> TokenBudget | None:
    """Return the budget bound for this run, or ``None``.

    Returns:
        TokenBudget | None: The shared cap, when ``bind_run_budget`` is active.
    """
    return _RUN_BUDGET.get()


@contextmanager
def bind_run_budget(budget: TokenBudget) -> Iterator[TokenBudget]:
    """Bind ``budget`` for the dynamic scope so concurrent dispatches share it.

    Args:
        budget: J2 ``TokenBudget`` for this run (same object, one cap).

    Yields:
        TokenBudget: The bound budget.
    """
    token = _RUN_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _RUN_BUDGET.reset(token)


def record_provider_usage(
    budget: TokenBudget,
    *,
    input_tokens: int | None,
    output_tokens: int | None,
) -> bool:
    """Account one provider call without coercing ``None`` tokens to zero.

    Args:
        budget: Shared J2 budget.
        input_tokens: Prompt tokens, or ``None`` when the API omitted them.
        output_tokens: Completion tokens, or ``None`` when omitted.

    Returns:
        bool: J2 ``record_usage`` result — ``True`` when accepted or unreported.
    """
    return budget.record_usage(input_tokens=input_tokens, output_tokens=output_tokens)


def token_budget_for(*, model: str, max_tokens: int) -> TokenBudget:
    """Return J2's ``TokenBudget`` for a pinned model id.

    Price lookup stays on ``compute_cost`` / ``PRICE_TABLE``, keyed by ``model``.
    The budget object itself is the J2 token cap (E-D9 — no fork).

    Args:
        model: Pinned model id used for price-table lookup.
        max_tokens: Per-run token ceiling.

    Returns:
        TokenBudget: J2 budget with ``max_tokens`` set.

    Raises:
        ValueError: ``model`` is empty.
    """
    if not model:
        msg = "token_budget_for requires a pinned model id"
        raise ValueError(msg)
    return TokenBudget(max_tokens=max_tokens)


def apply_kill_switch(budget: TokenBudget) -> KillSwitchStatus:
    """Return the J2 stop-reason token when the cap has already fired.

    Args:
        budget: Shared J2 budget.

    Returns:
        Literal["kill_switch", "ok"]: ``kill_switch`` when dispatch must stop.
    """
    if budget.should_stop():
        return "kill_switch"
    return "ok"


__all__ = [
    "PROVIDER_PATHS",
    "TokenBudget",
    "apply_kill_switch",
    "bind_run_budget",
    "compute_cost",
    "current_run_budget",
    "record_provider_usage",
    "token_budget_for",
]
