"""Resolve ``risk.mode`` and blast-radius overrides from the PR base (#1489)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from loguru import logger

from mergecraft.review_policy.ignore_paths import _base_repo_settings, _event_base_sha

if TYPE_CHECKING:
    from mergecraft.classify.blast_radius import RuleSet
    from mergecraft.config.settings import RepoSettings, RiskSettings
    from mergecraft.scm.protocol import ScmProvider


async def resolve_risk_settings(
    scm: ScmProvider,
    owner: str,
    repo: str,
    *,
    event: dict[str, Any] | None,
    run_start_settings: RepoSettings,
    operator_owned: bool,
) -> tuple[RiskSettings, RuleSet]:
    """Return risk mode and blast-radius rule set from operator-side config only."""
    from mergecraft.config.settings import RiskSettings

    pull = event.get("pull_request") if isinstance(event, dict) else None
    if operator_owned or not isinstance(pull, dict):
        risk = run_start_settings.risk
        raw_rules = run_start_settings.blast_radius_override or {}
        rule_set: RuleSet = cast("RuleSet", dict(raw_rules))  # reason: RuleSet is a TypedDict
        return risk, rule_set
    base_sha = _event_base_sha(event)
    if not base_sha:
        logger.warning("risk: PR base commit unknown — deterministic mode with defaults")
        return RiskSettings(), {}
    try:
        settings, _source, detail = await _base_repo_settings(scm, owner, repo, base_sha)
    except Exception as err:
        logger.warning("risk: base config unreadable ({}) — defaults", type(err).__name__)
        return RiskSettings(), {}
    if settings is None:
        logger.warning("risk: base config dropped — {}", detail)
        return RiskSettings(), {}
    return settings.risk, cast(  # reason: RuleSet is a TypedDict
        "RuleSet", dict(settings.blast_radius_override or {})
    )


__all__ = ["resolve_risk_settings"]
