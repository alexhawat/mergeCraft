"""Pipeline trust gate — repo pipelines honoured only at trusted tier (AP6 / D9)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings
    from mergecraft.orchestrator.pipeline import PipelineDefinition


def resolve_effective_pipeline(
    *,
    settings: RepoSettings,
    trust_tier: str,
    repo_pipeline: PipelineDefinition,
    operator_pipeline: PipelineDefinition,
    event_name: str,
) -> tuple[PipelineDefinition, str]:
    """Select the pipeline to execute, mirroring ``setup_script`` trust ordering (D9).

    Untrusted sources never execute a repo-supplied pipeline — the operator's
    pipeline runs instead with a recorded skip reason.
    """
    del settings
    if trust_tier == "trusted":
        return repo_pipeline, ""

    skip_reason = f"skipped repo pipeline on untrusted tier ({event_name} event)"
    operator_copy = operator_pipeline.model_copy(update={"source": "operator"})
    return operator_copy, skip_reason


__all__ = ["resolve_effective_pipeline"]
