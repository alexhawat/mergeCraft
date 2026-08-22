"""Behavioral pins for the shared review engine (Thermos / #380).

Sibling of ``tests/review/test_da_review_snapshot.py`` — keep that file's
``ReviewSnapshot`` construction pins; this module drives ``ReviewEngine.run``.
Hidden ``diff-review`` is not deleted. Do not grep source for ``engine.run(``
or ``timeout=engine.timeout_s(...)``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.offline_review import OfflineReviewResult
from mergecraft.review import ReviewEngine, ReviewEngineResult
from mergecraft.review.snapshot import (
    CANONICAL_STAGE_NAMES,
    DEFAULT_STAGE_TIMEOUTS_MS,
    ReviewSnapshot,
    ReviewStageSpec,
    canonical_review_snapshot,
)
from mergecraft.run_outcome import RunOutcome
from mergecraft.scm.webhooks import conforming_review_request
from tests.review.hook_review_run import HookReviewRun

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
_MISSING = object()


def _short_snapshot(*, review_ms: int = 10_000) -> ReviewSnapshot:
    stages = tuple(
        ReviewStageSpec(name=name, timeout_ms=review_ms if name == "review" else 10_000)
        for name in CANONICAL_STAGE_NAMES
    )
    return ReviewSnapshot(entry="cli", stages=stages)


async def _noop() -> None:
    return None


async def _publish_echo(payload: object) -> object:
    return payload


def _hooks(
    *,
    materialize: Any = _noop,
    analyze: Any = _noop,
    review: Any = _noop,
    publish: Any = _publish_echo,
) -> HookReviewRun[Any, Any]:
    return HookReviewRun(
        materialize_hook=materialize,
        analyze_hook=analyze,
        review_hook=review,
        publish_hook=publish,
    )


class _OrderTap:
    """Wrap a positional ``ReviewRun`` so each stage appends to ``order``."""

    def __init__(self, inner: object, order: list[str]) -> None:
        self._inner = inner
        self._order = order

    async def materialize(self) -> object:
        self._order.append("materialize")
        return await self._inner.materialize()  # type: ignore[union-attr]

    async def analyze(self) -> object:
        self._order.append("analyze")
        return await self._inner.analyze()  # type: ignore[union-attr]

    async def review(self) -> object:
        self._order.append("review")
        return await self._inner.review()  # type: ignore[union-attr]

    async def publish(self, review_out: object) -> object:
        self._order.append("publish")
        return await self._inner.publish(review_out)  # type: ignore[union-attr]


# ── Constructor + canonical timeouts ──────────────────────────────────────────


def test_review_engine_constructs_from_snapshot_without_pre_stamping() -> None:
    """Unit: callers construct ``ReviewEngine(snapshot=...)``; stages have not run."""
    snapshot = canonical_review_snapshot(entry="cli")
    engine = ReviewEngine(snapshot=snapshot)
    assert isinstance(engine, ReviewEngine)
    assert not isinstance(engine, ReviewEngineResult)
    assert engine.snapshot is snapshot
    assert engine.stages == snapshot.stages
    assert isinstance(engine.stages[0], ReviewStageSpec)
    assert engine.timeout_s("review") == DEFAULT_STAGE_TIMEOUTS_MS["review"] / 1000
    assert engine.timeout_s("materialize") == 600.0
    assert engine.timeout_s("analyze") == 600.0
    assert engine.timeout_s("review") == 3600.0
    assert engine.timeout_s("publish") == 120.0
    assert engine.result().stages_ran == ()


@pytest.mark.asyncio
async def test_review_engine_invokes_on_stage_before_each_hook() -> None:
    """Unit: ``set_on_stage`` fires at the start of every canonical stage."""
    seen: list[str] = []
    engine = ReviewEngine(snapshot=_short_snapshot())
    engine.set_on_stage(seen.append)
    await engine.run(_hooks())
    assert seen == ["materialize", "analyze", "review", "publish"]


def test_review_package_reexports_engine_types() -> None:
    """Unit: ``mergecraft.review`` re-exports the engine types, not ``run_from_snapshot``."""
    import mergecraft.review as review_pkg
    import mergecraft.review.engine as engine_mod

    assert review_pkg.ReviewEngine is ReviewEngine
    assert review_pkg.ReviewEngineResult is ReviewEngineResult
    assert review_pkg.ReviewRun is engine_mod.ReviewRun
    assert "ReviewRun" in review_pkg.__all__
    assert "HookReviewRun" not in review_pkg.__all__
    assert "HookReviewRun" not in engine_mod.__all__
    assert not hasattr(review_pkg, "HookReviewRun")
    assert not hasattr(engine_mod, "HookReviewRun")
    assert not hasattr(engine_mod, "_resolve_driver")
    assert "run_from_snapshot" not in review_pkg.__all__
    assert not hasattr(review_pkg, "run_from_snapshot")
    assert not hasattr(engine_mod, "run_from_snapshot")


def test_changed_paths_from_unified_diff_is_not_on_offline_stages() -> None:
    """Unit: path extraction lives on ``changed_paths_in_diff``, not a deleted helper."""
    import mergecraft.review.offline_stages as offline_stages

    assert not hasattr(offline_stages, "changed_paths_from_unified_diff")


def test_canonical_snapshot_records_review_timeout_as_data_not_engine_enforced() -> None:
    """Unit: 1h review timeout is snapshot data; review is agent self-timed."""
    snapshot = canonical_review_snapshot(entry="action")
    by_name = {stage.name: stage for stage in snapshot.stages}
    assert by_name["review"].timeout_ms == 3_600_000
    assert DEFAULT_STAGE_TIMEOUTS_MS["review"] == 3_600_000
    assert by_name["review"].engine_enforced is False
    for name in ("materialize", "analyze", "publish"):
        assert by_name[name].engine_enforced is True


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


# ── engine.run stage machine ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_engine_run_executes_four_hooks_in_order() -> None:
    """Happy: materialize → analyze → review → publish; publish sees review output."""
    engine = ReviewEngine(snapshot=_short_snapshot())
    order: list[str] = []

    async def materialize() -> None:
        order.append("materialize")

    async def analyze() -> None:
        order.append("analyze")

    async def review() -> str:
        order.append("review")
        return "reviewed"

    async def publish(payload: object) -> str:
        order.append("publish")
        assert payload == "reviewed"
        return "published"

    result = await engine.run(
        _hooks(materialize=materialize, analyze=analyze, review=review, publish=publish),
    )
    assert isinstance(result, ReviewEngineResult)
    assert isinstance(result.stages[0], ReviewStageSpec)
    assert result.stages == engine.stages
    assert order == list(CANONICAL_STAGE_NAMES)
    assert result.stages_ran == CANONICAL_STAGE_NAMES
    assert result.output == "published"
    assert result.published_or("missing") == "published"


@pytest.mark.asyncio
async def test_engine_run_accepts_positional_hook_driver() -> None:
    """Happy: production-style ``run(driver)`` takes a positional ``ReviewRun``."""
    engine = ReviewEngine(snapshot=_short_snapshot())
    order: list[str] = []

    async def materialize() -> None:
        order.append("materialize")

    async def analyze() -> None:
        order.append("analyze")

    async def review() -> str:
        order.append("review")
        return "reviewed"

    async def publish(payload: object) -> str:
        order.append("publish")
        assert payload == "reviewed"
        return "published"

    driver: HookReviewRun[str, str] = HookReviewRun(
        materialize_hook=materialize,
        analyze_hook=analyze,
        review_hook=review,
        publish_hook=publish,
    )
    result = await engine.run(driver)
    assert order == list(CANONICAL_STAGE_NAMES)
    assert result.output == "published"
    assert result.published_or("missing") == "published"


def test_published_or_returns_missing_when_output_is_none() -> None:
    """Edge: ``published_or`` substitutes when publish never produced a value."""
    engine = ReviewEngine(snapshot=_short_snapshot())
    assert engine.result().published_or("fallback") == "fallback"


@pytest.mark.asyncio
async def test_engine_run_timeout_omits_incomplete_stage_from_stages_ran() -> None:
    """Error: a timeout before a stage finishes must not list that stage."""
    engine = ReviewEngine(snapshot=_short_snapshot())

    async def slow_review() -> None:
        await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        await engine.run(
            _hooks(review=slow_review),
            timeouts={"review": 0.02},
        )
    assert engine.result().stages_ran == ("materialize", "analyze")


@pytest.mark.asyncio
async def test_engine_does_not_wait_for_self_timed_review_without_timeouts_overlay() -> None:
    """Edge: review ``engine_enforced=False`` is not cancelled by a 1ms snapshot budget."""
    stages = tuple(
        ReviewStageSpec(
            name=name,
            timeout_ms=1,
            engine_enforced=name != "review",
        )
        for name in CANONICAL_STAGE_NAMES
    )
    engine = ReviewEngine(snapshot=ReviewSnapshot(entry="cli", stages=stages))

    async def slower_than_one_ms() -> str:
        await asyncio.sleep(0.03)
        return "self-timed"

    result = await engine.run(_hooks(review=slower_than_one_ms))
    assert result.stages_ran == CANONICAL_STAGE_NAMES
    assert result.output == "self-timed"


@pytest.mark.asyncio
async def test_analyze_timeout_does_not_wrap_credentials_owned_by_materialize() -> None:
    """Unit: credentials-like work in materialize is not gated by the analyze budget."""
    engine = ReviewEngine(snapshot=_short_snapshot())

    async def credentials_like_materialize() -> None:
        await asyncio.sleep(0.05)

    result = await engine.run(
        _hooks(materialize=credentials_like_materialize),
        timeouts={"analyze": 0.01, "materialize": 1.0},
    )
    assert result.stages_ran == CANONICAL_STAGE_NAMES


@pytest.mark.asyncio
async def test_slow_review_succeeds_under_payload_sized_override() -> None:
    """Happy: review is not 10-minute-capped; a payload-sized override covers a slow hook."""
    engine = ReviewEngine(snapshot=canonical_review_snapshot(entry="action"))
    assert engine.timeout_s("review") == 3600.0

    async def slow_review() -> str:
        await asyncio.sleep(0.08)
        return "payload"

    result = await engine.run(
        _hooks(review=slow_review),
        timeouts={"review": 0.5},
    )
    assert result.output == "payload"
    assert result.stages_ran == CANONICAL_STAGE_NAMES


@pytest.mark.asyncio
async def test_publish_timeout_after_successful_review_omits_publish() -> None:
    """Error: publish TimeoutError after review completed; publish is not in stages_ran."""
    engine = ReviewEngine(snapshot=_short_snapshot())
    timed: list[str] = []

    async def slow_publish(_payload: object) -> None:
        await asyncio.sleep(1)

    def on_timeout(name: str) -> None:
        timed.append(name)

    with pytest.raises(TimeoutError):
        await engine.run(
            _hooks(publish=slow_publish),
            timeouts={"publish": 0.02},
            on_timeout=on_timeout,
        )
    assert timed == ["publish"]
    assert engine.result().stages_ran == ("materialize", "analyze", "review")


# ── CLI / Action / SCM entry points ───────────────────────────────────────────


def test_cli_review_timeout_cleans_up_subprocesses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Error: CLI TimeoutError cleans up subprocesses like cancel."""
    from mergecraft.cli import diff_review_cmd

    cleaned: list[str] = []
    monkeypatch.setattr(
        diff_review_cmd,
        "cleanup_review_subprocesses",
        lambda: cleaned.append("cleanup"),
    )

    async def boom(**_kwargs: object) -> OfflineReviewResult:
        raise TimeoutError

    monkeypatch.setattr(diff_review_cmd, "run_offline_diff_review", boom)

    async def boom_run(self: ReviewEngine, driver: object, /, **_kwargs: Any) -> ReviewEngineResult:
        raise TimeoutError

    monkeypatch.setattr(ReviewEngine, "run", boom_run)
    patch = tmp_path / "change.diff"
    patch.write_text(
        "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n",
        encoding="utf-8",
    )
    runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env=_DUMB_ENV,
        catch_exceptions=True,
    )
    assert cleaned == ["cleanup"]


