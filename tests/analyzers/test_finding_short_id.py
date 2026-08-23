"""CA #452 RED — stable short finding id derived from ``Finding.fingerprint`` (D2).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-24-c-findings-cli-wave-plan.md``
Implementation wave: **CA**. Pins prefix ``MC-``, deterministic derivation, and
documented collision behaviour when truncated ids would clash.
"""

from __future__ import annotations

import re

import pytest

from tests.analyzers.support_short_id import (
    collision_fingerprints,
    require_attr,
    require_callable,
)

_MC_ID_RE = re.compile(r"^MC-[0-9a-f]{6,}$")


@pytest.mark.xfail(reason="green after CA", strict=False)
def test_finding_short_id_prefix_is_mc() -> None:
    """D2 — short ids use the ``MC-`` prefix."""
    prefix = require_attr("FINDING_SHORT_ID_PREFIX")
    finding_short_id = require_callable("finding_short_id")
    fingerprint = "a83f91c2d4e5f6a7b8c9d0e1"
    short_id = finding_short_id(fingerprint)
    assert prefix == "MC-"
    assert short_id.startswith("MC-")


@pytest.mark.xfail(reason="green after CA", strict=False)
def test_finding_short_id_is_deterministic_for_same_fingerprint() -> None:
    """Happy — the same fingerprint always maps to the same short id."""
    finding_short_id = require_callable("finding_short_id")
    fingerprint = "deadbeefcafebabe01234567"
    assert finding_short_id(fingerprint) == finding_short_id(fingerprint)


@pytest.mark.xfail(reason="green after CA", strict=False)
def test_finding_short_id_uses_fingerprint_prefix() -> None:
    """Happy — default truncation uses the fingerprint's leading hex (issue example)."""
    finding_short_id = require_callable("finding_short_id")
    fingerprint = "a83f91c2d4e5f6a7b8c9d0e1"
    assert finding_short_id(fingerprint) == "MC-a83f91"


@pytest.mark.xfail(reason="green after CA", strict=False)
def test_finding_short_id_differs_for_different_fingerprints() -> None:
    """Edge — unrelated fingerprints should not share a short id by default."""
    finding_short_id = require_callable("finding_short_id")
    left = finding_short_id("111111111111111111111111")
    right = finding_short_id("222222222222222222222222")
    assert left != right


@pytest.mark.parametrize(
    ("fingerprint", "label"),
    [
        ("", "empty"),
        (".", "dot"),
        ("..", "dotdot"),
        ("../escape", "path traversal"),
    ],
)
@pytest.mark.xfail(reason="green after CA", strict=False)
def test_finding_short_id_rejects_unsafe_fingerprint(
    fingerprint: str,
    label: str,
) -> None:
    """Error — unsafe fingerprint values are rejected at the helper boundary."""
    finding_short_id = require_callable("finding_short_id")
    with pytest.raises((ValueError, TypeError), match=r".+"):
        finding_short_id(fingerprint)


@pytest.mark.xfail(reason="green after CA", strict=False)
def test_resolve_finding_short_ids_disambiguates_truncation_collisions() -> None:
    """D2 — batch assignment yields distinct ids when truncation would collide."""
    resolve_finding_short_ids = require_callable("resolve_finding_short_ids")
    fp1, fp2 = collision_fingerprints()
    mapping = resolve_finding_short_ids([fp1, fp2])
    assert mapping[fp1] != mapping[fp2]
    assert _MC_ID_RE.match(mapping[fp1])
    assert _MC_ID_RE.match(mapping[fp2])


@pytest.mark.xfail(reason="green after CA", strict=False)
def test_resolve_finding_short_ids_is_stable_for_repeated_calls() -> None:
    """Happy — collision resolution is deterministic across repeated batch calls."""
    resolve_finding_short_ids = require_callable("resolve_finding_short_ids")
    fingerprints = list(collision_fingerprints())
    first = resolve_finding_short_ids(fingerprints)
    second = resolve_finding_short_ids(fingerprints)
    assert first == second
