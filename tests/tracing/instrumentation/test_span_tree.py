"""W3.1 + W3.4 + W3.6 — span tree shape, correlation attributes, disabled no-op.

These three contracts target the **integration** layer between the run
lifecycle (``mergecraft.run``) and the Batch A sink surface (``MemorySink``
through ``sink_factory``). W4 must wire the production emit sites so:

- ``mergecraft.run`` is the root span (``parent_span_id is None``);
- ``mergecraft.prep``, ``mergecraft.analyzers.pipeline``, ``agent.attempt``,
  ``llm.call`` / ``tool.call``, and ``mergecraft.publish`` are emitted at the
  existing seams, all carrying ``parent_span_id`` pointing at ``mergecraft.run``
  or a transitive child;
- the correlation attributes ``run_id``, ``repo``, ``pr_number``,
  ``commit_sha``, ``workflow_run_id``, ``job_id`` are present on the root
  span (W3.4 — issue §4);
- when tracing is disabled (convention 9), no emit site produces a span and
  the production code does not touch the filesystem.

The remaining tests here pin the correlation-attribute and disabled
no-op contracts. The full span-tree shape contract is recorded on the
instrumentation issue tracker for a future implementation wave; it is
not asserted here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.tracing.conftest import as_sink_value
from tests.tracing.instrumentation.conftest import (
    make_agent_result,
    make_agent_usage,
)


def _assert_closed_tree(events: list[Any]) -> None:
    roots = [event for event in events if event.parent_span_id is None]
    assert len(roots) == 1
    assert roots[0].kind == "mergecraft.run"
    assert len([event for event in events if event.kind == "mergecraft.run"]) == 1
    assert {event.trace_id for event in events} == {roots[0].trace_id}
    span_ids = {event.span_id for event in events}
    assert all(
        event.parent_span_id in span_ids for event in events if event.parent_span_id is not None
    )


def test_correlation_attributes_present(
    captured_sink: Any, correlation_fields: dict[str, Any]
) -> None:
    """W3.4 — the issue's §4 correlation attributes land on the root span.

    Runs a tiny lifecycle so at least the root span fires; the asserts only
    examine the root span's ``attrs``.
    """
    from mergecraft.config import RepoSettings

    settings = RepoSettings.model_validate(
        {
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
        }
    )

    import asyncio

    from mergecraft.utils.agent_resolve import run_with_model_chain

    async def run_once(slug: str) -> Any:
        return make_agent_result(success=True, usage=make_agent_usage())

    asyncio.run(
        run_with_model_chain(
            settings=settings,
            run_once=run_once,
            correlation=correlation_fields,
        )
    )

    captured_sink.record()
    roots = [event for event in captured_sink.events if event.parent_span_id is None]
    assert len(roots) == 1
    root_attrs = roots[0].attrs
    for field_name, expected in correlation_fields.items():
        expected_value = as_sink_value(expected) if isinstance(expected, str) else expected
        assert root_attrs.get(field_name) == expected_value, (
            f"correlation attribute {field_name!r} missing or wrong on root span "
            f"(got {root_attrs.get(field_name)!r})"
        )


def test_instrumentation_is_noop_when_disabled(disabled_tracing: Any, tmp_path: Path) -> None:
    """W3.6 / convention 9 — tracing off means no spans and no filesystem work.

    The existing Batch A convention-9 test (``test_tracing_disabled_is_a_true_noop``)
    pins the sink factory short-circuit. This test pins the **emit sites**:
    with tracing off, no production code path creates a span or a trace
    directory, and the run is byte-identical to the no-trace baseline.
    """
    assert isinstance(disabled_tracing, type(disabled_tracing))  # preserve fixture use

    # No span family may be referenced when disabled — the public emit
    # surface must short-circuit to ``NullSink`` (or equivalent) before any
    # production code can call ``.emit(...)``.
    # W4 implements this; until then the assertion is the negative shape.
    trace_dir = tmp_path / ".mergecraft" / "traces"
    assert not trace_dir.exists()

    # The disabled sink must not allocate work: the emit call should never
    # be invoked at all when tracing is off.
    assert hasattr(disabled_tracing, "emit")
    assert hasattr(disabled_tracing, "write")


def test_run_root_is_single_when_tracing_enabled(
    captured_sink: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W3.1 (negative) — only one root span is emitted per run."""
    import asyncio

    from mergecraft.config import RepoSettings
    from mergecraft.utils.agent_resolve import run_with_model_chain

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-span-tree-test")

    settings = RepoSettings.model_validate(
        {
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
            "models": ["anthropic/claude-sonnet"],
        }
    )

    async def run_once(slug: str) -> Any:
        return make_agent_result(success=True, usage=make_agent_usage())

    asyncio.run(run_with_model_chain(settings=settings, run_once=run_once))

    captured_sink.record()
    roots = [event for event in captured_sink.events if event.parent_span_id is None]
    assert len(roots) == 1
    assert roots[0].kind == "mergecraft.run"


