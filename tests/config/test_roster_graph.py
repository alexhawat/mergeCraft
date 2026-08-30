"""Unit tests for canonical ``after:`` graph helpers (wave plan 11)."""

from __future__ import annotations

import pytest

from mergecraft.config.roster_graph import (
    AfterEdge,
    RosterGraphError,
    dispatch_levels,
    ordered_level_groups,
    validate_after_graph,
)


def test_dispatch_levels_parallel_reviewers_share_level_zero() -> None:
    nodes = (
        AfterEdge(name="reviewer", after=None),
        AfterEdge(name="reviewer2", after=None),
    )
    assert dispatch_levels(nodes) == {"reviewer": 0, "reviewer2": 0}


def test_dispatch_levels_chain_increments_levels() -> None:
    nodes = (
        AfterEdge(name="reviewer", after=None),
        AfterEdge(name="reviewer2", after="reviewer"),
        AfterEdge(name="reviewer3", after="reviewer2"),
    )
    assert dispatch_levels(nodes) == {"reviewer": 0, "reviewer2": 1, "reviewer3": 2}


def test_ordered_level_groups_preserves_declaration_order_within_level() -> None:
    nodes = (
        AfterEdge(name="reviewer", after=None),
        AfterEdge(name="reviewer-b", after="reviewer"),
        AfterEdge(name="reviewer-c", after="reviewer"),
    )
    groups = ordered_level_groups(
        nodes,
        names_in_order=("reviewer", "reviewer-b", "reviewer-c"),
    )
    assert groups == (("reviewer",), ("reviewer-b", "reviewer-c"))


def test_validate_after_graph_rejects_unknown_dependency() -> None:
    nodes = (AfterEdge(name="reviewer2", after="missing"),)
    with pytest.raises(RosterGraphError, match=r"unknown agent"):
        validate_after_graph(nodes)


def test_validate_after_graph_rejects_self_cycle() -> None:
    nodes = (AfterEdge(name="reviewer", after="reviewer"),)
    with pytest.raises(RosterGraphError, match=r"cycle"):
        validate_after_graph(nodes)


def test_validate_after_graph_rejects_longer_cycle() -> None:
    nodes = (
        AfterEdge(name="a", after="b"),
        AfterEdge(name="b", after="a"),
    )
    with pytest.raises(RosterGraphError, match=r"cycle"):
        validate_after_graph(nodes)
