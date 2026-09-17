"""Behavioural results are their own artifact — Finding and FindingSource stay put."""

from __future__ import annotations

from typing import get_args

from mergecraft.analyzers.finding import Finding
from mergecraft.review_taxonomy import FindingSource
from tests.verify.support import PINNED_FINDING_FIELDS, PINNED_FINDING_SOURCES


def test_finding_fields_are_unchanged() -> None:
    """This plan does not extend ``Finding``; a new field fails this pin."""
    assert set(Finding.model_fields) == PINNED_FINDING_FIELDS
    assert Finding.model_config.get("extra") == "forbid"


def test_finding_source_gains_no_behavior_value() -> None:
    """No new ``FindingSource`` member (including ``behavior``) is added."""
    sources = set(get_args(FindingSource))
    assert sources == PINNED_FINDING_SOURCES
    assert "behavior" not in sources
    assert "behaviour" not in sources
    assert "verification" not in sources
