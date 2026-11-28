"""OpenAI Agents SDK integration for mergeCraft review steps.

Install with ``pip install mergecraft-action[agents]`` (or ``uv sync --extra agents``).
"""

from __future__ import annotations

from mergecraft.agents_sdk.agent import review_agent
from mergecraft.agents_sdk.guardrails import (
    filter_guarded_findings,
    review_output_guardrail,
    sanitize_review_output,
)
from mergecraft.agents_sdk.loop import ReviewLoopResult, run_review_loop
from mergecraft.agents_sdk.model import AgentsSdkModelConfig, resolve_model_config
from mergecraft.agents_sdk.report import (
    AGENTS_SDK_REVIEW_SCHEMA,
    AgentsSdkReviewReport,
    build_review_report,
    render_review_markdown,
)
from mergecraft.agents_sdk.types import ReviewFinding, ReviewFindingsReport

__all__ = [
    "AGENTS_SDK_REVIEW_SCHEMA",
    "AgentsSdkModelConfig",
    "AgentsSdkReviewReport",
    "ReviewFinding",
    "ReviewFindingsReport",
    "ReviewLoopResult",
    "build_review_report",
    "filter_guarded_findings",
    "render_review_markdown",
    "resolve_model_config",
    "review_agent",
    "review_output_guardrail",
    "run_review_loop",
    "sanitize_review_output",
]