def test_scm_conforming_request_runs_engine_and_exposes_stage_specs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration: SCM maps identity onto a snapshot; engine is not fake-run."""
    runs: list[str] = []

    async def boom_run(self: ReviewEngine, driver: object, /, **_kwargs: Any) -> ReviewEngineResult:
        runs.append("run")
        raise AssertionError("conforming_review_request must not run the engine")

    monkeypatch.setattr(ReviewEngine, "run", boom_run)
    request = conforming_review_request("github", event="pull_request", body={})
    assert request.snapshot.entry == "scm"
    assert isinstance(request.snapshot, ReviewSnapshot)
    assert request.mode == "Review"
    assert isinstance(request.stages[0], ReviewStageSpec)
    assert tuple(stage.name for stage in request.stages) == CANONICAL_STAGE_NAMES
    assert request.stages_ran == ()
    assert runs == []


def test_cli_review_drives_engine_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration: dry-run review runs materialize → analyze stage → review short-circuit → publish.

    D10 (#401): analyze must not invoke the analyzer catalog on ``--dry-run``; the engine
    stage order is unchanged. Pipeline-skip pins live in ``test_fc_dry_run_skips_analyzers``.
    """
    order: list[str] = []
    original = ReviewEngine.run

    async def wrapped(self: ReviewEngine, driver: object, /, **kwargs: Any) -> ReviewEngineResult:
        return await original(self, _OrderTap(driver, order), **kwargs)

    monkeypatch.setattr(ReviewEngine, "run", wrapped)
    monkeypatch.setattr(
        "mergecraft.review.offline_stages.run_analyzer_pipeline",
        lambda **_kwargs: None,
    )
    patch = tmp_path / "change.diff"
    patch.write_text(
        "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env=_DUMB_ENV,
        catch_exceptions=True,
    )
    assert result.exception is None, result.exception
    assert order == list(CANONICAL_STAGE_NAMES)


