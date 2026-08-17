"""Deterministic pipeline executor — walks steps and records verdict protocol (AP6)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from mergecraft.agents.gates import decide_approval
from mergecraft.agents.registry import AgentRole, Registry, resolve_agent_ref
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.mcp.verdict import record_validated_terminal_submission
from mergecraft.modes import compute_modes
from mergecraft.orchestrator.decisions import (
    DecisionNodeKind,
    StructuredDecisionClient,
    run_decision_node,
)
from mergecraft.orchestrator.pipeline import (
    PipelineDefinition,
    PipelineStepKind,
    evaluate_predicate,
)
from mergecraft.types import XrepoConfig
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.tool_state import TerminalSubmission

StepStatus = Literal["ran", "skipped", "failed"]
TERMINAL_PROTOCOL = "submit_review_verdict"


class PipelineExecutionError(RuntimeError):
    """Raised when a step's ``on_error: fail`` policy aborts the run."""


@dataclass
class StepRecord:
    step_id: str
    status: StepStatus
    skip_reason: str = ""
    dispatched_agents: tuple[str, ...] = ()
    on_error_applied: str = ""


@dataclass
class PipelineRunResult:
    step_records: list[StepRecord] = field(default_factory=list)
    terminal_submission: TerminalSubmission | None = None
    orchestrator_kind: str = "deterministic"
    orchestrator_tokens: int = 0
    terminal_protocol: str = TERMINAL_PROTOCOL
    verdict_recorded_via: Callable[..., Any] | None = None
    structural_approval: bool = False
    policy_verdict: str = "neutral"
    verifier_skipped_by_repo_pipeline: bool = False
    decision_answers: dict[DecisionNodeKind, Any] = field(default_factory=dict)


def _tool_ctx(repo_root: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(repo_root))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
            push="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(repo_root),
        signed_commits=True,
        xrepo=XrepoConfig(mode="explicit", read=[], write=[]),
        static_checks_enabled=True,
    )


def _infer_classifier_signals(
    *,
    classifier_signals: dict[str, Any] | None,
    diff_path: Path | None,
) -> dict[str, Any]:
    if classifier_signals is not None:
        return dict(classifier_signals)
    if diff_path is None or not diff_path.is_file():
        return {}
    text = diff_path.read_text(encoding="utf-8")
    paths: list[str] = []
    for line in text.splitlines():
        if line.startswith(("+++ b/", "--- a/")):
            paths.append(line[6:].strip())
    languages: list[str] = []
    for path in paths:
        if path.endswith(".py"):
            languages.append("python")
        elif path.endswith(".md"):
            languages.append("markdown")
    return {"changed_paths": paths, "languages": languages, "risk_band": "low"}


