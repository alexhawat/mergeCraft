"""Branch coverage for plan-12 publish paths in ``mergecraft.main``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.config.settings import RepoSettings
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.run_packet import prepare_run_packet
from mergecraft.main import RunContext, RunOutcome
from tests.evidence.test_run_packet import _make_ctx

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class _UsageRow:
    total_tokens: int


def _publish() -> Any:
    import mergecraft.main as main_mod

    return main_mod._publish


def _token_summary() -> Any:
    import mergecraft.main as main_mod

    return main_mod._token_summary


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([], None),
        ([_UsageRow(total_tokens=100), _UsageRow(total_tokens=50)], "100, 50"),
    ],
)
def test_token_summary_formats_usage_entries(rows: list[_UsageRow], expected: str | None) -> None:
    assert _token_summary()(rows) == expected


@pytest.mark.asyncio
async def test_publish_emit_false_writes_deterministic_record_and_step_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_context = _make_ctx(tmp_path)
    tool_context.tool_state.pr_number = 546
    prepared = prepare_run_packet(tool_context, run_succeeded=True)
    assert prepared is not None
    tool_context.tool_state.prepared_run_packet = prepared

    deterministic_calls: list[dict[str, Any]] = []
    step_summaries: list[str] = []

    async def _capture_deterministic(**kwargs: Any) -> None:
        deterministic_calls.append(kwargs)

    def _capture_step_summary(body: str) -> None:
        step_summaries.append(body)

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    import mergecraft.main as main_mod
    import mergecraft.utils.step_summary as step_summary_mod

    monkeypatch.setattr(main_mod, "persist_learnings", _noop)
    monkeypatch.setattr(main_mod, "report_status_checks", _noop)
    monkeypatch.setattr(main_mod, "publish_deterministic_record", _capture_deterministic)
    monkeypatch.setattr(step_summary_mod, "append_step_summary", _capture_step_summary)

    run_ctx = RunContext(settings=RepoSettings(), tool_context=tool_context)
    await _publish()(
        run_ctx,
        outcome=RunOutcome.passed,
        failure_reason=None,
        emit=False,
    )

    assert deterministic_calls
    assert deterministic_calls[0]["pull_number"] == 546
    assert step_summaries


@pytest.mark.asyncio
async def test_publish_resolves_pull_number_from_issue_number(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_context = _make_ctx(tmp_path)
    tool_context.tool_state.pr_number = None
    tool_context.payload.event.issue_number = 99
    prepared = prepare_run_packet(tool_context, run_succeeded=True)
    assert prepared is not None
    tool_context.tool_state.prepared_run_packet = prepared

    deterministic_calls: list[dict[str, Any]] = []

    async def _capture_deterministic(**kwargs: Any) -> None:
        deterministic_calls.append(kwargs)

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    import mergecraft.main as main_mod
    import mergecraft.utils.step_summary as step_summary_mod

    monkeypatch.setattr(main_mod, "persist_learnings", _noop)
    monkeypatch.setattr(main_mod, "report_status_checks", _noop)
    monkeypatch.setattr(main_mod, "publish_deterministic_record", _capture_deterministic)
    monkeypatch.setattr(step_summary_mod, "append_step_summary", lambda _body: None)

    run_ctx = RunContext(settings=RepoSettings(), tool_context=tool_context)
    await _publish()(
        run_ctx,
        outcome=RunOutcome.passed,
        failure_reason=None,
        emit=False,
    )

    assert deterministic_calls
    assert deterministic_calls[0]["pull_number"] == 99


@pytest.mark.asyncio
async def test_publish_passes_rejection_reason_for_no_verdict_packet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_context = _make_ctx(tmp_path)
    tool_context.tool_state.pr_number = 546
    packet = build_packet(
        change_id="acme/demo#546",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=[],
        findings=[],
        deterministic_checks=[],
        self_assessment={"would_approve": False, "sha": "abc"},
    )
    tool_context.tool_state.prepared_run_packet = packet
    no_verdict_packet = packet

    deterministic_calls: list[dict[str, Any]] = []

    async def _capture_deterministic(**kwargs: Any) -> None:
        deterministic_calls.append(kwargs)

    async def _noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    def _resolve_packet(_ctx: Any, *, run_succeeded: bool) -> Any:
        assert run_succeeded is False
        return no_verdict_packet

    import mergecraft.main as main_mod
    import mergecraft.utils.step_summary as step_summary_mod

    monkeypatch.setattr(main_mod, "resolve_prepared_run_packet", _resolve_packet)
    monkeypatch.setattr(main_mod, "persist_learnings", _noop)
    monkeypatch.setattr(main_mod, "report_status_checks", _noop)
    monkeypatch.setattr(main_mod, "publish_deterministic_record", _capture_deterministic)
    monkeypatch.setattr(step_summary_mod, "append_step_summary", lambda _body: None)

    run_ctx = RunContext(settings=RepoSettings(), tool_context=tool_context)
    await _publish()(
        run_ctx,
        outcome=RunOutcome.inconclusive,
        failure_reason="provider_success_without_submission",
        emit=False,
    )

    assert deterministic_calls
    assert deterministic_calls[0]["rejection_reason"] == "provider_success_without_submission"
