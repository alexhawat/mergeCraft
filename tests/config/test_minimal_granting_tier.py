"""#1239 — the recommended ``trust.agentSandbox`` tier is the tightest that grants, not the loosest."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from mergecraft.config import trust_policy
from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
from mergecraft.config.trust_policy import (
    _AuthorGateOutcome,
    _minimal_granting_tier,
    agent_sandbox_manifest_fields,
    resolve_agent_sandbox_decision,
)
from tests.analyzers.support import FORK_PULL_REQUEST_EVENT, SAME_REPO_PULL_REQUEST_EVENT
from tests.trust_credentials.support import write_trust_config

_HEAD_SHA = "d" * 40
_DISPATCH_EVENT: dict[str, Any] = {
    "repository": {"full_name": "acme/demo", "default_branch": "main"},
    "ref": "refs/heads/feature-branch",
}


def _patch_ancestor(monkeypatch: pytest.MonkeyPatch, *, is_ancestor: bool) -> list[str]:
    """Answer the ``merged-only`` ancestry probe without git; record the heads it saw."""
    probed: list[str] = []

    def _fake(*, head_sha: str, default_branch: str, config_root: Path) -> bool:
        probed.append(head_sha)
        return is_ancestor

    monkeypatch.setattr(trust_policy, "_head_is_ancestor_of_default", _fake)
    return probed


def _tier(
    event_name: str,
    event: dict[str, Any],
    *,
    author_gate: _AuthorGateOutcome | None = None,
) -> str | None:
    return _minimal_granting_tier(
        event_name=event_name,
        event=event,
        head_sha=_HEAD_SHA,
        default_branch="main",
        config_root=Path("."),
        author_gate=author_gate,
    )


def test_workflow_dispatch_recommends_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ancestor(monkeypatch, is_ancestor=False)
    assert _tier("workflow_dispatch", _DISPATCH_EVENT) == "dispatch"


@pytest.mark.parametrize("event_name", ["workflow_dispatch", "pull_request"])
def test_a_head_merged_into_the_default_branch_recommends_merged_only(
    monkeypatch: pytest.MonkeyPatch, event_name: str
) -> None:
    probed = _patch_ancestor(monkeypatch, is_ancestor=True)
    event = _DISPATCH_EVENT if event_name == "workflow_dispatch" else SAME_REPO_PULL_REQUEST_EVENT
    assert _tier(event_name, event) == "merged-only"
    assert probed == [_HEAD_SHA]


def test_same_repo_pull_request_recommends_same_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ancestor(monkeypatch, is_ancestor=False)
    assert _tier("pull_request", SAME_REPO_PULL_REQUEST_EVENT) == "same-repo"


def test_fork_head_recommends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    probed = _patch_ancestor(monkeypatch, is_ancestor=True)
    assert _tier("pull_request", FORK_PULL_REQUEST_EVENT) is None
    assert probed == [], "the fork floor must answer before any git probe"


def test_refused_author_gate_recommends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_ancestor(monkeypatch, is_ancestor=True)
    refused = _AuthorGateOutcome(status="refused", detail="foreign author")
    assert _tier("workflow_dispatch", _DISPATCH_EVENT, author_gate=refused) is None
    assert _tier("pull_request", SAME_REPO_PULL_REQUEST_EVENT, author_gate=refused) is None


def _decide(
    tmp_path: Path, *, configured: str, event_name: str, event: dict[str, Any]
) -> trust_policy.AgentSandboxDecision:
    write_trust_config(tmp_path, agent_sandbox=configured, self_review="off")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    return resolve_agent_sandbox_decision(
        event=deepcopy(event),
        event_name=event_name,
        config_root=tmp_path,
        settings_snapshot=snapshot,
        head_sha=_HEAD_SHA,
        operator_override_requested=True,
    )


def test_refusal_decision_and_manifest_name_the_tightest_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The public decision (remedy text + manifest) carries ``dispatch``, not ``same-repo``."""
    _patch_ancestor(monkeypatch, is_ancestor=False)
    decision = _decide(
        tmp_path, configured="never", event_name="workflow_dispatch", event=_DISPATCH_EVENT
    )
    assert decision.honour is False
    assert decision.granting_tier == "dispatch"
    assert agent_sandbox_manifest_fields(decision)["agent_sandbox_granting_tier"] == "dispatch"


def test_a_configured_tier_that_already_grants_is_the_granting_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``same-repo`` grants a merged head too; do not tell the operator to switch to ``merged-only``."""
    probed = _patch_ancestor(monkeypatch, is_ancestor=True)
    decision = _decide(
        tmp_path,
        configured="same-repo",
        event_name="pull_request",
        event=SAME_REPO_PULL_REQUEST_EVENT,
    )
    assert decision.honour is True
    assert decision.granting_tier == "same-repo"
    assert probed == []


def test_no_override_does_not_probe_for_a_remedy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probed = _patch_ancestor(monkeypatch, is_ancestor=False)
    write_trust_config(tmp_path, agent_sandbox="dispatch", self_review="off")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    decision = resolve_agent_sandbox_decision(
        event=deepcopy(SAME_REPO_PULL_REQUEST_EVENT),
        event_name="pull_request",
        config_root=tmp_path,
        settings_snapshot=snapshot,
        head_sha=_HEAD_SHA,
        operator_override_requested=False,
    )
    assert not decision.honour
    assert decision.granting_tier is None
    assert probed == []
