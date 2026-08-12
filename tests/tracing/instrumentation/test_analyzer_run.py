"""W3.3 — ``analyzer.run`` spans carry id, exit_code, findings_count, duration.

W4 must emit one ``analyzer.run`` span per analyzer in
``run_analyzer_pipeline`` — both the parent ``mergecraft.analyzers.pipeline``
and the per-analyzer children. Each ``analyzer.run`` span must carry:

- ``analyzer.id`` — the manifest id (matches ``AnalyzerStatusRow.id``).
- ``analyzer.exit_code`` — 0 on success, non-zero on raised / unavailable.
- ``analyzer.findings_count`` — the number of findings produced.
- ``analyzer.duration_ms`` — wall-clock duration of the adapter run.

Plus a parametric edge case: a run with **zero findings** still emits an
``analyzer.run`` span whose ``findings_count`` is ``0`` and ``exit_code``
is ``0``.

The fixtures here drive ``run_analyzer_pipeline`` with a tiny repo and a
recording analyzer adapter so the spans land deterministically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def _make_repo(tmp_path: Path, *, files: list[str]) -> Path:
    """Create a minimal repo with ``.mergecraft/config.yaml`` and the given files."""
    (tmp_path / ".mergecraft").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        "tracing:\n  enabled: true\n  sinks:\n    - type: memory\nanalyzers:\n  enabled: true\n",
        encoding="utf-8",
    )
    for path in files:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("print('hello')\n", encoding="utf-8")
    return tmp_path


def _register_demo_analyzer(*, finding_count: int, exit_code: int = 0) -> Any:
    """Register an in-tree analyzer that records its run.

    Returns the manifest id so tests can assert the analyzer.run span
    exists for it.
    """
    from mergecraft.analyzers.finding import Finding, FindingLocation, FindingSeverity
    from mergecraft.analyzers.registry import AnalyzerManifest, register_manifest

    async def collect(  # type: ignore[no-untyped-def]
        repo_root: Path,
        changed_files: list[str],
        tier: str,
        base_ref: str | None = None,
        offline: bool = False,
    ) -> Any:
        from mergecraft.analyzers.adapters import AdapterRunResult

        findings: list[Finding] = []
        if finding_count > 0 and changed_files:
            findings.append(
                Finding(
                    id="demo.finding.1",
                    analyzer="demo",
                    severity=FindingSeverity.warning,
                    message="demo finding",
                    location=FindingLocation(path=changed_files[0], start_line=1),
                )
            )
        if exit_code != 0:
            msg = f"demo adapter exit {exit_code}"
            raise RuntimeError(msg)
        return AdapterRunResult(
            findings=findings, skip_reason=None, version_note="0.0.1", config_note=""
        )

    manifest = AnalyzerManifest(
        id="demo",
        description="in-tree demo analyzer for W3.3",
        collect=collect,
    )
    register_manifest(manifest)
    return manifest.id


@pytest.mark.xfail(reason="green after W4: analyzer.run instrumentation", strict=False)
def test_analyzer_run_spans_carry_id_exit_code_findings_count_duration(
    captured_sink: Any, tmp_path: Path
) -> None:
    """W3.3 — happy path: one ``analyzer.run`` per analyzer with the four attributes."""
    _make_repo(tmp_path, files=["src/example.py"])
    _register_demo_analyzer(finding_count=2)

    from mergecraft.analyzers.pipeline import run_analyzer_pipeline

    state = run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["src/example.py"],
        tier="trusted",
        diff_text="@@\n+hello\n",
    )
    assert state.ran is True

    captured_sink.record()
    analyzer_runs = captured_sink.by_kind.get("analyzer.run", [])
    assert analyzer_runs, "no analyzer.run spans recorded"
    assert len(analyzer_runs) == 1

    attrs = analyzer_runs[0].attrs
    assert attrs.get("analyzer.id") == "demo"
    assert attrs.get("analyzer.exit_code") == 0
    assert attrs.get("analyzer.findings_count") == 2
    assert isinstance(attrs.get("analyzer.duration_ms"), int)
    assert attrs.get("analyzer.duration_ms") >= 0


@pytest.mark.xfail(reason="green after W4: analyzer.run instrumentation", strict=False)
def test_analyzer_run_span_records_zero_findings(captured_sink: Any, tmp_path: Path) -> None:
    """W3.3 (edge) — an analyzer that produces no findings still emits a span."""
    _make_repo(tmp_path, files=["src/example.py"])
    _register_demo_analyzer(finding_count=0)

    from mergecraft.analyzers.pipeline import run_analyzer_pipeline

    state = run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["src/example.py"],
        tier="trusted",
        diff_text="@@\n+hello\n",
    )
    assert state.ran is True

    captured_sink.record()
    analyzer_runs = captured_sink.by_kind.get("analyzer.run", [])
    assert len(analyzer_runs) == 1
    assert analyzer_runs[0].attrs.get("analyzer.findings_count") == 0
    assert analyzer_runs[0].attrs.get("analyzer.exit_code") == 0


@pytest.mark.xfail(reason="green after W4: analyzer.run instrumentation", strict=False)
def test_analyzer_run_span_records_non_zero_exit_on_failure(
    captured_sink: Any, tmp_path: Path
) -> None:
    """W3.3 (error) — a failing analyzer still emits a span with a non-zero exit code."""
    _make_repo(tmp_path, files=["src/example.py"])
    _register_demo_analyzer(finding_count=0, exit_code=1)

    from mergecraft.analyzers.pipeline import run_analyzer_pipeline

    state = run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["src/example.py"],
        tier="trusted",
        diff_text="@@\n+hello\n",
    )
    # Pipeline as a whole may succeed (other analyzers may run); this test
    # only cares about the demo analyzer's exit_code attribute.
    _ = state

    captured_sink.record()
    analyzer_runs = captured_sink.by_kind.get("analyzer.run", [])
    demo_runs = [event for event in analyzer_runs if event.attrs.get("analyzer.id") == "demo"]
    assert len(demo_runs) == 1
    assert demo_runs[0].attrs.get("analyzer.exit_code") != 0


@pytest.mark.xfail(reason="green after W4: analyzer.run instrumentation", strict=False)
def test_analyzer_pipeline_parent_span_present(captured_sink: Any, tmp_path: Path) -> None:
    """W3.3 (parent) — ``mergecraft.analyzers.pipeline`` is the parent of ``analyzer.run``."""
    _make_repo(tmp_path, files=["src/example.py"])
    _register_demo_analyzer(finding_count=1)

    from mergecraft.analyzers.pipeline import run_analyzer_pipeline

    run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=["src/example.py"],
        tier="trusted",
        diff_text="@@\n+hello\n",
    )

    captured_sink.record()
    pipeline_spans = captured_sink.by_kind.get("mergecraft.analyzers.pipeline", [])
    assert len(pipeline_spans) == 1
    parent_id = pipeline_spans[0].span_id

    child_runs = [
        event
        for event in captured_sink.by_kind.get("analyzer.run", [])
        if event.parent_span_id == parent_id
    ]
    assert child_runs, "analyzer.run spans must parent under the pipeline span"


__all__ = [
    "test_analyzer_pipeline_parent_span_present",
    "test_analyzer_run_span_records_non_zero_exit_on_failure",
    "test_analyzer_run_span_records_zero_findings",
    "test_analyzer_run_spans_carry_id_exit_code_findings_count_duration",
]
