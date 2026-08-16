"""Pluggable orchestrator — declarative pipeline file and deterministic executor (AP6)."""

from mergecraft.orchestrator.executor import PipelineExecutor, PipelineRunResult, StepRecord
from mergecraft.orchestrator.pipeline import (
    PipelineDefinition,
    PipelineValidationError,
    parse_pipeline,
    validate_predicate,
)
from mergecraft.orchestrator.trust import resolve_effective_pipeline

__all__ = [
    "PipelineDefinition",
    "PipelineExecutor",
    "PipelineRunResult",
    "PipelineValidationError",
    "StepRecord",
    "parse_pipeline",
    "resolve_effective_pipeline",
    "validate_predicate",
]
