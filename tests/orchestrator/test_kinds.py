"""AP6 orchestrator kinds — LLM default pin and terminal verdict protocol (PR AP6).

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP6, AP6.1).
Covers ``orchestrator`` settings kind (``llm`` | ``deterministic`` | ``hybrid``),
``orchestrator/executor.py``, and convention 3 — reaching a terminal pipeline
node is **not** structural approval; only ``decide_approval()`` is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.gates import decide_approval
from mergecraft.config.settings import RepoSettings, default_settings

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def test_llm_is_the_default() -> None:
    """D10 — unset ``orchestrator`` config preserves today's LLM orchestrator behaviour."""
    unset = default_settings()
    assert getattr(unset, "orchestrator", "llm") == "llm"

    merged = RepoSettings.model_validate({})
    assert getattr(merged, "orchestrator", "llm") == "llm"

    with_models = RepoSettings.model_validate({"models": ["anthropic/claude-sonnet"]})
    assert getattr(with_models, "orchestrator", "llm") == "llm"


def test_deterministic_kind_runs_the_pipeline(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    ordered_pipeline_yaml: str,
) -> None:
    """``orchestrator: deterministic`` walks the declarative step list via the registry."""
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    write_repo_config(tmp_path, extra_yaml="orchestrator: deterministic")
    write_pipeline_file(tmp_path, ordered_pipeline_yaml)
    monkeypatch.chdir(tmp_path)

    settings = load_repo_settings(root=tmp_path)
    assert settings.orchestrator == "deterministic"

    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    executor = PipelineExecutor(registry=registry, settings=settings)
    result = executor.run(pipeline, repo_root=tmp_path)

    executed_ids = [record.step_id for record in result.step_records if record.status == "ran"]
    assert executed_ids == ["classify", "review", "verify", "submit"]
    assert result.orchestrator_kind == "deterministic"
    assert result.orchestrator_tokens == 0


def test_all_kinds_terminate_through_the_same_verdict_protocol(
    tmp_path: Path,
    ordered_pipeline_yaml: str,
) -> None:
    """Convention 3 — every orchestrator kind records ``submit_review_verdict`` on ToolState."""
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.mcp.verdict import record_validated_terminal_submission
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    for kind in ("llm", "deterministic", "hybrid"):
        case_root = tmp_path / kind
        case_root.mkdir()
        write_repo_config(case_root, extra_yaml=f"orchestrator: {kind}")
        write_pipeline_file(case_root, ordered_pipeline_yaml)

        settings = load_repo_settings(root=case_root)
        registry = load_registry(settings=settings, repo_root=case_root)
        pipeline = parse_pipeline((case_root / ".mergecraft" / "pipeline.yaml").read_text())
        executor = PipelineExecutor(registry=registry, settings=settings)
        result = executor.run(pipeline, repo_root=case_root)

        assert result.terminal_submission is not None
        assert result.terminal_submission.verdict in {"approve", "request_changes"}
        assert result.terminal_protocol == "submit_review_verdict"
        assert result.verdict_recorded_via is record_validated_terminal_submission


def test_reaching_a_terminal_node_is_not_approval(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    terminal_only_pipeline_yaml: str,
) -> None:
    """Reaching the pipeline terminal node must not imply ``decide_approval`` success."""
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline

    write_repo_config(tmp_path, extra_yaml="orchestrator: deterministic")
    write_pipeline_file(tmp_path, terminal_only_pipeline_yaml)
    monkeypatch.chdir(tmp_path)

    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    result = PipelineExecutor(registry=registry, settings=settings).run(
        pipeline,
        repo_root=tmp_path,
    )

    assert any(
        record.step_id == "submit" and record.status == "ran" for record in result.step_records
    )
    assert result.structural_approval is False
    assert decide_approval([], run_succeeded=True, tier="trusted") == "neutral"
    assert result.policy_verdict != "success"
