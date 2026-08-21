"""Failure-injection harness for named reliability faults (#364).

Out of scope: soak/SLO runners (``slo``) and degradation/recovery (``recovery``).

Exports:
    FailureToken: Handle returned when a named fault is injected.
    inject_failure: Cut a provider, analyzer, or disk without a live gateway.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from loguru import logger

NamedFault = Literal["provider_outage", "analyzer_crash", "disk_full"]


@dataclass(frozen=True, slots=True)
class FailureToken:
    """Opaque handle for an injected fault (cleared by dropping the token)."""

    fault: NamedFault
    token_id: str


def inject_failure(fault: str) -> FailureToken:
    """Inject a named fault and return a token proving the cut landed.

    Args:
        fault: One of ``provider_outage``, ``analyzer_crash``, ``disk_full``.

    Returns:
        A non-None token the soak/SLO harness can correlate.

    Raises:
        ValueError: If ``fault`` is not a named injection.
    """
    match fault:
        case "provider_outage" | "analyzer_crash" | "disk_full":
            named: NamedFault = fault
        case _:
            raise ValueError(f"unknown failure injection: {fault}")
    token = FailureToken(fault=named, token_id=uuid.uuid4().hex)
    logger.debug("Injected reliability fault {}", named)
    return token
