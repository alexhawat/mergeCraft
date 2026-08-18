"""DG8.1 — classifier-derived effort band (no fake minute estimates)."""

from __future__ import annotations

import re

import pytest


def _classify_effort_band(*args: object, **kwargs: object) -> object:
    from mergecraft.pr.effort_band import classify_effort_band

    return classify_effort_band(*args, **kwargs)


_EFFORT_BANDS = frozenset({"xs", "s", "m", "l", "xl"})
_MINUTE_PATTERN = re.compile(r"\b\d+\s*(?:min(?:ute)?s?|hrs?|hours?)\b", re.IGNORECASE)


@pytest.mark.xfail(reason="green after DG8.2: effort band classifier", strict=False)
def test_emits_a_band_not_a_fake_minute_estimate(
    sample_diff: str,
    sample_pr_metadata: dict[str, object],
) -> None:
    """Effort is a discrete band derived from change signals — never a minute guess."""
    result = _classify_effort_band(
        diff=sample_diff,
        pr_metadata=sample_pr_metadata,
        change_signals={"files_changed": 1, "lines_added": 3, "lines_deleted": 0},
    )

    band = result.band
    assert band in _EFFORT_BANDS, f"unexpected effort band: {band!r}"

    rationale = getattr(result, "rationale", "")
    assert isinstance(rationale, str)
    assert not _MINUTE_PATTERN.search(rationale), (
        "effort output must not invent minute/hour estimates"
    )

    assert getattr(result, "estimated_minutes", None) is None
    assert getattr(result, "minutes", None) is None
