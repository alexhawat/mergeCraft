"""Shared helpers for wave plan 15 — trust boundary & credential truth."""

from __future__ import annotations

import importlib
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

import pytest
import yaml
from tests.analyzers.support import (
    FORK_PULL_REQUEST_EVENT,
    SAME_REPO_PULL_REQUEST_EVENT,
)

from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot

AgentSandboxLevel = Literal["never", "merged-only", "dispatch", "same-repo"]
SelfReviewLevel = Literal["off", "analyzers", "full"]
HeadScenario = Literal[
    "fork_head",
    "same_repo_prt",
    "same_repo_pr",
    "workflow_dispatch",
    "head_on_default",
]

W2_XFAIL = pytest.mark.xfail(reason="green after W2: agentSandbox policy gate", strict=True)
W3_XFAIL = pytest.mark.xfail(reason="green after W3: analyzer egress fail-closed", strict=True)
W4_XFAIL = pytest.mark.xfail(reason="green after W4: credential probe consolidation", strict=True)
W5_XFAIL = pytest.mark.xfail(reason="green after W5: Logfire action token seam", strict=True)
W6_XFAIL = pytest.mark.xfail(reason="green after W6: entropy redaction evidence", strict=True)

NOUS_SLUG = "nous/deepseek/deepseek-v4-flash"
DEFAULT_HEAD_SHA = "abc123def4567890abcdef1234567890abcd1234"
DEFAULT_BRANCH_SHA = "deadbeef" * 5  # 40-char hex on default branch

# Tier x head matrix from W1.1 (honour == grant operator sandbox override).
SANDBOX_MATRIX: dict[tuple[AgentSandboxLevel, HeadScenario], bool] = {
    ("never", "fork_head"): False,
    ("never", "same_repo_prt"): False,
    ("never", "same_repo_pr"): False,
    ("never", "workflow_dispatch"): False,
    ("never", "head_on_default"): False,
    ("merged-only", "fork_head"): False,
    ("merged-only", "same_repo_prt"): False,
    ("merged-only", "same_repo_pr"): False,
    ("merged-only", "workflow_dispatch"): False,
    ("merged-only", "head_on_default"): True,
    ("dispatch", "fork_head"): False,
    ("dispatch", "same_repo_prt"): False,
    ("dispatch", "same_repo_pr"): False,
    ("dispatch", "workflow_dispatch"): True,
    ("dispatch", "head_on_default"): True,
    ("same-repo", "fork_head"): False,
    ("same-repo", "same_repo_prt"): True,
    ("same-repo", "same_repo_pr"): True,
    ("same-repo", "workflow_dispatch"): True,
    ("same-repo", "head_on_default"): True,
}

SELF_REVIEW_LEVELS: tuple[SelfReviewLevel, ...] = ("off", "analyzers", "full")
AGENT_SANDBOX_TIERS: tuple[AgentSandboxLevel, ...] = (
    "never",
    "merged-only",
    "dispatch",
    "same-repo",
)
HEAD_SCENARIOS: tuple[HeadScenario, ...] = (
    "fork_head",
    "same_repo_prt",
    "same_repo_pr",
    "workflow_dispatch",
    "head_on_default",
)


