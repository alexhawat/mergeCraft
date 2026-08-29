"""Tests for shared finding severity ranking."""

from __future__ import annotations

from mergecraft.findings.severity import severity_rank


def test_severity_rank_orders_blocking_severities() -> None:
    assert severity_rank("Trivial") < severity_rank("Minor")
    assert severity_rank("Minor") < severity_rank("Major")
    assert severity_rank("Major") < severity_rank("Critical")


def test_severity_rank_unknown_defaults_below_minor() -> None:
    assert severity_rank("unknown") == 0
