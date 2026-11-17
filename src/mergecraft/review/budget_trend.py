"""Advisory review budget target warnings from rolling run history (#1494)."""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from mergecraft.config.settings import ReviewBudgetSettings
    from mergecraft.scm.protocol import ScmProvider

MetricName = Literal["tokens", "cost_usd", "wall_seconds"]
_BUDGET_LABEL = "mergecraft-budget-trend"
_ISSUE_TITLE_PREFIX = "mergeCraft review budget trend"


@dataclass(frozen=True, slots=True)
class RunUsageSample:
    tokens: int | None
    cost_usd: float | None
    wall_seconds: float | None


def percentile(values: list[float], p: float) -> float | None:
    """Pure p-quantile; ``None`` when ``values`` is empty."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[int(rank)]
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def window_stats(samples: list[RunUsageSample]) -> dict[str, float | None]:
    tokens = [float(s.tokens) for s in samples if s.tokens is not None]
    costs = [s.cost_usd for s in samples if s.cost_usd is not None]
    wall = [s.wall_seconds for s in samples if s.wall_seconds is not None]
    return {
        "tokens_p50": percentile(tokens, 0.5),
        "tokens_p90": percentile(tokens, 0.9),
        "cost_usd_p50": percentile(costs, 0.5),
        "cost_usd_p90": percentile(costs, 0.9),
        "wall_seconds_p50": percentile(wall, 0.5),
        "wall_seconds_p90": percentile(wall, 0.9),
    }


def target_warnings(
    settings: ReviewBudgetSettings,
    stats: dict[str, float | None],
    *,
    window_n: int,
) -> list[tuple[MetricName, str]]:
    """Return advisory lines when rolling p50 exceeds configured targets."""
    target = settings.target
    if not any(
        (
            target.tokens_p50,
            target.cost_usd_p50,
            target.wall_seconds_p50,
        )
    ):
        return []
    warnings: list[tuple[MetricName, str]] = []
    if target.tokens_p50 is not None:
        observed = stats.get("tokens_p50")
        if observed is not None and observed > target.tokens_p50:
            warnings.append(
                (
                    "tokens",
                    (
                        f"Review token p50 ({observed:.0f}) exceeds target "
                        f"{target.tokens_p50} (p90 {stats.get('tokens_p90') or 0:.0f} "
                        f"over {window_n} runs)"
                    ),
                )
            )
    if target.cost_usd_p50 is not None:
        observed = stats.get("cost_usd_p50")
        if observed is not None and observed > target.cost_usd_p50:
            warnings.append(
                (
                    "cost_usd",
                    (
                        f"Review cost p50 (${observed:.4f}) exceeds target "
                        f"${target.cost_usd_p50:.4f}"
                    ),
                )
            )
    if target.wall_seconds_p50 is not None:
        observed = stats.get("wall_seconds_p50")
        if observed is not None and observed > target.wall_seconds_p50:
            warnings.append(
                (
                    "wall_seconds",
                    (
                        f"Review wall-time p50 ({observed:.0f}s) exceeds target "
                        f"{target.wall_seconds_p50:.0f}s"
                    ),
                )
            )
    return warnings


def issue_title(metric: MetricName) -> str:
    return f"{_ISSUE_TITLE_PREFIX}: {metric}"


def issue_body_fingerprint(metric: MetricName, message: str) -> str:
    return f"<!-- mergecraft-budget-trend:{metric} -->\n\n{message}"


async def ensure_tracking_issue(
    scm: ScmProvider,
    owner: str,
    repo: str,
    *,
    metric: MetricName,
    body: str,
) -> None:
    """Create or update one open tracking issue per metric."""
    title = issue_title(metric)
    fingerprint = issue_body_fingerprint(metric, body)
    try:
        open_issues = await scm.list_issues(
            owner, repo, state="open", labels=f"{_BUDGET_LABEL}-{metric}"
        )
    except Exception:
        open_issues = []
    for issue in open_issues:
        if str(issue.get("title") or "") == title:
            number = issue.get("number")
            if isinstance(number, int):
                await scm.update_issue(owner, repo, number, body=fingerprint)
                return
    await scm.create_issue(
        owner,
        repo,
        title=title,
        body=fingerprint,
        labels=[_BUDGET_LABEL, f"{_BUDGET_LABEL}-{metric}"],
    )


def samples_from_packets(packets: list[dict[str, Any]]) -> list[RunUsageSample]:
    """Extract usage rows from evidence packet JSON dicts."""
    out: list[RunUsageSample] = []
    for packet in packets:
        metrics = packet.get("run_metrics") if isinstance(packet, dict) else None
        phase = (metrics or {}).get("phase_elapsed_s") if isinstance(metrics, dict) else {}
        wall = None
        if isinstance(phase, dict):
            try:
                wall = float(sum(float(v) for v in phase.values()))
            except (TypeError, ValueError):
                wall = None
        cost = (metrics or {}).get("recorded_cost_usd") if isinstance(metrics, dict) else None
        tokens = None
        usage = packet.get("usage_entries") if isinstance(packet, dict) else None
        if isinstance(usage, list):
            total = 0
            for row in usage:
                if isinstance(row, dict):
                    total += int(row.get("input_tokens") or 0) + int(row.get("output_tokens") or 0)
            tokens = total if usage else None
        out.append(
            RunUsageSample(
                tokens=tokens,
                cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
                wall_seconds=wall,
            )
        )
    return out


async def emit_budget_trend_advisory(ctx: Any) -> None:
    """Log warnings and file tracking issues when rolling p50 exceeds targets."""
    from mergecraft.utils import gha_log

    settings = ctx.settings.review.budget
    target = settings.target
    if not any((target.tokens_p50, target.cost_usd_p50, target.wall_seconds_p50)):
        return
    packet = getattr(ctx.tool_state, "prepared_run_packet", None)
    samples = samples_from_packets([packet.model_dump()] if packet is not None else [])
    window_n = min(settings.window_size, max(len(samples), 1))
    stats = window_stats(samples)
    for metric, message in target_warnings(settings, stats, window_n=window_n):
        gha_log.warning(f"mergeCraft budget trend ({metric}): {message}")
        if ctx.tool_context is not None:
            repo = ctx.tool_context.repo
            with contextlib.suppress(Exception):
                await ensure_tracking_issue(
                    ctx.tool_context.scm,
                    repo.owner,
                    repo.name,
                    metric=metric,
                    body=message,
                )


__all__ = [
    "RunUsageSample",
    "emit_budget_trend_advisory",
    "ensure_tracking_issue",
    "issue_title",
    "percentile",
    "samples_from_packets",
    "target_warnings",
    "window_stats",
]
