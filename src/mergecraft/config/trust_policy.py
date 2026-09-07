"""Two-axis trust policy resolution for review runs (plan 13 D13-D16).

**Execution trust** answers whether analyzers and repo-executable config may run
against this checkout. **Authority trust** answers whether the agent's own
terminal output may unlock approval semantics on this run.

The operator knob ``trust.selfReview`` is read only from the base-tree settings
snapshot (lane C ``settings_snapshot`` / MCB-19) — never from a PR head edit.

``trust.agentSandbox`` (lane B / #553) is resolved the same way but gates only
whether ``MERGECRAFT_CODEX_SANDBOX=danger-full-access`` is honoured — never
``execution_trust`` or ``tool_state.trust_tier`` (D1a).

``trust.sandboxTrustedAuthors`` is an additive-only precondition on top of the
``agentSandbox`` tier: empty (default) changes nothing; non-empty requires every
commit's author *and* committer email in the bound PR head range to be on the
list, or the override is refused even on a tier that would otherwise grant it.
It can never grant an override a tier refuses, and the fork floor still runs
first. See ``docs/trust-policy.md``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — ``config_root.resolve()`` runs at runtime
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.config.settings import AgentSandboxLevel, TrustTier
from mergecraft.utils.git_hardening import git_argv

if TYPE_CHECKING:
    from mergecraft.config.settings_snapshot import RepoSettingsSnapshot

ExecutionTrust = TrustTier
AuthorityTrust = TrustTier
SelfReviewLevel = Literal["off", "analyzers", "full"]
ResolvedFrom = Literal["base_snapshot", "live_load"]

_AGENT_SANDBOX_LEVELS: frozenset[str] = frozenset({"never", "merged-only", "dispatch", "same-repo"})
AGENT_SANDBOX_LEVELS = _AGENT_SANDBOX_LEVELS
_TIER_LOOSEN_ORDER: tuple[AgentSandboxLevel, ...] = (
    "never",
    "merged-only",
    "dispatch",
    "same-repo",
)


@dataclass(frozen=True, slots=True)
class TrustPolicy:
    """Effective trust posture for one review run."""

    level: SelfReviewLevel
    execution_trust: ExecutionTrust
    authority_trust: AuthorityTrust
    resolved_from: ResolvedFrom
    config_hash: str


AuthorGateStatus = Literal["not-configured", "passed", "refused", "unevaluated"]


@dataclass(frozen=True, slots=True)
class AgentSandboxDecision:
    """Whether ``danger-full-access`` is granted for one run (lane B D1/D2)."""

    honour: bool
    reason: str
    configured_tier: AgentSandboxLevel
    resolved_from: ResolvedFrom
    event_name: str
    head_status: str
    operator_override_requested: bool
    granting_tier: AgentSandboxLevel | None = None
    author_gate: AuthorGateStatus = "not-configured"
    author_gate_offending_email: str | None = None


@dataclass(frozen=True, slots=True)
class _AuthorGateOutcome:
    """Result of evaluating ``trust.sandboxTrustedAuthors`` against one head range."""

    status: Literal["not-configured", "passed", "refused"]
    offending_email: str | None = None
    detail: str | None = None


def is_fork_pull_request(event: dict[str, Any]) -> bool:
    """Return True when the GitHub event payload describes a fork PR head."""
    return _is_fork_pull_request(event)


def bound_head_sha(event: dict[str, Any], *, event_name: str) -> str:
    """Return the head SHA bound for sandbox policy on this event."""
    if event_name == "workflow_dispatch":
        for key in ("head_sha", "after"):
            candidate = event.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    pull_request = event.get("pull_request")
    if isinstance(pull_request, dict):
        head = pull_request.get("head")
        if isinstance(head, dict):
            sha = head.get("sha")
            if isinstance(sha, str) and sha.strip():
                return sha.strip()
    return ""


def default_branch_from_event(event: dict[str, Any]) -> str:
    repository = event.get("repository")
    if isinstance(repository, dict):
        branch = repository.get("default_branch")
        if isinstance(branch, str) and branch.strip():
            return branch.strip()
    return "main"


def _is_fork_pull_request(event: dict[str, Any]) -> bool:
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return False
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


def _read_agent_sandbox_level(settings: Any) -> AgentSandboxLevel:
    trust = getattr(settings, "trust", None)
    raw = getattr(trust, "agent_sandbox", "dispatch")
    if raw in _AGENT_SANDBOX_LEVELS:
        return raw  # type: ignore[return-value]  # — value verified against AgentSandboxLevel literals above
    return "dispatch"


def _read_sandbox_trusted_authors(settings: Any) -> tuple[str, ...]:
    """Read ``trust.sandboxTrustedAuthors`` defensively; empty means "not configured"."""
    trust = getattr(settings, "trust", None)
    raw = getattr(trust, "sandbox_trusted_authors", [])
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return tuple(raw)
    return ()


def _head_repo_label(event: dict[str, Any]) -> str:
    pull_request = event.get("pull_request")
    if isinstance(pull_request, dict):
        head = pull_request.get("head")
        if isinstance(head, dict):
            repo = head.get("repo")
            if isinstance(repo, dict):
                full_name = repo.get("full_name")
                if isinstance(full_name, str) and full_name.strip():
                    return full_name
    repository = event.get("repository")
    if isinstance(repository, dict):
        full_name = repository.get("full_name")
        if isinstance(full_name, str) and full_name.strip():
            return full_name
    return "unknown"


def _describe_head_status(event_name: str, event: dict[str, Any]) -> str:
    if _is_fork_pull_request(event):
        return f"fork ({_head_repo_label(event)})"
    if event_name == "workflow_dispatch":
        repository = event.get("repository")
        default_branch = "main"
        if isinstance(repository, dict):
            candidate = repository.get("default_branch")
            if isinstance(candidate, str) and candidate.strip():
                default_branch = candidate
        ref = event.get("ref")
        if isinstance(ref, str) and ref.endswith(f"/{default_branch}"):
            return f"default-branch ({_head_repo_label(event)})"
        return f"same-repo dispatch ({_head_repo_label(event)})"
    return f"same-repo {event_name} ({_head_repo_label(event)})"


def _head_is_ancestor_of_default(
    *,
    head_sha: str,
    default_branch: str,
    config_root: Path,
) -> bool:
    remote_ref = f"origin/{default_branch}"
    fetch = subprocess.run(
        git_argv(["fetch", "origin", default_branch]),
        cwd=str(config_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if fetch.returncode != 0:
        return False
    probe = subprocess.run(
        git_argv(["merge-base", "--is-ancestor", head_sha, remote_ref]),
        cwd=str(config_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return probe.returncode == 0


def _base_sha_for_author_gate(
    *,
    event: dict[str, Any],
    default_branch: str,
    config_root: Path,
) -> str | None:
    """Resolve the range's base sha: ``pull_request.base.sha``, else ``origin/<default>``."""
    pull_request = event.get("pull_request")
    if isinstance(pull_request, dict):
        base = pull_request.get("base")
        if isinstance(base, dict):
            sha = base.get("sha")
            if isinstance(sha, str) and sha.strip():
                return sha.strip()
    remote_ref = f"origin/{default_branch}"
    fetch = subprocess.run(
        git_argv(["fetch", "origin", default_branch]),
        cwd=str(config_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if fetch.returncode != 0:
        return None
    probe = subprocess.run(
        git_argv(["rev-parse", remote_ref]),
        cwd=str(config_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        return None
    resolved = probe.stdout.strip()
    return resolved or None


def _commit_emails_in_range(
    *,
    base_sha: str,
    head_sha: str,
    config_root: Path,
) -> list[str] | None:
    """Return every author+committer email over ``(base_sha, head_sha]``, or None on failure."""
    result = subprocess.run(
        git_argv(["log", "--format=%ae%n%ce", f"{base_sha}..{head_sha}"]),
        cwd=str(config_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _evaluate_author_gate(
    *,
    trusted_authors: tuple[str, ...],
    event: dict[str, Any],
    head_sha: str,
    default_branch: str,
    config_root: Path,
) -> _AuthorGateOutcome:
    """Evaluate ``trust.sandboxTrustedAuthors`` against the PR head range (fails closed)."""
    if not trusted_authors:
        return _AuthorGateOutcome(status="not-configured")
    if not head_sha.strip():
        return _AuthorGateOutcome(
            status="refused",
            detail="no head sha bound for this run — commit range cannot be computed",
        )
    base_sha = _base_sha_for_author_gate(
        event=event, default_branch=default_branch, config_root=config_root
    )
    if not base_sha:
        return _AuthorGateOutcome(
            status="refused",
            detail="base sha could not be resolved from the event or origin/<default-branch>",
        )
    emails = _commit_emails_in_range(base_sha=base_sha, head_sha=head_sha, config_root=config_root)
    if emails is None:
        return _AuthorGateOutcome(
            status="refused",
            detail=f"git log over {base_sha[:12]}..{head_sha[:12]} failed",
        )
    if not emails:
        return _AuthorGateOutcome(
            status="refused",
            detail=f"git log over {base_sha[:12]}..{head_sha[:12]} returned no commits",
        )
    allowlist = {author.lower() for author in trusted_authors}
    for email in emails:
        if email.lower() not in allowlist:
            return _AuthorGateOutcome(
                status="refused",
                offending_email=email,
                detail=f"commit author/committer {email!r} is not in trust.sandboxTrustedAuthors",
            )
    return _AuthorGateOutcome(status="passed")


def _tier_native_honours_override(
    tier: AgentSandboxLevel,
    *,
    event_name: str,
    event: dict[str, Any],
    head_sha: str,
    default_branch: str,
    config_root: Path,
) -> bool:
    """Whether ``tier`` grants the override on this head, ignoring the author gate."""
    if _is_fork_pull_request(event):
        return False
    if tier == "never":
        return False
    if tier == "same-repo":
        return True
    if tier == "dispatch":
        return event_name == "workflow_dispatch"
    if tier == "merged-only":
        return _head_is_ancestor_of_default(
            head_sha=head_sha,
            default_branch=default_branch,
            config_root=config_root,
        )
    return event_name == "workflow_dispatch"


def _tier_honours_override(
    tier: AgentSandboxLevel,
    *,
    event_name: str,
    event: dict[str, Any],
    head_sha: str,
    default_branch: str,
    config_root: Path,
    author_gate: _AuthorGateOutcome | None = None,
) -> bool:
    """Whether ``tier`` grants the override — tier logic, then the additive author gate.

    ``author_gate`` is a precondition that can only tighten this result: it may turn
    a tier-granted override into a refusal, never the reverse. Omit it (or pass a
    ``not-configured`` outcome) to get the tier's native behaviour unchanged.
    """
    if not _tier_native_honours_override(
        tier,
        event_name=event_name,
        event=event,
        head_sha=head_sha,
        default_branch=default_branch,
        config_root=config_root,
    ):
        return False
    return not (author_gate is not None and author_gate.status == "refused")


def _minimal_granting_tier(
    *,
    event_name: str,
    event: dict[str, Any],
    head_sha: str,
    default_branch: str,
    config_root: Path,
    author_gate: _AuthorGateOutcome | None = None,
) -> AgentSandboxLevel | None:
    if _is_fork_pull_request(event):
        return None
    for tier in reversed(_TIER_LOOSEN_ORDER):
        if _tier_honours_override(
            tier,
            event_name=event_name,
            event=event,
            head_sha=head_sha,
            default_branch=default_branch,
            config_root=config_root,
            author_gate=author_gate,
        ):
            return tier
    return None


def _log_agent_sandbox_decision(decision: AgentSandboxDecision) -> None:
    if decision.honour:
        logger.info(
            "agent sandbox override granted: tier={} head={} event={} reason={}",
            decision.configured_tier,
            decision.head_status,
            decision.event_name,
            decision.reason,
        )
        return
    if not decision.operator_override_requested:
        return
    if decision.author_gate == "refused":
        logger.warning(
            "agent sandbox override refused: head={} event={} configured_tier={} "
            "operator_override_requested=true reason={}. "
            "Commit author/committer {} is not in trust.sandboxTrustedAuthors — "
            "add it to trust.sandboxTrustedAuthors or do not push fork branches to origin.",
            decision.head_status,
            decision.event_name,
            decision.configured_tier,
            decision.reason,
            decision.author_gate_offending_email or "(unresolved — see reason)",
        )
        return
    if decision.granting_tier is None:
        logger.warning(
            "agent sandbox override refused: head={} event={} configured_tier={} "
            "operator_override_requested=true reason={}. "
            "No trust.agentSandbox tier grants override on this head.",
            decision.head_status,
            decision.event_name,
            decision.configured_tier,
            decision.reason,
        )
        return
    logger.warning(
        "agent sandbox override refused: head={} event={} configured_tier={} "
        "operator_override_requested=true reason={}. "
        "Set trust.agentSandbox to {!r} (mergecraft trust set-agent-sandbox {}) "
        "if this runner should skip Codex's nested sandbox.",
        decision.head_status,
        decision.event_name,
        decision.configured_tier,
        decision.reason,
        decision.granting_tier,
        decision.granting_tier,
    )


def resolve_agent_sandbox_decision(
    *,
    event: dict[str, Any],
    event_name: str,
    config_root: Path,
    settings_snapshot: RepoSettingsSnapshot | None = None,
    head_sha: str,
    default_branch: str = "main",
    operator_override_requested: bool = True,
) -> AgentSandboxDecision:
    """Resolve whether ``danger-full-access`` is honoured for this run (D1/D1a/D1d)."""
    resolved_from: ResolvedFrom
    if settings_snapshot is not None:
        settings = settings_snapshot.settings
        resolved_from = "base_snapshot"
    else:
        from mergecraft.config.settings_snapshot import load_repo_settings

        settings = load_repo_settings(root=config_root.resolve(), load_learnings_files=False)
        resolved_from = "live_load"

    configured_tier = _read_agent_sandbox_level(settings)
    trusted_authors = _read_sandbox_trusted_authors(settings)
    head_status = _describe_head_status(event_name, event)
    repo_root = config_root.resolve()

    if _is_fork_pull_request(event):
        decision = AgentSandboxDecision(
            honour=False,
            reason="fork head is a hard floor — no tier grants sandbox override",
            configured_tier=configured_tier,
            resolved_from=resolved_from,
            event_name=event_name,
            head_status=head_status,
            operator_override_requested=operator_override_requested,
            granting_tier=None,
            author_gate="unevaluated" if trusted_authors else "not-configured",
        )
        _log_agent_sandbox_decision(decision)
        return decision

    # Native tier logic — before the author gate — decides whether the gate is the
    # deciding factor for the *configured* tier's own outcome. It does not gate
    # whether we compute the author-gate result at all: reaching here means this
    # head is not a fork, so "same-repo" always natively honours, and
    # ``_minimal_granting_tier`` below needs the real gate result to avoid
    # recommending a looser tier the gate would refuse anyway.
    configured_native_honour = _tier_native_honours_override(
        configured_tier,
        event_name=event_name,
        event=event,
        head_sha=head_sha,
        default_branch=default_branch,
        config_root=repo_root,
    )

    author_gate_outcome = _AuthorGateOutcome(status="not-configured")
    if trusted_authors:
        author_gate_outcome = _evaluate_author_gate(
            trusted_authors=trusted_authors,
            event=event,
            head_sha=head_sha,
            default_branch=default_branch,
            config_root=repo_root,
        )

    granting_tier = _minimal_granting_tier(
        event_name=event_name,
        event=event,
        head_sha=head_sha,
        default_branch=default_branch,
        config_root=repo_root,
        author_gate=author_gate_outcome if trusted_authors else None,
    )

    if trusted_authors:
        author_gate_status: AuthorGateStatus = (
            author_gate_outcome.status if configured_native_honour else "unevaluated"
        )
    else:
        author_gate_status = "not-configured"

    if not operator_override_requested:
        return AgentSandboxDecision(
            honour=False,
            reason="MERGECRAFT_CODEX_SANDBOX override not requested",
            configured_tier=configured_tier,
            resolved_from=resolved_from,
            event_name=event_name,
            head_status=head_status,
            operator_override_requested=False,
            granting_tier=granting_tier,
            author_gate=author_gate_status,
            author_gate_offending_email=author_gate_outcome.offending_email,
        )

    honour = configured_native_honour and author_gate_outcome.status != "refused"
    if not configured_native_honour:
        reason = (
            f"trust.agentSandbox={configured_tier} refuses override for "
            f"event={event_name} head={head_status}"
        )
    elif author_gate_outcome.status == "refused":
        reason = (
            f"trust.agentSandbox={configured_tier} would grant override for {head_status}, "
            f"but trust.sandboxTrustedAuthors refuses it: {author_gate_outcome.detail}"
        )
    else:
        reason = f"trust.agentSandbox={configured_tier} grants override for {head_status}"
    decision = AgentSandboxDecision(
        honour=honour,
        reason=reason,
        configured_tier=configured_tier,
        resolved_from=resolved_from,
        event_name=event_name,
        head_status=head_status,
        operator_override_requested=operator_override_requested,
        granting_tier=granting_tier,
        author_gate=author_gate_status,
        author_gate_offending_email=author_gate_outcome.offending_email,
    )
    _log_agent_sandbox_decision(decision)
    return decision


def agent_sandbox_manifest_fields(decision: AgentSandboxDecision) -> dict[str, str]:
    """Manifest keys for agent sandbox posture (lane B D2a)."""
    fields: dict[str, str] = {
        "agent_sandbox_tier": decision.configured_tier,
        "configured_agent_sandbox": decision.configured_tier,
        "agent_sandbox_event": decision.event_name,
        "event_name": decision.event_name,
        "agent_sandbox_head_status": decision.head_status,
        "agent_sandbox_resolved_from": decision.resolved_from,
        "agent_sandbox_reason": decision.reason,
    }
    if decision.honour:
        fields["agent_sandbox_honoured"] = "true"
        fields["agent_sandbox_granted"] = "true"
    else:
        fields["agent_sandbox_honoured"] = "false"
        fields["agent_sandbox_granted"] = "false"
    if decision.granting_tier is not None:
        fields["agent_sandbox_granting_tier"] = decision.granting_tier
    fields["agent_sandbox_author_gate"] = decision.author_gate
    if decision.author_gate_offending_email:
        fields["agent_sandbox_author_gate_offending_email"] = decision.author_gate_offending_email
    return fields


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
    # One source of truth for the event name. Deriving the base tier from the
    # ambient ``GITHUB_EVENT_NAME`` while judging ``_same_repo_pull_request_target``
    # from the argument let the two disagree — a ``pull_request_target`` run
    # resolved ``trusted`` at ``selfReview: off`` whenever the ambient value said
    # ``pull_request``, and ``mergecraft trust show`` reported that posture.
    base_tier = derive_trust_tier(event=event, shell=shell, offline=offline, event_name=event_name)
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
    "AGENT_SANDBOX_LEVELS",
    "AgentSandboxDecision",
    "AuthorGateStatus",
    "AuthorityTrust",
    "ExecutionTrust",
    "ResolvedFrom",
    "SelfReviewLevel",
    "TrustPolicy",
    "agent_sandbox_manifest_fields",
    "bound_head_sha",
    "default_branch_from_event",
    "is_fork_pull_request",
    "log_trust_policy_at_run_start",
    "resolve_agent_sandbox_decision",
    "resolve_trust_policy",
    "trust_policy_manifest_fields",
]