def test_cli_review_constructs_exactly_one_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: CLI review constructs one ``ReviewEngine``, not CLI + offline."""
    inits: list[int] = []
    orig = ReviewEngine.__init__

    def counted(self: ReviewEngine, *args: object, **kwargs: object) -> None:
        inits.append(1)
        orig(self, *args, **kwargs)

    monkeypatch.setattr(ReviewEngine, "__init__", counted)
    monkeypatch.setattr(
        "mergecraft.review.offline_stages.run_analyzer_pipeline",
        lambda **_kwargs: None,
    )
    patch = tmp_path / "change.diff"
    patch.write_text(
        "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n",
        encoding="utf-8",
    )
    runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--dry-run"],
        env=_DUMB_ENV,
        catch_exceptions=True,
    )
    assert len(inits) == 1


@pytest.mark.asyncio
async def test_action_main_calls_engine_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Integration: Action ``main`` awaits ``engine.run`` without a review-None overlay."""
    from tests.support.run_main_harness import run_main_for_test

    calls: list[str] = []
    timeout_overlays: list[object] = []
    original = ReviewEngine.run

    async def wrapped(self: ReviewEngine, driver: object, /, **kwargs: Any) -> ReviewEngineResult:
        calls.append("run")
        timeout_overlays.append(kwargs.get("timeouts", _MISSING))
        timeouts = kwargs.get("timeouts")
        assert "timeouts" not in kwargs or timeouts is None or "review" not in (timeouts or {})
        return await original(self, driver, **kwargs)

    monkeypatch.setattr(ReviewEngine, "run", wrapped)
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
    )
    assert rec.raised is None, rec.raised
    assert calls, (
        "main() must await engine.run rather than wrapping _execute_agent in the review timeout"
    )
    assert timeout_overlays, "engine.run must be awaited"
    overlay = timeout_overlays[0]
    if overlay is not _MISSING and overlay is not None:
        assert "review" not in overlay


