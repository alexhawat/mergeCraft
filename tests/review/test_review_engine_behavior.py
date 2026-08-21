"""Behavioral pins for the shared review engine (Thermos / #380).

Sibling of ``tests/review/test_da_review_snapshot.py`` — keep that file's
``"ReviewSnapshot" in source`` pins; this module asserts the engine actually
drives a run. Hidden ``diff-review`` is not deleted.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest
from pydantic import ValidationError

from mergecraft.review.engine import ReviewEngineResult, run_from_snapshot
from mergecraft.review.snapshot import (
    CANONICAL_STAGE_NAMES,
    DEFAULT_STAGE_TIMEOUTS_MS,
    ReviewSnapshot,
    ReviewStageSpec,
    canonical_review_snapshot,
    snapshot_manifest_stages,
)
from mergecraft.scm.webhooks import conforming_review_request


def test_run_from_snapshot_returns_engine_result_not_snapshot_identity() -> None:
    """Unit: callers receive ``ReviewEngineResult``, not the snapshot itself."""
    snapshot = canonical_review_snapshot(entry="cli")
    result = run_from_snapshot(snapshot)
    assert isinstance(result, ReviewEngineResult)
    assert result is not snapshot
    assert result.snapshot is snapshot
    assert result.timeout_s("review") == DEFAULT_STAGE_TIMEOUTS_MS["review"] / 1000
    assert result.stages == snapshot_manifest_stages(snapshot)
    assert result.stages_ran == CANONICAL_STAGE_NAMES


@pytest.mark.asyncio
async def test_engine_run_awaits_execute_with_kwargs() -> None:
    """Happy: ``engine.run`` actually awaits ``execute`` and forwards kwargs."""
    engine = run_from_snapshot(canonical_review_snapshot(entry="cli"))
    seen: dict[str, object] = {}

    async def execute(*, cwd: str, flag: bool) -> str:
        seen["cwd"] = cwd
        seen["flag"] = flag
        return "done"

    returned = await engine.run(execute, cwd="/tmp/review", flag=True)
    assert returned == "done"
    assert seen == {"cwd": "/tmp/review", "flag": True}


@pytest.mark.asyncio
async def test_engine_run_applies_review_timeout() -> None:
    """Error: a slow ``execute`` is cancelled by the review-stage timeout."""
    stages = tuple(
        ReviewStageSpec(
            name=name,
            timeout_ms=10 if name == "review" else DEFAULT_STAGE_TIMEOUTS_MS[name],
        )
        for name in CANONICAL_STAGE_NAMES
    )
    snapshot = ReviewSnapshot(entry="cli", stages=stages)
    engine = run_from_snapshot(snapshot)
    assert engine.timeout_s("review") == 0.01

    async def slow(**kwargs: object) -> None:
        await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        await engine.run(slow)


def test_canonical_review_snapshot_is_the_intended_constructor() -> None:
    """Unit: factory builds the frozen canonical stage set."""
    snapshot = canonical_review_snapshot(entry="action", mode="Review", source="gha")
    assert isinstance(snapshot, ReviewSnapshot)
    assert tuple(stage.name for stage in snapshot.stages) == CANONICAL_STAGE_NAMES
    assert all(stage.observable for stage in snapshot.stages)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "Fix"},
        {
            "stages": tuple(
                ReviewStageSpec(name=name, timeout_ms=1_000, observable=name != "review")
                for name in CANONICAL_STAGE_NAMES
            )
        },
        {
            "stages": tuple(
                ReviewStageSpec(name=name, timeout_ms=1_000)
                for name in reversed(CANONICAL_STAGE_NAMES)
            )
        },
    ],
)
def test_review_snapshot_rejects_invalid_contracts(kwargs: dict[str, object]) -> None:
    """Error: wrong order, unobservable stage, or bad mode raise ValidationError."""
    stages = kwargs.get("stages") or tuple(
        ReviewStageSpec(name=name, timeout_ms=DEFAULT_STAGE_TIMEOUTS_MS[name])
        for name in CANONICAL_STAGE_NAMES
    )
    mode = str(kwargs.get("mode", "Review"))
    with pytest.raises(ValidationError):
        ReviewSnapshot(entry="cli", mode=mode, stages=stages)  # type: ignore[arg-type]


def test_review_snapshot_rejects_unknown_stage_name() -> None:
    """Error: a non-canonical stage name is a validation failure."""
    with pytest.raises(ValidationError):
        ReviewStageSpec(name="compile", timeout_ms=1_000)  # type: ignore[arg-type]


def test_cli_diff_review_cmd_drives_engine_run() -> None:
    """Integration: CLI review path calls ``engine.run(`` (not snapshot-only)."""
    from mergecraft.cli import diff_review_cmd

    source = inspect.getsource(diff_review_cmd)
    assert "ReviewSnapshot" in source
    assert "engine.run(" in source or "timeout_s" in source
    assert "run_from_snapshot" in source


def test_action_main_uses_engine_timeouts_with_wait_for() -> None:
    """Integration: Action ``main.py`` times materialize + review via the engine."""
    import mergecraft.main as action_main

    source = inspect.getsource(action_main)
    compact = " ".join(source.split())
    assert "asyncio.wait_for" in source
    assert 'timeout=engine.timeout_s("materialize")' in compact
    assert 'timeout=engine.timeout_s("review")' in compact


def test_scm_conforming_request_returns_engine_stages() -> None:
    """Integration: SCM webhook request carries canonical stages from the engine."""
    request = conforming_review_request("github", event="pull_request", body={})
    names = [str(row.get("name")) for row in request.stages]
    assert names == list(CANONICAL_STAGE_NAMES)
    assert request.snapshot.entry == "scm"
    assert request.mode == "Review"
