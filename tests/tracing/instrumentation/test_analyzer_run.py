"""Behavioral contracts for analyzer pipeline child spans."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


def _finding() -> Any:
    from mergecraft.analyzers.finding import make_finding

    return make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="certain",
        message="unused import",
        path="a.py",
        start_line=1,
        end_line=1,
        source="analyzer",
    )


@pytest.mark.parametrize(
    ("adapter_result", "expected_exit", "expected_count", "expected_status"),
    [
        ("finding", 0, 1, "ok"),
        ("clean", 0, 0, "ok"),
        ("error", 1, 0, "error"),
    ],
)
def test_analyzer_run_span_reports_adapter_invocation_status(
    captured_sink: Any,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    adapter_result: str,
    expected_exit: int,
    expected_count: int,
    expected_status: str,
) -> None:
    """Finding, clean, and adapter-error paths use the current pipeline seams."""
    from mergecraft.analyzers import adapters, pipeline
    from mergecraft.analyzers.registry import get_manifest
    from mergecraft.config import RepoSettings
    from mergecraft.tracing.tracer import get_tracer_from_settings, run_root_span

    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "memory"}]}}
    )
    monkeypatch.setattr(pipeline, "load_repo_settings", lambda **_kwargs: settings)
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_kwargs: [get_manifest("ruff")])

    def _run_adapter(**_kwargs: Any) -> adapters.AdapterRunResult:
        if adapter_result == "error":
            raise OSError("adapter unavailable")
        findings = [_finding()] if adapter_result == "finding" else []
        return adapters.AdapterRunResult(findings=findings)

    monkeypatch.setattr(adapters, "run_adapter", _run_adapter)
    tracer = get_tracer_from_settings(settings)
    with run_root_span(tracer):
        state = pipeline.run_analyzer_pipeline(
            repo_root=tmp_path,
            changed_files=["a.py"],
            tier="trusted",
            shell="restricted",
        )

    captured_sink.record()
    runs = captured_sink.by_kind.get("analyzer.run", [])
    assert len(runs) == 1
    run = runs[0]
    assert run.attrs["analyzer.exit_code"] == expected_exit
    assert run.attrs["analyzer.findings_count"] == expected_count
    assert run.status == expected_status
    pipelines = captured_sink.by_kind.get("mergecraft.analyzers.pipeline", [])
    assert len(pipelines) == 1
    assert run.parent_span_id == pipelines[0].span_id
    assert len(state.findings) == expected_count
