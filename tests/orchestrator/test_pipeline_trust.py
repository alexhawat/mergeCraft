"""AP6 pipeline trust gate — repo pipelines gated like ``setupScript`` (PR AP6).

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP6, AP6.1).
Covers D9 — untrusted sources never execute a repo-supplied pipeline; the
operator's pipeline runs instead. Mirrors ``main._run_setup_script_phase`` trust
ordering from ``tests/security/test_trust_ordering.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_XFAIL = pytest.mark.xfail(strict=True, reason="AP6.2")


@_XFAIL
def test_untrusted_source_pipeline_is_ignored(
    tmp_path: Path,
    hostile_skip_verifier_yaml: str,
    operator_pipeline_yaml: str,
) -> None:
    """D9 — repo pipeline is ignored on untrusted tier with a recorded skip reason."""
    from mergecraft.orchestrator.pipeline import parse_pipeline
    from mergecraft.orchestrator.trust import resolve_effective_pipeline
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.config.settings import load_repo_settings

    write_repo_config(tmp_path)
    write_pipeline_file(tmp_path, hostile_skip_verifier_yaml, name="pipeline.yaml")
    settings = load_repo_settings(root=tmp_path)
    repo_pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    operator_pipeline = parse_pipeline(operator_pipeline_yaml)

    effective, skip_reason = resolve_effective_pipeline(
        settings=settings,
        trust_tier="untrusted",
        repo_pipeline=repo_pipeline,
        operator_pipeline=operator_pipeline,
        event_name="pull_request",
    )

    assert effective.step_ids() == ["review", "verify", "submit"]
    assert "skipped" in skip_reason.lower()
    assert "untrusted" in skip_reason.lower()
    assert "pipeline" in skip_reason.lower()


@_XFAIL
def test_untrusted_pipeline_cannot_skip_the_verifier(
    tmp_path: Path,
    hostile_skip_verifier_yaml: str,
    operator_pipeline_yaml: str,
) -> None:
    """Concrete attack — hostile repo pipeline that omits verify must not run."""
    from mergecraft.orchestrator.executor import PipelineExecutor
    from mergecraft.orchestrator.pipeline import parse_pipeline
    from mergecraft.orchestrator.trust import resolve_effective_pipeline
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.agents.registry import load_registry
    from mergecraft.config.settings import load_repo_settings

    write_repo_config(tmp_path)
    write_pipeline_file(tmp_path, hostile_skip_verifier_yaml)
    settings = load_repo_settings(root=tmp_path)
    registry = load_registry(settings=settings, repo_root=tmp_path)
    repo_pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    operator_pipeline = parse_pipeline(operator_pipeline_yaml)

    effective, _skip_reason = resolve_effective_pipeline(
        settings=settings,
        trust_tier="untrusted",
        repo_pipeline=repo_pipeline,
        operator_pipeline=operator_pipeline,
        event_name="pull_request",
    )

    result = PipelineExecutor(registry=registry, settings=settings).run(
        effective,
        repo_root=tmp_path,
    )
    ran = {record.step_id for record in result.step_records if record.status == "ran"}
    assert "verify" in ran
    assert result.verifier_skipped_by_repo_pipeline is False


@_XFAIL
def test_operator_pipeline_is_used_instead(
    tmp_path: Path,
    hostile_skip_verifier_yaml: str,
    operator_pipeline_yaml: str,
) -> None:
    """Untrusted tier executes the operator pipeline, not the repo file."""
    from mergecraft.orchestrator.pipeline import parse_pipeline
    from mergecraft.orchestrator.trust import resolve_effective_pipeline
    from tests.orchestrator.conftest import write_pipeline_file, write_repo_config

    from mergecraft.config.settings import load_repo_settings

    write_repo_config(tmp_path)
    write_pipeline_file(tmp_path, hostile_skip_verifier_yaml)
    settings = load_repo_settings(root=tmp_path)
    repo_pipeline = parse_pipeline((tmp_path / ".mergecraft" / "pipeline.yaml").read_text())
    operator_pipeline = parse_pipeline(operator_pipeline_yaml)

    effective, skip_reason = resolve_effective_pipeline(
        settings=settings,
        trust_tier="untrusted",
        repo_pipeline=repo_pipeline,
        operator_pipeline=operator_pipeline,
        event_name="pull_request_target",
    )

    assert effective.source == "operator"
    assert effective.step_ids() == operator_pipeline.step_ids()
    assert effective.step_ids() != repo_pipeline.step_ids()
    assert skip_reason.endswith("pull_request_target event)")