@pytest.mark.asyncio
async def test_skip_agent_publish_is_owned_by_finalize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Error: inconclusive skip-agent must not ``_publish`` from the review hook."""
    import traceback

    import mergecraft.main as main_mod
    from mergecraft.config.settings import RepoSettings
    from tests.support.run_main_harness import run_main_for_test

    publish_stacks: list[str] = []
    orig_publish = main_mod._publish

    async def wrap_publish(*args: object, **kwargs: object) -> object:
        publish_stacks.append("".join(traceback.format_stack()))
        return await orig_publish(*args, **kwargs)

    monkeypatch.setattr(main_mod, "_publish", wrap_publish)
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
        setup_script_rc=1,
    )
    assert rec.raised is None, rec.raised
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.inconclusive
    assert rec.agent_runs == []
    assert publish_stacks, "engine publish must still call _publish"
    assert all("_run_review_after_analyze" not in stack for stack in publish_stacks)
    assert any("_finalize" in stack for stack in publish_stacks)


@pytest.mark.asyncio
async def test_skip_agent_review_returns_skip_agent_review_not_dummy_agent_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Error: skip-agent is ``SkipAgentReview``, not ``AgentResult(success=True, error=...)``."""
    import mergecraft.main as main_mod
    from mergecraft.agents.shared import AgentResult
    from mergecraft.config.settings import RepoSettings
    from mergecraft.main import SkipAgentReview
    from tests.support.run_main_harness import run_main_for_test

    captured: list[object] = []
    orig = main_mod._run_review_after_analyze

    async def wrap_review(ctx: object) -> object:
        out = await orig(ctx)
        captured.append(out)
        return out

    monkeypatch.setattr(main_mod, "_run_review_after_analyze", wrap_review)
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
        setup_script_rc=1,
    )
    assert rec.raised is None, rec.raised
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.inconclusive
    assert captured, "review stage must return a skip-agent sentinel"
    skip_out = captured[0]
    assert isinstance(skip_out, SkipAgentReview)
    assert skip_out.reason
    assert type(skip_out) is not AgentResult
    dummy_error = getattr(skip_out, "error", None)
    dummy_success = getattr(skip_out, "success", None)
    assert not (dummy_success is True and dummy_error is not None)


