"""Advisory review budget target warnings from rolling run history (#1494)."""

from __future__ import annotations

import asyncio
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import httpx
from loguru import logger

from mergecraft.review.budget_history import RunUsageSample, load_review_history, make_usage_sample

if TYPE_CHECKING:
    from mergecraft.action.review_state import RunContext
    from mergecraft.config.settings import ReviewBudgetSettings
    from mergecraft.mcp.context import ToolContext
    from mergecraft.scm.protocol import ScmProvider

MetricName = Literal["tokens", "cost_usd", "wall_seconds"]

_BUDGET_LABEL = "mergecraft-budget-trend"
_ISSUE_TITLE_PREFIX = "mergeCraft review budget trend"
_HISTORY_TIMEOUT_S = 5
_ADVISORY_TIMEOUT_S = 12
_ISSUES_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class _BudgetMeasurement:
    metric: MetricName
    p50: float
    target: float
    detail: str

    @property
    def over_target(self) -> bool:
        return self.p50 > self.target


def percentile(values: list[float], p: float) -> float | None:
    """Return the linearly interpolated quantile of the observed values."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p
    low = math.floor(rank)
    high = math.ceil(rank)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _targets(settings: ReviewBudgetSettings) -> tuple[tuple[MetricName, float | None], ...]:
    target = settings.target
    return (
        ("tokens", target.tokens_p50),
        ("cost_usd", target.cost_usd_p50),
        ("wall_seconds", target.wall_seconds_p50),
    )


def _render_value(metric: MetricName, value: float) -> str:
    if metric == "cost_usd":
        return f"${value:.4f}"
    if metric == "wall_seconds":
        return f"{value:g}s"
    return f"{value:,.0f}"


def _measure(
    settings: ReviewBudgetSettings, samples: list[RunUsageSample]
) -> list[_BudgetMeasurement]:
    measurements = []
    for metric, target in _targets(settings):
        if target is None:
            continue
        observations: list[float] = []
        contributors: defaultdict[str, float] = defaultdict(float)
        for sample in samples:
            value: float | None = getattr(sample, metric)
            if value is None:
                continue
            observations.append(value)
            if metric == "wall_seconds":
                contributors["setup"] += sample.setup_seconds or 0
                contributors["agent"] += sample.agent_seconds or 0
            elif sample.model:
                contributors[sample.model] += value
        p50, p90 = percentile(observations, 0.50), percentile(observations, 0.90)
        if p50 is None or p90 is None:
            continue
        contributor_text = ""
        if contributors:
            label = (
                "Largest phase by time"
                if metric == "wall_seconds"
                else "Largest review totals by recorded model"
            )
            contributor_text = f". {label} `{max(contributors, key=contributors.__getitem__)}`"
        detail = (
            f"`{metric}` p50 {_render_value(metric, p50)}, p90 {_render_value(metric, p90)}, "
            f"target {_render_value(metric, target)}. "
            f"{len(observations)} measurements across {len(samples)} of "
            f"{settings.window_size} requested reviews{contributor_text}."
        )
        measurements.append(_BudgetMeasurement(metric, p50, target, detail))
    return measurements


async def _ensure_labels(scm: ScmProvider, owner: str, repo: str, labels: list[str]) -> None:
    for label in labels:
        try:
            await scm.create_label(owner, repo, name=label)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 422 or not any(
                error.get("code") == "already_exists"
                for error in exc.response.json().get("errors", [])
            ):
                raise


async def _tracking_issues(
    ctx: ToolContext, metric: MetricName, publishers: frozenset[str]
) -> list[dict[str, Any]]:
    """Find the attributable issues before deciding whether to create or update."""
    scm, repo = ctx.scm, ctx.repo
    found = await scm.list_issues(
        repo.owner,
        repo.name,
        params={
            "labels": f"{_BUDGET_LABEL}-{metric}",
            "state": "all",
            "per_page": _ISSUES_PAGE_SIZE,
        },
    )
    if len(found) >= _ISSUES_PAGE_SIZE:
        raise ValueError("budget issue lookup reached its page limit")
    return [
        issue
        for issue in found
        if isinstance(issue, dict)
        and issue.get("title") == f"{_ISSUE_TITLE_PREFIX}: {metric}"
        and str(issue.get("body") or "").startswith(
            f"<!-- mergecraft-budget-trend:{metric} -->\n\n"
        )
        and isinstance(issue.get("user"), dict)
        and str(issue["user"].get("login") or "").casefold() in publishers
        and "pull_request" not in issue
        and type(issue.get("number")) is int
        and issue["number"] > 0
    ]


async def _sync_tracking_issue(
    ctx: ToolContext, metric: _BudgetMeasurement, publishers: frozenset[str], *, history_note: str
) -> None:
    """Update the existing attributable issue, reopening it after a fresh breach."""
    scm, repo = ctx.scm, ctx.repo
    title = f"{_ISSUE_TITLE_PREFIX}: {metric.metric}"
    marker = f"<!-- mergecraft-budget-trend:{metric.metric} -->\n\n"
    labels = [_BUDGET_LABEL, f"{_BUDGET_LABEL}-{metric.metric}"]
    status = "above target" if metric.over_target else "back within target"
    body = f"{marker}Review budget is {status}. {metric.detail}{history_note}"
    issues = await _tracking_issues(ctx, metric.metric, publishers)
    if not issues and metric.over_target:
        await _ensure_labels(scm, repo.owner, repo.name, labels)
        await scm.create_issue(repo.owner, repo.name, title=title, body=body, labels=labels)
        # GitHub has no atomic create-if-missing for issues. Re-read after
        # creating so concurrent launches settle on the same lowest issue number.
        issues = await _tracking_issues(ctx, metric.metric, publishers)
    if not issues:
        return

    issues.sort(key=lambda item: item["number"])
    primary, *duplicates = issues
    state = "open" if metric.over_target else "closed"
    if primary.get("state") != state or (metric.over_target and primary.get("body") != body):
        await scm.update_issue(repo.owner, repo.name, primary["number"], body=body, state=state)
    for issue in duplicates:
        if issue.get("state") == "open":
            await scm.update_issue(repo.owner, repo.name, issue["number"], state="closed")


def _current_usage(ctx: ToolContext) -> RunUsageSample | None:
    from mergecraft.utils.review_cost import recorded_run_cost

    state = ctx.tool_state
    packet = state.prepared_run_packet
    if packet is None or (packet.triage is not None and packet.triage.tier in {"skip", "lite"}):
        return None
    usage = state.usage_entries
    tokens = sum(row.input_tokens + row.output_tokens for row in usage) if usage else None
    if ctx.budget_tracker is not None and ctx.budget_tracker.tokens_used > 0:
        tokens = max(tokens or 0, ctx.budget_tracker.tokens_used)
    cost = recorded_run_cost(usage, budget_tracker=ctx.budget_tracker)
    phases = state.phase_elapsed_s
    return make_usage_sample(
        tokens=tokens,
        cost_usd=cost.amount_usd if cost.availability == "available" else None,
        setup=phases.get("setup"),
        agent=phases.get("agent"),
        model=ctx.resolved_model or state.model,
    )


async def _budget_settings(run: RunContext, ctx: ToolContext) -> ReviewBudgetSettings | None:
    from mergecraft.review_policy.ignore_paths import _base_review_settings, _event_base_sha

    if run.settings_snapshot_operator_owned:
        return run.settings.review.budget if run.settings is not None else None
    sha = _event_base_sha(run.gh_event)
    if not sha:
        return None
    repo = ctx.repo
    review, _, _ = await _base_review_settings(ctx.scm, repo.owner, repo.name, sha)
    return review.budget if review is not None else None


async def _emit_advisory(run: RunContext) -> None:
    from mergecraft.config.trust_policy import is_fork_pull_request
    from mergecraft.review.authorship import resolve_publisher_logins
    from mergecraft.run_outcome import is_review_mode
    from mergecraft.utils import gha_log
    from mergecraft.utils.step_summary import append_step_summary

    ctx = run.tool_context
    event = run.gh_event or {}
    if (
        ctx is None
        or not isinstance(event.get("pull_request"), dict)
        or not is_review_mode(ctx.tool_state.selected_mode)
    ):
        return
    settings = await _budget_settings(run, ctx)
    if settings is None or not any(target is not None for _, target in _targets(settings)):
        return
    current = _current_usage(ctx)
    if current is None:
        return

    history = None
    publishers: frozenset[str] = frozenset()
    try:
        async with asyncio.timeout(_HISTORY_TIMEOUT_S):
            publishers = frozenset(
                login.casefold() for login in await resolve_publisher_logins(ctx)
            )
            if publishers:
                run_attempt_env = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
                identity = (
                    (ctx.run_id, int(run_attempt_env))
                    if ctx.run_id and run_attempt_env.isdecimal()
                    else None
                )
                history = await load_review_history(
                    ctx,
                    publishers=publishers,
                    window_size=settings.window_size - 1,
                    current_attempt=identity,
                )
    except Exception as exc:
        logger.info("Review budget history could not be read ({})", type(exc).__name__)

    samples = [current, *(history.samples if history is not None else [])]
    measurements = _measure(settings, samples)
    history_note = ""
    if history is None:
        history_note = " Repository history unavailable. Only this review was measured."
    elif history.limited:
        history_note = " The repository history search reached its read limit."
    warnings = [measurement.detail for measurement in measurements if measurement.over_target]
    if warnings:
        summary = "\n".join(f"- **Warning:** {warning}{history_note}" for warning in warnings)
        try:
            append_step_summary(f"### Review budget\n\n{summary}")
        except OSError as exc:
            logger.info("Review budget summary could not be written ({})", type(exc).__name__)
        for warning in warnings:
            gha_log.warning(f"mergeCraft review budget: {warning}{history_note}")

    if history is None or run.authority_trust != "trusted" or is_fork_pull_request(event):
        return
    for measurement in measurements:
        if not measurement.over_target and history.limited and len(samples) < settings.window_size:
            continue
        try:
            await _sync_tracking_issue(ctx, measurement, publishers, history_note=history_note)
        except Exception as exc:
            gha_log.warning(
                f"mergeCraft review budget: tracking issue for {measurement.metric} "
                f"could not be synchronized ({type(exc).__name__})"
            )


async def emit_budget_trend_advisory(run: RunContext) -> None:
    """Finish the optional budget report without changing the review outcome."""
    try:
        async with asyncio.timeout(_ADVISORY_TIMEOUT_S):
            await _emit_advisory(run)
    except Exception as exc:
        logger.warning("Review budget advisory unavailable ({})", type(exc).__name__)


__all__ = ["emit_budget_trend_advisory", "percentile"]
