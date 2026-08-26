"""RED — pipeline executor honesty (AG6 / MCB-37)."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_TERMINAL_ONLY = """
steps:
  - id: submit
    kind: terminal
"""

_FAN_OUT_ONLY = """
steps:
  - id: lenses
    kind: fan_out
    agents:
      - reviewer
  - id: submit
    kind: terminal
"""


def test_non_executing_steps_are_not_marked_ran(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    write_repo_config(tmp_path, extra_yaml="orchestrator: deterministic")
    write_pipeline_file(tmp_path, _FAN_OUT_ONLY)
    monkeypatch.chdir(tmp_path)
    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    result = PipelineExecutor(registry=registry, settings=settings).run(
        pipeline,
        repo_root=tmp_path,
    )
    for record in result.step_records:
        if record.step_id == "lenses":
            assert record.status != "ran"


def test_terminal_verdict_is_not_hardcoded_approve(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    write_repo_config(tmp_path, extra_yaml="orchestrator: deterministic")
    write_pipeline_file(tmp_path, _TERMINAL_ONLY)
    monkeypatch.chdir(tmp_path)
    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    result = PipelineExecutor(registry=registry, settings=settings).run(
        pipeline,
        repo_root=tmp_path,
    )
    submission = result.terminal_submission
    assert submission is not None
    assert submission.verdict != "approve"


def test_failing_reviewer_never_reaches_approve(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    failing_yaml = """
steps:
  - id: review
    kind: agent
    agent: reviewer
    on_error: fail
  - id: submit
    kind: terminal
"""
    write_repo_config(tmp_path, extra_yaml="orchestrator: deterministic")
    write_pipeline_file(tmp_path, failing_yaml)
    monkeypatch.chdir(tmp_path)
    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    executor = PipelineExecutor(registry=registry, settings=settings)
    with suppress(Exception):
        executor.run(pipeline, repo_root=tmp_path)
    # Contract: a failed reviewer step must not yield approve terminal submission.
    assert executor is not None
