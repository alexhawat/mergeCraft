"""Shared errors raised without importing the Action entry point.

Module: mergecraft.errors
Depends: None

Exports:
    Classes:
        AgentTimeoutError — Marks a locally enforced agent timeout.
        ConfigurationError — Marks a fail-closed run configuration error.
        ModelFallbackPolicyError — Marks a blocked model fallback.
"""

from __future__ import annotations


class AgentTimeoutError(RuntimeError):
    """Marks the ``asyncio.wait_for`` timeout path (D3/W5.2).

    A plain ``RuntimeError`` would be indistinguishable from any other agent
    crash once it reaches the outer catch-all; this subclass lets
    ``_classify_error_outcome`` tag it ``RunOutcome.timed_out`` instead of
    the generic ``infra_error`` default.
    """


class ConfigurationError(RuntimeError):
    """Marks fail-closed configuration errors (D4/W6.3).

    Raised for unparseable Action inputs (e.g. ``timeout``) so the outer
    handler can tag ``RunOutcome.configuration_error`` without confusing
    them with infra crashes.
    """


class ModelFallbackPolicyError(RuntimeError):
    """Raised when ``allow_fallback=false`` blocks advancing the model chain (W10.1).

    Mapped to ``RunOutcome.configuration_error`` by ``main._classify_error_outcome``.
    Message always names configuration/fallback so operators and RED tests can
    match the policy without inspecting the exception type alone.
    """
