"""Run-budget + model-chain helpers used by ``main.py``.

Extracted from ``main.py`` so the orchestrator stays under the 1k-line ceiling.
Both helpers carry over verbatim — the audit confirmed ``NO_ISSUES`` on the
model-chain selection block (W4/D8) and on the timeout-budget resolver
(S1 / F6), so we move the bodies without touching the logic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.utils.agent_resolve import (
    pick_runnable_slug_from_chain,
    resolve_model,
    resolve_runtime_agent,
)
from mergecraft.utils.payload import TIMEOUT_DISABLED, resolve_timeout_ms

if TYPE_CHECKING:
    from mergecraft.agents.shared import Agent
    from mergecraft.config.settings import RepoSettings


class _ConfigurationError(RuntimeError):
    """Marks fail-closed configuration errors (D4/W6.3).

    Raised for unparseable Action inputs (e.g. ``timeout``) so the outer
    handler can tag ``RunOutcome.configuration_error`` without confusing
    them with infra crashes.
    """


def _first_runnable_in_chain(chain: list[str]) -> str:
    """Harness-patchable one-arg facade over :func:`pick_runnable_slug_from_chain`.

    ``allow_fallback`` lives on the function object (not a module global) so the
    harness can still replace this symbol with ``lambda chain: …`` while
    ``main`` stamps the policy before calling.
    """
    allow = bool(getattr(_first_runnable_in_chain, "allow_fallback", True))
    return pick_runnable_slug_from_chain(chain, allow_fallback=allow)


_first_runnable_in_chain.allow_fallback = True  # type: ignore[attr-defined]


def _resolve_run_budget(payload: dict[str, Any], settings: RepoSettings) -> tuple[int | None, int]:
    """Resolve the pre-deduction ``timeout_ms`` and the post-cap ``setup_timeout_s``.

    Returns ``(timeout_ms, setup_timeout_s)`` where ``timeout_ms`` is ``None``
    when ``timeout == "none"`` (no deadline), a positive duration in ms
    otherwise, and defaults to one hour when no value is supplied.
    ``setup_timeout_s`` is the ``settings.setup_timeout_s`` capped against
    ``timeout_ms // 1000`` so a tight run deadline shrinks the setup budget
    proportionally (S1 / F6). Raises :class:`_ConfigurationError` for an
    unparseable duration string so the outer catch routes it to
    ``RunOutcome.configuration_error``.
    """
    timeout_raw = payload.get("timeout")
    if timeout_raw == TIMEOUT_DISABLED:
        timeout_ms: int | None = None
    elif timeout_raw:
        usable = resolve_timeout_ms(timeout_raw)
        if usable is None:
            msg = (
                f'invalid timeout "{timeout_raw}" '
                "(use a duration like 10m/1h or --notimeout to disable)"
            )
            raise _ConfigurationError(msg)
        timeout_ms = usable
    else:
        timeout_ms = 3_600_000

    setup_timeout_s = settings.setup_timeout_s
    if timeout_ms is not None and timeout_ms > 0:
        setup_timeout_s = min(setup_timeout_s, timeout_ms // 1000)
    return timeout_ms, setup_timeout_s


def _resolve_agent_model(
    model_head: str | None,
    model_pin: bool,
    chain_for_decision: list[str],
    settings: RepoSettings,
) -> tuple[str | None, str | None, Agent, bool]:
    """Resolve the model-chain selection block (W4/D8).

    Returns ``(selected_slug, resolved_model, agent, use_model_chain)``.
    ``use_model_chain`` is true whenever an effective chain has more than
    one entry OR the operator asked for the chain explicitly (i.e. supplied
    a ``model:`` head AND did not pin); it is consumed by :func:`main` when
    dispatching the agent run and re-used inside
    :func:`_run_agent_with_timeout` to decide whether to wrap the call in
    :func:`run_with_model_chain`. The helper raises :class:`RuntimeError`
    when the chain has no runnable entry under the operator's
    ``allow_fallback`` setting, mirroring the inline block that used to
    live in :func:`main`.
    """
    use_model_chain = len(chain_for_decision) > 1 or (
        bool(chain_for_decision) and model_head is not None and not model_pin
    )
    selected_slug: str | None
    if use_model_chain:
        _first_runnable_in_chain.allow_fallback = settings.allow_fallback  # type: ignore[attr-defined]
        selected_slug = _first_runnable_in_chain(chain_for_decision)
        if not selected_slug:
            msg = "no runnable model slug in chain — configure credentials for at least one entry"
            raise RuntimeError(msg)
        resolved_model = resolve_model(slug=selected_slug, respect_env_override=False)
    else:
        # Single-entry chain (or pin opt-in). The chain is collapsed to
        # exactly ``[model_head]`` when pinned; otherwise it is just the
        # first configured entry. Honour ``respect_env_override=False``
        # when the operator named a model explicitly — the action input
        # already wins.
        only_slug = (
            model_head if model_pin else (chain_for_decision[0] if chain_for_decision else None)
        )
        resolved_model = resolve_model(slug=only_slug, respect_env_override=False)
        selected_slug = only_slug
    agent = resolve_runtime_agent(model=resolved_model)
    return selected_slug, resolved_model, agent, use_model_chain


# ``_ConfigurationError`` is re-exported here because ``main.py`` re-raises
# ``ValueError`` from ``apply_setup_overrides`` / ``apply_tracing_overrides``
# as this type — moving it out keeps the public exception surface intact.
__all__ = [
    "_ConfigurationError",
    "_first_runnable_in_chain",
    "_resolve_agent_model",
    "_resolve_run_budget",
]