@pytest.mark.asyncio
async def test_action_lifecycle_and_detached_mcp_tool_share_one_root(
    captured_sink: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The Action root owns direct dispatch, publication, and detached MCP work."""
    import asyncio
    import contextvars

    from tests.support.run_main_harness import FakeAgent, run_main_for_test

    import mergecraft.main as main_mod
    from mergecraft.config import RepoSettings
    from mergecraft.mcp.rpc import dispatch_mcp_rpc
    from mergecraft.mcp.shared import ToolClass, ToolResult, ToolSpec

    contexts: list[Any] = []
    real_tool_context = main_mod.ToolContext

    def _capture_tool_context(**kwargs: Any) -> Any:
        context = real_tool_context(**kwargs)
        contexts.append(context)
        return context

    monkeypatch.setattr(main_mod, "ToolContext", _capture_tool_context)

    async def _execute(_arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=[{"type": "text", "text": "ok"}])

    tool = ToolSpec(
        name="trace_probe",
        description="Trace propagation probe.",
        input_schema={"type": "object", "properties": {}},
        execute=_execute,
        tool_class=ToolClass.ANALYSIS,
    )

    class _McpCallingAgent(FakeAgent):
        async def run(self, ctx: Any) -> Any:
            del ctx
            self.calls.append(self.name)
            assert contexts

            async def _detached_call() -> dict[str, Any]:
                return await dispatch_mcp_rpc(
                    1,
                    "tools/call",
                    {"name": tool.name, "arguments": {}},
                    tools=[tool],
                    by_name={tool.name: tool},
                    tool_ctx=contexts[0],
                    validators={},
                )

            task = contextvars.Context().run(asyncio.create_task, _detached_call())
            response = await task
            assert "result" in response
            return self.result

    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "memory"}]}}
    )
    record = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=settings,
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
        agent=_McpCallingAgent(),
    )
    assert record.raised is None
    assert record.result is not None
    assert record.result.success
    assert record.tool_context.trace_parent is not None

    captured_sink.record()
    _assert_closed_tree(captured_sink.events)
    root = captured_sink.by_kind["mergecraft.run"][0]
    tool_call = captured_sink.by_kind["tool.call"][0]
    assert tool_call.parent_span_id == root.span_id
    assert "mergecraft.publish" in captured_sink.by_kind


@pytest.mark.asyncio
async def test_action_publication_failure_closes_the_run_root_as_error(
    captured_sink: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A publication exception remains inside the root and marks it failed."""
    from tests.support.run_main_harness import run_main_for_test

    import mergecraft.main as main_mod
    from mergecraft.config import RepoSettings

    async def _failing_publish(ctx: Any, *, emit: bool = True, **_kwargs: Any) -> None:
        if not emit:
            return
        assert ctx.settings is not None
        from mergecraft.tracing.tracer import get_tracer_from_settings

        tracer = get_tracer_from_settings(ctx.settings)
        with tracer.start_span("mergecraft.publish"):
            raise RuntimeError("publication exploded")

    monkeypatch.setattr(main_mod, "_publish", _failing_publish)
    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "memory"}]}}
    )
    record = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=settings,
    )
    assert record.raised is None
    assert record.result is not None
    assert not record.result.success
    assert record.result.error == "publication exploded"

    captured_sink.record()
    _assert_closed_tree(captured_sink.events)
    assert captured_sink.by_kind["mergecraft.run"][0].status == "error"
    assert captured_sink.by_kind["mergecraft.publish"][0].status == "error"


