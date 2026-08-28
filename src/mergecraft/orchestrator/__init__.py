"""Pluggable orchestrator — declarative pipeline file and deterministic executor (AP6).

.. warning:: Experimental. ``PipelineExecutor`` is a preview stub for
   ``mergecraft pipeline show``; it does not run registry agents or gate
   production reviews.
"""

from mergecraft.orchestrator.decisions import (
    DecisionNodeKind,
    DecisionSchemaError,
    run_decision_node,
)
from mergecraft.orchestrator.executor import (
    PipelineExecutor,  # experimental preview stub
    PipelineRunResult,
    StepRecord,
)
from mergecraft.orchestrator.pipeline import (
    PipelineDefinition,
    PipelineValidationError,
    parse_pipeline,
    validate_predicate,
)
from mergecraft.orchestrator.trust import resolve_effective_pipeline

__all__ = [
    "DecisionNodeKind",
    "DecisionSchemaError",
    "PipelineDefinition",
    "PipelineExecutor",
    "PipelineRunResult",
    "PipelineValidationError",
    "StepRecord",
    "parse_pipeline",
    "resolve_effective_pipeline",
    "run_decision_node",
    "validate_predicate",
]