def write_trust_config(
    root: Path,
    *,
    agent_sandbox: str | None = "dispatch",
    self_review: SelfReviewLevel = "off",
    extra_lines: str = "",
) -> Path:
    """Write ``.mergecraft/config.yaml`` with trust knobs."""
    config_dir = root / ".mergecraft"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "config.yaml"
    lines = ["trust:"]
    if self_review != "off":
        lines.append(f"  selfReview: '{self_review}'")
    else:
        lines.append("  selfReview: 'off'")
    if agent_sandbox is not None:
        lines.append(f"  agentSandbox: '{agent_sandbox}'")
    if extra_lines:
        lines.append(extra_lines.rstrip("\n"))
    lines.extend(
        [
            "model: anthropic/claude-sonnet",
            "push: restricted",
            "shell: restricted",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def scenario_event_and_name(
    scenario: HeadScenario,
    *,
    head_sha: str = DEFAULT_HEAD_SHA,
) -> tuple[str, dict[str, Any]]:
    """Return ``(event_name, event_payload)`` for a matrix column."""
    if scenario == "fork_head":
        return "pull_request", deepcopy(FORK_PULL_REQUEST_EVENT)
    if scenario == "same_repo_prt":
        event = deepcopy(SAME_REPO_PULL_REQUEST_EVENT)
        event["pull_request"]["head"]["sha"] = head_sha  # type: ignore[index]
        return "pull_request_target", event
    if scenario == "same_repo_pr":
        event = deepcopy(SAME_REPO_PULL_REQUEST_EVENT)
        event["pull_request"]["head"]["sha"] = head_sha  # type: ignore[index]
        return "pull_request", event
    if scenario == "workflow_dispatch":
        return "workflow_dispatch", {
            "repository": {
                "full_name": "acme/demo",
                "default_branch": "main",
            },
            "ref": "refs/heads/feature-branch",
            "head_sha": head_sha,
        }
    if scenario == "head_on_default":
        return "workflow_dispatch", {
            "repository": {
                "full_name": "acme/demo",
                "default_branch": "main",
            },
            "ref": "refs/heads/main",
            "head_sha": DEFAULT_BRANCH_SHA,
        }
    msg = f"unknown head scenario: {scenario!r}"
    raise ValueError(msg)


def import_trust_policy_symbol(name: str) -> Any:
    module = importlib.import_module("mergecraft.config.trust_policy")
    try:
        return getattr(module, name)
    except AttributeError as exc:
        pytest.fail(f"mergecraft.config.trust_policy.{name} not implemented: {exc}")


def import_agent_resolve_symbol(name: str) -> Any:
    module = importlib.import_module("mergecraft.utils.agent_resolve")
    try:
        return getattr(module, name)
    except AttributeError as exc:
        pytest.fail(f"mergecraft.utils.agent_resolve.{name} not implemented: {exc}")


def import_action_symbol(name: str) -> Any:
    module = importlib.import_module("mergecraft.action.inputs")
    try:
        return getattr(module, name)
    except AttributeError as exc:
        pytest.fail(f"mergecraft.action.inputs.{name} not implemented: {exc}")


def import_analyzer_egress_symbol(name: str) -> Any:
    for module_name in ("mergecraft.analyzers.sandbox", "mergecraft.analyzers.egress"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        if hasattr(module, name):
            return getattr(module, name)
    pytest.fail(
        f"analyzer egress symbol {name!r} not implemented "
        "(expected in mergecraft.analyzers.sandbox or .egress)"
    )


def resolve_agent_sandbox_decision(
    *,
    root: Path,
    tier: AgentSandboxLevel,
    scenario: HeadScenario,
    self_review: SelfReviewLevel = "off",
    operator_override_requested: bool = True,
    settings_snapshot: Any | None = None,
    head_sha: str | None = None,
    default_branch: str = "main",
) -> Any:
    """Call the W2 policy resolver (pinned API)."""
    resolve = import_trust_policy_symbol("resolve_agent_sandbox_decision")
    event_name, event = scenario_event_and_name(scenario, head_sha=head_sha or DEFAULT_HEAD_SHA)
    write_trust_config(root, agent_sandbox=tier, self_review=self_review)
    snapshot = settings_snapshot or capture_repo_settings_snapshot(
        root=root, load_learnings_files=False
    )
    bound_sha = head_sha
    if bound_sha is None:
        bound_sha = DEFAULT_BRANCH_SHA if scenario == "head_on_default" else DEFAULT_HEAD_SHA
    return resolve(
        event=event,
        event_name=event_name,
        config_root=root,
        settings_snapshot=snapshot,
        head_sha=bound_sha,
        default_branch=default_branch,
        operator_override_requested=operator_override_requested,
    )


def decision_honours_override(decision: Any) -> bool:
    if hasattr(decision, "honour"):
        return bool(decision.honour)
    if isinstance(decision, tuple) and decision:
        return bool(decision[0])
    pytest.fail(f"unexpected agent sandbox decision shape: {decision!r}")


def load_config_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


__all__ = [
    "AGENT_SANDBOX_TIERS",
    "DEFAULT_BRANCH_SHA",
    "DEFAULT_HEAD_SHA",
    "HEAD_SCENARIOS",
    "NOUS_SLUG",
    "SANDBOX_MATRIX",
    "SELF_REVIEW_LEVELS",
    "W2_XFAIL",
    "W3_XFAIL",
    "W4_XFAIL",
    "W5_XFAIL",
    "W6_XFAIL",
    "decision_honours_override",
    "import_action_symbol",
    "import_agent_resolve_symbol",
    "import_analyzer_egress_symbol",
    "import_trust_policy_symbol",
    "load_config_dict",
    "resolve_agent_sandbox_decision",
    "scenario_event_and_name",
    "write_trust_config",
]