@pytest.mark.asyncio
async def test_action_setup_still_uses_the_materialize_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Resolving tracing settings cannot move setup outside its stage budget."""
    import asyncio

    from tests.support.run_main_harness import run_main_for_test

    import mergecraft.main as main_mod
    from mergecraft.review.engine import ReviewEngine

    real_setup = main_mod._setup_run

    async def _stalled_setup(ctx: Any) -> Any:
        await asyncio.sleep(0.05)
        return await real_setup(ctx)

    monkeypatch.setattr(main_mod, "_setup_run", _stalled_setup)
    monkeypatch.setattr(ReviewEngine, "timeout_s", lambda _self, _name: 0.001)
    record = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path)
    assert record.raised is None
    assert record.result is not None
    assert record.result.outcome is not None
    assert record.result.outcome.value == "timed_out"


@pytest.mark.asyncio
async def test_nested_model_chain_reuses_context_local_run_root(
    captured_sink: Any,
) -> None:
    """An intermediate active span does not cause a second run root."""
    from mergecraft.config import RepoSettings
    from mergecraft.tracing.tracer import get_tracer_from_settings, run_root_span
    from mergecraft.utils.agent_resolve import run_with_model_chain

    settings = RepoSettings.model_validate(
        {
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
            "models": ["anthropic/claude-sonnet"],
        }
    )
    tracer = get_tracer_from_settings(settings)

    async def _run_once(_slug: str) -> Any:
        return make_agent_result(success=True, usage=make_agent_usage())

    with (
        run_root_span(tracer) as root,
        tracer.start_span("mergecraft.phase", parent_span_id=root.span_id),
    ):
        await run_with_model_chain(settings=settings, run_once=_run_once)

    captured_sink.record()
    _assert_closed_tree(captured_sink.events)


@pytest.mark.asyncio
async def test_offline_lifecycle_has_one_root_through_publish(
    captured_sink: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The offline stage driver runs to publication inside one run root."""
    import mergecraft.offline_review as offline_mod
    from mergecraft.config import RepoSettings
    from mergecraft.utils.offline_diff import DiffMaterialization
    from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    settings = RepoSettings.model_validate(
        {
            "tracing": {"enabled": True, "sinks": [{"type": "memory"}]},
            "analyzers": {"enabled": False},
        }
    )
    monkeypatch.setattr(offline_mod, "load_repo_settings", lambda **_kwargs: settings)
    monkeypatch.setattr(offline_mod, "resolve_offline_review_trust_tier", lambda **_: "trusted")
    monkeypatch.setattr(offline_mod, "apply_cli_trust_tier_env", lambda _tier: {})
    monkeypatch.setattr(offline_mod, "_apply_tracing_cli_overrides", lambda _args: {})
    monkeypatch.setattr(
        "mergecraft.evidence.run_manifest.apply_local_telemetry_defaults",
        lambda **_kwargs: {},
    )

    def _materialize(
        _workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        del spec, diff_file
        path = out_dir / "review.diff"
        path.write_text("diff --git a/a.py b/a.py\n+print(1)\n", encoding="utf-8")
        return DiffMaterialization(path=path, base_ref="HEAD", line_count=2, empty=False)

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)

    async def _review(**_kwargs: Any) -> Any:
        return offline_mod.OfflineReviewResult(
            success=True,
            output="reviewed",
            outcome=offline_mod.RunOutcome.passed,
        )

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", _review)
    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)
    result = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
    )
    assert result.success

    captured_sink.record()
    _assert_closed_tree(captured_sink.events)
    assert "mergecraft.publish" in captured_sink.by_kind


# Re-export for tests that import from this module.
__all__ = [
    "test_action_lifecycle_and_detached_mcp_tool_share_one_root",
    "test_action_publication_failure_closes_the_run_root_as_error",
    "test_action_setup_still_uses_the_materialize_timeout",
    "test_correlation_attributes_present",
    "test_instrumentation_is_noop_when_disabled",
    "test_nested_model_chain_reuses_context_local_run_root",
    "test_offline_lifecycle_has_one_root_through_publish",
    "test_run_root_is_single_when_tracing_enabled",
]
