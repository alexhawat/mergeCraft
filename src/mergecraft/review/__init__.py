"""Review-mode helpers — shared engine, snapshot, and lens selection."""

from __future__ import annotations

from mergecraft.review.engine import ReviewEngine, ReviewEngineResult, run_from_snapshot
from mergecraft.review.lens_routing import (
    LENS_ROUTING_STEP4_NOTE,
    LensRoutingDecision,
    LensRoutingEntry,
    load_routing_registry,
    route_lenses,
)
from mergecraft.review.snapshot import (
    ReviewSnapshot,
    ReviewStageSpec,
    canonical_review_snapshot,
)

__all__ = [
    "LENS_ROUTING_STEP4_NOTE",
    "LensRoutingDecision",
    "LensRoutingEntry",
    "ReviewEngine",
    "ReviewEngineResult",
    "ReviewSnapshot",
    "ReviewStageSpec",
    "canonical_review_snapshot",
    "load_routing_registry",
    "route_lenses",
    "run_from_snapshot",
]
