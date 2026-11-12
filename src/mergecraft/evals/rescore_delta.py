"""Base-vs-head structural replay keep/drop delta (#1164, advisory).

Runs the same keyless ``run_structural_replay`` contract at two mergeCraft
commits and reports per-case status flips plus aggregate metric deltas. Live
provider rescoring stays opt-in; CI uses this for reviewer-surface diffs only.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.evals.benchmark import BenchmarkResultSet, run_structural_replay
from mergecraft.evals.gate import DEFAULT_GATE_TOLERANCE, eval_gate
from mergecraft.evals.store import CASE_STATUS_PASSED, CASE_STATUS_REGRESSION

if TYPE_CHECKING:
    from collections.abc import Sequence

KeepDropKind = Literal["gained_pass", "lost_pass", "unchanged", "blocked_flip"]


class CaseKeepDropRow(BaseModel):
    """One case's base vs head replay status."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    base_status: str
    head_status: str
    kind: KeepDropKind


class RescoreDeltaReport(BaseModel):
    """Advisory base-vs-head structural replay comparison."""

    model_config = ConfigDict(extra="forbid")

    recorded_at: datetime
    base_commit: str
    head_commit: str
    rows: list[CaseKeepDropRow] = Field(default_factory=list)
    gate_passed: bool
    regressed_metrics: tuple[str, ...] = ()
    decision_replay_pass_rate_delta: float = 0.0
    unsafe_approval_rate_delta: float = 0.0
    clean_block_rate_delta: float = 0.0
    inconclusive_rate_delta: float = 0.0

    @property
    def gained_pass(self) -> list[CaseKeepDropRow]:
        return [row for row in self.rows if row.kind == "gained_pass"]

    @property
    def lost_pass(self) -> list[CaseKeepDropRow]:
        return [row for row in self.rows if row.kind == "lost_pass"]


def _row_kind(base_status: str, head_status: str) -> KeepDropKind:
    if base_status == head_status:
        return "unchanged"
    if base_status == CASE_STATUS_REGRESSION and head_status == CASE_STATUS_PASSED:
        return "gained_pass"
    if base_status == CASE_STATUS_PASSED and head_status == CASE_STATUS_REGRESSION:
        return "lost_pass"
    return "blocked_flip"


def compare_result_sets(
    baseline: BenchmarkResultSet,
    candidate: BenchmarkResultSet,
    *,
    tolerance: float = DEFAULT_GATE_TOLERANCE,
) -> RescoreDeltaReport:
    """Compare two replay result sets and classify per-case keep/drop flips."""
    gate = eval_gate(baseline=baseline, candidate=candidate, tolerance=tolerance)
    base_by_id = {row.case_id: row.status for row in baseline.case_results}
    head_by_id = {row.case_id: row.status for row in candidate.case_results}
    rows: list[CaseKeepDropRow] = []
    for case_id in sorted(set(base_by_id) | set(head_by_id)):
        base_status = base_by_id.get(case_id, "blocked")
        head_status = head_by_id.get(case_id, "blocked")
        rows.append(
            CaseKeepDropRow(
                case_id=case_id,
                base_status=base_status,
                head_status=head_status,
                kind=_row_kind(base_status, head_status),
            )
        )
    b_metrics = baseline.metrics
    c_metrics = candidate.metrics
    return RescoreDeltaReport(
        recorded_at=datetime.now(UTC),
        base_commit=baseline.pins.mergecraft_commit,
        head_commit=candidate.pins.mergecraft_commit,
        rows=rows,
        gate_passed=gate.passed,
        regressed_metrics=gate.regressed_metrics,
        decision_replay_pass_rate_delta=(
            c_metrics.decision_replay_pass_rate - b_metrics.decision_replay_pass_rate
        ),
        unsafe_approval_rate_delta=(
            c_metrics.unsafe_approval_rate - b_metrics.unsafe_approval_rate
        ),
        clean_block_rate_delta=(c_metrics.clean_block_rate - b_metrics.clean_block_rate),
        inconclusive_rate_delta=(c_metrics.inconclusive_rate - b_metrics.inconclusive_rate),
    )


def run_rescore_at_checkout(*, bank_dir: Path | None = None) -> BenchmarkResultSet:
    """Run structural replay against the currently checked-out mergeCraft tree."""
    return run_structural_replay(bank_dir or Path("evals/cases"))


def write_rescore_delta_report(report: RescoreDeltaReport, path: Path) -> None:
    """Persist a delta report under ``evals/results/`` (creates parents)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def format_rescore_summary(report: RescoreDeltaReport) -> str:
    """Human-readable summary for CI step summaries (advisory)."""
    lines = [
        "Structural eval rescore delta (base vs head, keyless replay — not live detection).",
        f"Base commit: `{report.base_commit}` → head `{report.head_commit}`.",
        f"Pass-rate Δ: {report.decision_replay_pass_rate_delta:+.2%}; "
        f"unsafe-approval Δ: {report.unsafe_approval_rate_delta:+.2%}.",
        f"Gained pass: {len(report.gained_pass)}; lost pass: {len(report.lost_pass)}.",
    ]
    if report.regressed_metrics:
        lines.append(f"Gate regressed metrics: {', '.join(report.regressed_metrics)}")
    return "\n".join(lines)


#: The decision surface: the code that structural replay actually executes
#: (``decide_approval`` and the finding/severity model it reads). Replay is a
#: function of recorded findings and these paths only, so a change here is the
#: one that can move the delta (W3.3-4). The prompt/mode paths below can only
#: move the ``mode_prompt_versions`` pins.
DECISION_SURFACE_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "src/mergecraft/agents/gates.py",
    "src/mergecraft/findings/",
)

REVIEWER_SURFACE_PATH_PREFIXES: Final[tuple[str, ...]] = (
    *DECISION_SURFACE_PATH_PREFIXES,
    "src/mergecraft/modes/",
    "src/mergecraft/agents/reviewer.py",
    "src/mergecraft/agents/registry.py",
    "src/mergecraft/agents/harness_render.py",
    "src/mergecraft/mcp/review.py",
    "src/mergecraft/mcp/server.py",
    "src/mergecraft/mcp/checkout.py",
    "src/mergecraft/mcp/verification.py",
    ".github/skills/",
    "skills/",
)


def touches_reviewer_surface(changed_paths: Sequence[str]) -> bool:
    """True when any changed path affects the decision surface, prompts, modes, tools, or model config."""
    for raw in changed_paths:
        path = raw.strip().replace("\\", "/")
        if not path:
            continue
        for prefix in REVIEWER_SURFACE_PATH_PREFIXES:
            if path.startswith(prefix) or path == prefix.rstrip("/"):
                return True
        if path.endswith("config.yaml") and ".mergecraft" in path:
            return True
    return False


__all__ = [
    "DECISION_SURFACE_PATH_PREFIXES",
    "RescoreDeltaReport",
    "compare_result_sets",
    "format_rescore_summary",
    "run_rescore_at_checkout",
    "touches_reviewer_surface",
    "write_rescore_delta_report",
]