class PipelineExecutor:
    """Walk a declarative pipeline, dispatching registry agents without an LLM loop."""

    def __init__(
        self,
        *,
        registry: Registry,
        settings: RepoSettings,
        decision_client: StructuredDecisionClient | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._decision_client = decision_client

    def run(
        self,
        pipeline: PipelineDefinition,
        *,
        repo_root: Path,
        classifier_signals: dict[str, Any] | None = None,
        inject_failures: set[str] | None = None,
        diff_path: Path | None = None,
        decision_overrides: dict[DecisionNodeKind, StructuredDecisionClient] | None = None,
    ) -> PipelineRunResult:
        kind = self._settings.orchestrator
        ctx = _tool_ctx(repo_root)
        signals = _infer_classifier_signals(
            classifier_signals=classifier_signals,
            diff_path=diff_path,
        )
        diff_text = (
            diff_path.read_text(encoding="utf-8") if diff_path and diff_path.is_file() else ""
        )
        failures = inject_failures or set()
        records: list[StepRecord] = []
        decision_by_id: dict[str, Any] = {}
        decision_by_kind: dict[DecisionNodeKind, Any] = {}
        overrides = decision_overrides or {}
        verifier_ran = False
        verifier_in_repo_pipeline = any(
            step.kind is PipelineStepKind.agent and step.agent == AgentRole.verifier.value
            for step in pipeline.steps
        )
        tokens = 1 if kind == "llm" else 0

        for step in pipeline.steps:
            if step.when is not None and not evaluate_predicate(
                step.when,
                classifier_signals=signals,
                decision_answers=decision_by_id,
            ):
                records.append(
                    StepRecord(
                        step_id=step.id,
                        status="skipped",
                        skip_reason=f"predicate false: {step.when}",
                    )
                )
                continue

            if step.id in failures:
                on_error = step.on_error
                records.append(
                    StepRecord(
                        step_id=step.id,
                        status="failed",
                        on_error_applied=on_error,
                    )
                )
                if on_error == "fail":
                    msg = f"on_error fail policy triggered for step {step.id!r}"
                    raise PipelineExecutionError(msg)
                continue

            if step.kind is PipelineStepKind.decision and step.decision:
                node_kind = DecisionNodeKind(step.decision)
                client = overrides.get(node_kind, self._decision_client)
                if client is None:
                    msg = f"decision step {step.id!r} requires a structured decision client"
                    raise PipelineExecutionError(msg)
                answer = run_decision_node(
                    node_kind,
                    client=client,
                    diff_text=diff_text,
                    registry=self._registry,
                    classifier_signals=signals,
                )
                decision_by_id[step.decision] = answer
                decision_by_kind[node_kind] = answer
                if kind in {"hybrid", "llm"}:
                    tokens += 1
                records.append(StepRecord(step_id=step.id, status="ran"))
                continue

            if step.kind is PipelineStepKind.terminal:
                submission = record_validated_terminal_submission(
                    ctx,
                    {"verdict": "approve", "summary": "pipeline terminal node"},
                )
                records.append(StepRecord(step_id=step.id, status="ran"))
                policy = decide_approval([], run_succeeded=True, tier="trusted")
                return PipelineRunResult(
                    step_records=records,
                    terminal_submission=submission,
                    orchestrator_kind=kind,
                    orchestrator_tokens=tokens,
                    terminal_protocol=TERMINAL_PROTOCOL,
                    verdict_recorded_via=record_validated_terminal_submission,
                    structural_approval=False,
                    policy_verdict=str(policy),
                    verifier_skipped_by_repo_pipeline=(
                        pipeline.source == "repo" and verifier_in_repo_pipeline and not verifier_ran
                    ),
                    decision_answers=decision_by_kind,
                )

            if step.kind is PipelineStepKind.fan_out:
                dispatched = tuple(step.agents)
                for agent_ref in step.agents:
                    binding = resolve_agent_ref(self._registry, agent_ref)
                    if binding.role is AgentRole.verifier:
                        verifier_ran = True
                records.append(
                    StepRecord(
                        step_id=step.id,
                        status="ran",
                        dispatched_agents=dispatched,
                    )
                )
                continue

            if step.kind is PipelineStepKind.agent and step.agent:
                binding = resolve_agent_ref(self._registry, step.agent)
                if binding.role is AgentRole.verifier:
                    verifier_ran = True
                records.append(
                    StepRecord(
                        step_id=step.id,
                        status="ran",
                        dispatched_agents=(step.agent,),
                    )
                )

        policy = decide_approval([], run_succeeded=True, tier="trusted")
        return PipelineRunResult(
            step_records=records,
            orchestrator_kind=kind,
            orchestrator_tokens=tokens,
            structural_approval=False,
            policy_verdict=str(policy),
            verifier_skipped_by_repo_pipeline=(
                pipeline.source == "repo" and verifier_in_repo_pipeline and not verifier_ran
            ),
            decision_answers=decision_by_kind,
        )


__all__ = [
    "TERMINAL_PROTOCOL",
    "PipelineExecutionError",
    "PipelineExecutor",
    "PipelineRunResult",
    "StepRecord",
]
