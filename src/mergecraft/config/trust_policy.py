"""Two-axis trust policy resolution for review runs (plan 13 D13-D16).

**Execution trust** answers whether analyzers and repo-executable config may run
against this checkout. **Authority trust** answers whether the agent's own
terminal output may unlock approval semantics on this run.

The operator knob ``trust.selfReview`` is read only from the base-tree settings
snapshot (lane C ``settings_snapshot`` / MCB-19) — never from a PR head edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — ``config_root.resolve()`` runs at runtime
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.config.settings import TrustTier

if TYPE_CHECKING:
    from mergecraft.config.settings_snapshot import RepoSettingsSnapshot

ExecutionTrust = TrustTier
AuthorityTrust = TrustTier
SelfReviewLevel = Literal["off", "analyzers", "full"]
ResolvedFrom = Literal["base_snapshot", "live_load"]


@dataclass(frozen=True, slots=True)
class TrustPolicy:
    """Effective trust posture for one review run."""

    level: SelfReviewLevel
    execution_trust: ExecutionTrust
    authority_trust: AuthorityTrust
    resolved_from: ResolvedFrom
    config_hash: str


def _is_fork_pull_request(event: dict[str, Any]) -> bool:
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return True
    head = pull_request.get("head")
    if not isinstance(head, dict):
        return True
    repo = head.get("repo")
    if not isinstance(repo, dict):
        return True
    return bool(repo.get("fork"))


def _same_repo_pull_request_target(event_name: str, event: dict[str, Any]) -> bool:
    return event_name == "pull_request_target" and not _is_fork_pull_request(event)


def _read_self_review_level(settings: Any) -> SelfReviewLevel:
    trust = getattr(settings, "trust", None)
    raw = getattr(trust, "self_review", "off")
    if raw in {"off", "analyzers", "full"}:
        return raw  # type: ignore[return-value]  # — value verified against SelfReviewLevel literals above
    return "off"


def resolve_trust_policy(
    *,
    event: dict[str, Any],
    config_root: Path,
    event_name: str,
    settings_snapshot: RepoSettingsSnapshot | None = None,
    pr_head_config_hash: str | None = None,
    shell: str = "restricted",
    offline: bool = False,
) -> TrustPolicy:
    """Resolve execution and authority trust from the base snapshot (D15).

    ``pr_head_config_hash`` is accepted only so callers can prove the PR head
    config was not consulted; it is intentionally ignored.
    """
    _ = pr_head_config_hash

    resolved_from: ResolvedFrom
    config_hash: str
    if settings_snapshot is not None:
        settings = settings_snapshot.settings
        config_hash = settings_snapshot.config_hash
        resolved_from = "base_snapshot"
    else:
        from mergecraft.config.settings_snapshot import config_yaml_hash, load_repo_settings

        repo_root = config_root.resolve()
        settings = load_repo_settings(root=repo_root, load_learnings_files=False)
        config_hash = config_yaml_hash(root=repo_root)
        resolved_from = "live_load"

    level = _read_self_review_level(settings)
    base_tier = derive_trust_tier(event=event, shell=shell, offline=offline)
    execution: ExecutionTrust = base_tier
    authority: AuthorityTrust = base_tier

    if _is_fork_pull_request(event):
        execution = "untrusted"
        authority = "untrusted"
    elif _same_repo_pull_request_target(event_name, event) and level in ("analyzers", "full"):
        execution = "trusted"
        if level == "full":
            authority = "trusted"

    return TrustPolicy(
        level=level,
        execution_trust=execution,
        authority_trust=authority,
        resolved_from=resolved_from,
        config_hash=config_hash,
    )


def log_trust_policy_at_run_start(policy: TrustPolicy) -> None:
    """Emit the resolved trust posture once at run start (D14)."""
    logger.info(
        "trust policy: selfReview={} execution_trust={} authority_trust={} "
        "resolved_from={} config_hash={}",
        policy.level,
        policy.execution_trust,
        policy.authority_trust,
        policy.resolved_from,
        policy.config_hash or "(no config file)",
    )
    if policy.level == "full":
        logger.warning(
            "trust.selfReview=full: operator opted out of D14/#200 separation — "
            "same-repo pull_request_target may grant approval authority on this run"
        )


def trust_policy_manifest_fields(policy: TrustPolicy) -> dict[str, str]:
    """Manifest keys merged into evidence run records (plan 13 W9)."""
    return {
        "trust_self_review": policy.level,
        "trust_execution": policy.execution_trust,
        "trust_authority": policy.authority_trust,
        "trust_resolved_from": policy.resolved_from,
        "trust_config_hash": policy.config_hash,
    }


__all__ = [
    "AuthorityTrust",
    "ExecutionTrust",
    "ResolvedFrom",
    "SelfReviewLevel",
    "TrustPolicy",
    "log_trust_policy_at_run_start",
    "resolve_trust_policy",
    "trust_policy_manifest_fields",
]
