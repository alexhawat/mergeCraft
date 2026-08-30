"""Per-run budgets, external-operation timeouts, and large-input degradation (CC3).

A single resolved :class:`RunBounds` object is threaded from settings through
the offline review and Action orchestrators. Budget exhaustion maps to
``RunOutcome.inconclusive`` — never a partial approval (D12).
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

from loguru import logger

from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.agents.shared import AgentUsage
    from mergecraft.config.settings import RepoSettings, RoundBudgetsSettings, RunBoundsSettings

BudgetKind = Literal["token", "cost", "tool_call"]

_DEFAULT_TOKEN_BUDGET: Final[int] = 2_000_000
_DEFAULT_COST_BUDGET_USD: Final[float] = 50.0
_DEFAULT_TOOL_CALL_BUDGET: Final[int] = 500
_DEFAULT_RUN_TIMEOUT_S: Final[float] = 3600.0
_DEFAULT_CONTEXT_RETRIEVAL_TIMEOUT_S: Final[float] = 30.0
_DEFAULT_MAX_DIFF_LINES: Final[int] = 50_000
_DEFAULT_EXTERNAL_OPERATION_TIMEOUT_S: Final[float] = 600.0
_DEFAULT_CACHE_MAX_BYTES: Final[int] = 512 * 1024 * 1024

# Registry of every external I/O surface the runtime performs. Tests enumerate
# this table to prove no call site is unbounded (CC3.1e).
EXTERNAL_OPERATION_TIMEOUTS: Final[dict[str, float]] = {
    "git_clone": 600.0,
    "git_fetch": 120.0,
    "git_diff": 120.0,
    "git_setup": 600.0,
    "context_retrieval": _DEFAULT_CONTEXT_RETRIEVAL_TIMEOUT_S,
    "http_request": 120.0,
    "subprocess_agent": 3600.0,
    "mcp_shell": 300.0,
    "analyzer_run": 600.0,
    "source_acquire": 600.0,
}


@dataclass(frozen=True, slots=True)
class RunBounds:
    """Resolved per-run ceilings threaded from settings and env overrides."""

    token_budget: int
    cost_budget_usd: float
    tool_call_budget: int
    run_timeout_s: float
    context_retrieval_timeout_s: float
    max_diff_lines: int
    external_operation_timeout_s: float
    token_budget_tolerance: float = 0.0
    cache_max_bytes: int = _DEFAULT_CACHE_MAX_BYTES

    @property
    def token_ceiling(self) -> int:
        """Hard token ceiling: target plus configured tolerance band (D9)."""
        if self.token_budget_tolerance <= 0.0:
            return self.token_budget
        return int(self.token_budget * (1.0 + self.token_budget_tolerance))


@dataclass(frozen=True, slots=True)
class ScopeReduction:
    """Recorded scope omission when a diff exceeds ``max_diff_lines`` (D12)."""

    original_lines: int
    kept_lines: int
    omitted_paths: list[str]
    reason: str


class BudgetExhausted(RuntimeError):
    """Raised when a per-run budget ceiling is reached."""

    def __init__(self, kind: BudgetKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(slots=True)
class BudgetTracker:
    """Mutable per-run budget consumption against resolved :class:`RunBounds`.

    ``last_exhausted`` is set to the ``BudgetExhausted`` raised on the most
    recent overrun (whether tripped from agent-usage accounting via
    ``record_agent_usage`` or from the MCP ``tools/call`` handler via
    ``record_tool_call``). ``mergecraft.main._finalize`` drains this so D12
    holds uniformly regardless of which call site tripped the budget — see
    PR #242 review finding ``aeb5d964c1d35e5a41784ded``.
    """

    bounds: RunBounds
    tokens_used: int = 0
    cost_used: float = 0.0
    tool_calls: int = 0
    last_exhausted: BudgetExhausted | None = None
    over_target: bool = False
    phase_totals: Counter[str] = field(default_factory=Counter)
    _over_target_warned: bool = field(default=False, repr=False)

    def record_tokens(self, count: int, *, phase: str | None = None) -> None:
        if count <= 0:
            return
        phase_key = phase or "unattributed"
        target = self.bounds.token_budget
        ceiling = self.bounds.token_ceiling
        tolerance = self.bounds.token_budget_tolerance

        if tolerance <= 0.0:
            self.tokens_used += count
            self.phase_totals[phase_key] += count
            if self.tokens_used > target:
                msg = f"token budget exhausted ({self.tokens_used} > {target})"
                self._raise(BudgetExhausted("token", msg))
            return

        remaining = ceiling - self.tokens_used
        if count > ceiling:
            msg = (
                f"token budget exhausted by single increment ({count} > ceiling {ceiling}; "
                f"target {target}, tolerance {tolerance})"
            )
            self._raise(BudgetExhausted("token", msg))

        prior_used = self.tokens_used
        charge = count
        if charge > remaining:
            if prior_used < target:
                charge = remaining
            else:
                msg = (
                    "token budget exhausted by single increment "
                    f"({count} > remaining ceiling {remaining}; used {self.tokens_used}, "
                    f"target {target}, ceiling {ceiling}, tolerance {tolerance})"
                )
                self._raise(BudgetExhausted("token", msg))

        self.tokens_used += charge
        self.phase_totals[phase_key] += charge

        if prior_used <= target < self.tokens_used:
            self.over_target = True
            if not self._over_target_warned:
                self._over_target_warned = True
                logger.warning(
                    "token budget over target ({} > target {}); continuing to ceiling {}",
                    self.tokens_used,
                    target,
                    ceiling,
                )
        elif self.tokens_used > target:
            self.over_target = True

        if self.tokens_used > ceiling:
            msg = (
                f"token budget exhausted ({self.tokens_used} > ceiling {ceiling}; "
                f"target {target}, tolerance {tolerance})"
            )
            self._raise(BudgetExhausted("token", msg))

    def record_cost(self, amount: float) -> None:
        if amount <= 0:
            return
        self.cost_used += amount
        if self.cost_used > self.bounds.cost_budget_usd:
            msg = (
                f"cost budget exhausted ({self.cost_used:.4f} > {self.bounds.cost_budget_usd:.4f})"
            )
            self._raise(BudgetExhausted("cost", msg))

    def record_tool_call(self) -> None:
        self.tool_calls += 1
        if self.tool_calls > self.bounds.tool_call_budget:
            msg = f"tool-call budget exhausted ({self.tool_calls} > {self.bounds.tool_call_budget})"
            self._raise(BudgetExhausted("tool_call", msg))

    def _raise(self, exc: BudgetExhausted) -> None:
        """Stash the exhaustion on the tracker, then raise.

        Catching the exception at a higher level (e.g. the MCP JSON-RPC
        handler) is allowed — the orchestrator's ``_finalize`` still reads
        ``last_exhausted`` and applies ``budget_exhaustion_outcome`` (D12).
        """
        self.last_exhausted = exc
        raise exc


def record_agent_usage(
    tracker: BudgetTracker | None,
    usage: AgentUsage | None,
    *,
    phase: str | None = None,
) -> None:
    """Charge resolved agent usage against the per-run budget tracker."""
    if tracker is None or usage is None:
        return
    # ``AgentUsage.input_tokens`` already folds disjoint Anthropic cache reads
    # and cache writes per D16 / #273. ``cache_read_tokens`` /
    # ``cache_write_tokens`` are observability fields only — adding them again
    # here double-counts OpenAI-style cached input against the run budget.
    token_total = usage.input_tokens + usage.output_tokens
    tracker.record_tokens(token_total, phase=phase)
    if usage.cost_usd is not None:
        tracker.record_cost(usage.cost_usd)


def _env_float(env: Mapping[str, str], key: str) -> float | None:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return None
    return float(raw)


def _env_int(env: Mapping[str, str], key: str) -> int | None:
    raw = env.get(key)
    if raw is None or not str(raw).strip():
        return None
    return int(raw)


def round_budget_multiplier(
    round_budgets: RoundBudgetsSettings | None,
    *,
    round_index: int,
) -> float:
    """Return the budget multiplier for a 1-based review round (RC12)."""
    if round_budgets is None:
        return 1.0
    multipliers = round_budgets.multipliers
    if not multipliers:
        return 1.0
    index = max(1, round_index) - 1
    if index >= len(multipliers):
        return multipliers[-1]
    return multipliers[index]


def _scale_budget_int(value: int, multiplier: float) -> int:
    return int(value * multiplier)


def resolve_run_bounds(
    *,
    settings: RepoSettings | None = None,
    env: Mapping[str, str] | None = None,
    round_index: int = 1,
) -> RunBounds:
    """Resolve :class:`RunBounds` from repo settings with env overrides."""
    from mergecraft.config.settings import default_settings

    resolved_settings = settings if settings is not None else default_settings()
    cfg: RunBoundsSettings = resolved_settings.run_bounds
    environ = dict(env if env is not None else os.environ)

    token_budget = _env_int(environ, "MERGECRAFT_TOKEN_BUDGET") or cfg.token_budget
    cost_budget = _env_float(environ, "MERGECRAFT_COST_BUDGET_USD")
    if cost_budget is None:
        cost_budget = float(cfg.cost_budget_usd)
    tool_call_budget = _env_int(environ, "MERGECRAFT_TOOL_CALL_BUDGET") or cfg.tool_call_budget
    max_diff_lines = _env_int(environ, "MERGECRAFT_MAX_DIFF_LINES") or cfg.max_diff_lines
    context_timeout = _env_float(environ, "MERGECRAFT_CONTEXT_RETRIEVAL_TIMEOUT_S")
    if context_timeout is None:
        context_timeout = float(cfg.context_retrieval_timeout_s)
    run_timeout = _env_float(environ, "MERGECRAFT_RUN_TIMEOUT_S")
    if run_timeout is None:
        run_timeout = _DEFAULT_RUN_TIMEOUT_S
    external_timeout = _env_float(environ, "MERGECRAFT_EXTERNAL_OPERATION_TIMEOUT_S")
    if external_timeout is None:
        external_timeout = _DEFAULT_EXTERNAL_OPERATION_TIMEOUT_S
    cache_max = _env_int(environ, "MERGECRAFT_CACHE_MAX_BYTES") or cfg.cache_max_bytes

    multiplier = round_budget_multiplier(
        resolved_settings.review.round_budgets,
        round_index=round_index,
    )

    # ``cost_budget_usd`` scales with the round multiplier when ``roundBudgets`` is
    # enabled — operators who need a flat cost cap should set ``roundBudgets: false``.
    return RunBounds(
        token_budget=_scale_budget_int(token_budget, multiplier),
        cost_budget_usd=cost_budget * multiplier,
        tool_call_budget=_scale_budget_int(tool_call_budget, multiplier),
        run_timeout_s=run_timeout,
        context_retrieval_timeout_s=context_timeout,
        max_diff_lines=max_diff_lines,
        external_operation_timeout_s=external_timeout,
        token_budget_tolerance=cfg.token_budget_tolerance,
        cache_max_bytes=cache_max,
    )


def format_token_budget_summary(tracker: BudgetTracker) -> str:
    """Render token usage with target, ceiling, phase attribution, and over-target flag."""
    bounds = tracker.bounds
    parts = [
        (
            f"{tracker.tokens_used:,} used "
            f"(target {bounds.token_budget:,}, ceiling {bounds.token_ceiling:,})"
        ),
    ]
    if tracker.over_target:
        parts.append("over target")
    phase_bits = [
        f"{phase} {total:,}" for phase, total in sorted(tracker.phase_totals.items()) if total > 0
    ]
    if phase_bits:
        parts.append(f"by phase: {', '.join(phase_bits)}")
    return "; ".join(parts)


def enumerate_unbounded_external_operations() -> list[str]:
    """Return registry keys without a positive finite timeout (for tests)."""
    unbounded: list[str] = []
    for name, seconds in EXTERNAL_OPERATION_TIMEOUTS.items():
        if not isinstance(seconds, (int, float)) or seconds <= 0:
            unbounded.append(name)
    return unbounded


def timeout_for_external_operation(
    operation: str,
    *,
    bounds: RunBounds | None = None,
) -> float:
    """Return the timeout in seconds for a named external operation."""
    if operation == "context_retrieval" and bounds is not None:
        return bounds.context_retrieval_timeout_s
    timeout = EXTERNAL_OPERATION_TIMEOUTS.get(operation)
    if timeout is None:
        msg = f"unknown external operation {operation!r}"
        raise KeyError(msg)
    if bounds is not None:
        return min(timeout, bounds.external_operation_timeout_s)
    return timeout


def budget_exhaustion_outcome(exc: BudgetExhausted) -> RunOutcome:
    """Map budget exhaustion to ``inconclusive`` — never ``passed`` (D12)."""
    logger.warning("run budget exhausted ({}): {}", exc.kind, exc)
    return RunOutcome.inconclusive


def outcome_with_scope_reduction(
    outcome: RunOutcome,
    reduction: ScopeReduction | None,
) -> RunOutcome:
    """Downgrade a would-be pass when scope was reduced (D12)."""
    if reduction is None:
        return outcome
    if outcome is RunOutcome.passed:
        logger.warning(
            "scope reduced ({} lines → {}); outcome downgraded to inconclusive",
            reduction.original_lines,
            reduction.kept_lines,
        )
        return RunOutcome.inconclusive
    return outcome


def _diff_file_blocks(diff_text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    current_path: str | None = None
    current_lines: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_path is not None:
                blocks.append((current_path, "".join(current_lines)))
            parts = line.split()
            current_path = parts[3].removeprefix("b/") if len(parts) >= 4 else "unknown"
            current_lines = [line]
            continue
        if current_path is not None:
            current_lines.append(line)
    if current_path is not None:
        blocks.append((current_path, "".join(current_lines)))
    return blocks


def apply_diff_line_budget(
    diff_text: str,
    *,
    max_lines: int,
) -> tuple[str, ScopeReduction | None]:
    """Truncate an oversized diff by file, recording omitted scope (D12)."""
    if not diff_text.strip():
        return diff_text, None
    blocks = _diff_file_blocks(diff_text)
    if not blocks:
        return diff_text, None
    original_lines = diff_text.count("\n") + (0 if diff_text.endswith("\n") else 1)
    if original_lines <= max_lines:
        return diff_text, None

    kept_blocks: list[str] = []
    omitted_paths: list[str] = []
    kept_lines = 0
    for path, block in blocks:
        block_lines = block.count("\n") + (0 if block.endswith("\n") else 1)
        if kept_lines + block_lines > max_lines:
            omitted_paths.append(path)
            continue
        kept_blocks.append(block)
        kept_lines += block_lines

    reduced = "".join(kept_blocks)
    if reduced and not reduced.endswith("\n"):
        reduced = f"{reduced}\n"
    reason = (
        f"diff exceeded max_diff_lines ({original_lines} > {max_lines}); "
        f"scope reduced — {len(omitted_paths)} file(s) omitted"
    )
    reduction = ScopeReduction(
        original_lines=original_lines,
        kept_lines=kept_lines,
        omitted_paths=omitted_paths,
        reason=reason,
    )
    logger.warning("{}", reason)
    return reduced, reduction


__all__ = [
    "EXTERNAL_OPERATION_TIMEOUTS",
    "BudgetExhausted",
    "BudgetKind",
    "BudgetTracker",
    "RunBounds",
    "ScopeReduction",
    "apply_diff_line_budget",
    "budget_exhaustion_outcome",
    "enumerate_unbounded_external_operations",
    "format_token_budget_summary",
    "outcome_with_scope_reduction",
    "record_agent_usage",
    "resolve_run_bounds",
    "round_budget_multiplier",
    "timeout_for_external_operation",
]