@pytest.mark.asyncio
async def test_action_publish_timeout_is_timed_out_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Error: publish TimeoutError after a successful review is ``RunOutcome.timed_out``."""
    import mergecraft.main as main_mod
    from mergecraft.agents.shared import AgentResult
    from mergecraft.main import MainResult
    from tests.support.run_main_harness import run_main_for_test

    async def sleepy_finalize(ctx: object, result: AgentResult) -> MainResult:
        await asyncio.sleep(1.0)
        return MainResult(success=True, outcome=RunOutcome.passed)

    monkeypatch.setattr(main_mod, "_finalize", sleepy_finalize)

    def timeout_s(self: ReviewEngine, name: str) -> float:
        if name == "publish":
            return 0.05
        return self.snapshot.timeout_ms_for(name) / 1000.0  # type: ignore[arg-type]

    monkeypatch.setattr(ReviewEngine, "timeout_s", timeout_s)
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
    )
    assert rec.raised is None, f"publish timeout must not crash main(): {rec.raised!r}"
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.timed_out


def test_protocol_and_schema_versions_alias_the_snapshot() -> None:
    """Unit: CLI/agent version literals alias ``ReviewSnapshot`` source of truth."""
    from mergecraft.cli.agent_protocol import AGENT_PROTOCOL_VERSION
    from mergecraft.cli.global_surface import CLI_JSON_SCHEMA_VERSION
    from mergecraft.review.snapshot import REVIEW_PROTOCOL_VERSION, REVIEW_SCHEMA_VERSION

    assert AGENT_PROTOCOL_VERSION == REVIEW_PROTOCOL_VERSION
    assert CLI_JSON_SCHEMA_VERSION == REVIEW_SCHEMA_VERSION


def test_agent_protocol_does_not_export_first_finding_golden_relpath() -> None:
    """Unit: golden path constant belongs in tests, not ``src/``."""
    from mergecraft.cli import agent_protocol

    assert not hasattr(agent_protocol, "FIRST_FINDING_GOLDEN_RELPATH")
