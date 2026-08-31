"""W1.1 — Codex sandbox policy gate (wave plan 15, green after W2)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from loguru import logger
from tests.trust_credentials.support import (
    AGENT_SANDBOX_TIERS,
    DEFAULT_BRANCH_SHA,
    DEFAULT_HEAD_SHA,
    HEAD_SCENARIOS,
    SANDBOX_MATRIX,
    SELF_REVIEW_LEVELS,
    decision_honours_override,
    import_trust_policy_symbol,
    resolve_agent_sandbox_decision,
    scenario_event_and_name,
    write_trust_config,
)

from mergecraft.agents.codex import (
    CODEX_SANDBOX_ENV,
    CODEX_SANDBOX_UNSANDBOXED,
    _operator_sandbox_override,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


@pytest.mark.parametrize(
    ("tier", "scenario"),
    [(tier, scenario) for tier in AGENT_SANDBOX_TIERS for scenario in HEAD_SCENARIOS],
    ids=[f"{tier}-{scenario}" for tier in AGENT_SANDBOX_TIERS for scenario in HEAD_SCENARIOS],
)
def test_agent_sandbox_tier_head_matrix(tmp_path: Path, tier: str, scenario: str) -> None:
    """Every tier x head cell from W1.1 honours or refuses the operator override."""
    decision = resolve_agent_sandbox_decision(
        root=tmp_path,
        tier=tier,  # type: ignore[arg-type]
        scenario=scenario,  # type: ignore[arg-type]
    )
    expected = SANDBOX_MATRIX[(tier, scenario)]  # type: ignore[index]
    assert decision_honours_override(decision) is expected


def test_fork_head_is_hard_floor_in_every_tier(tmp_path: Path) -> None:
    """D1b — fork head refuses in all four tiers; name the floor explicitly."""
    for tier in AGENT_SANDBOX_TIERS:
        decision = resolve_agent_sandbox_decision(
            root=tmp_path,
            tier=tier,
            scenario="fork_head",
        )
        assert decision_honours_override(decision) is False, f"fork must refuse for tier={tier!r}"


def test_lane_d_coupling_self_review_does_not_open_sandbox_on_prt(tmp_path: Path) -> None:
    """D1a — selfReview analyzers + same-repo pull_request_target + dispatch still refuses."""
    decision = resolve_agent_sandbox_decision(
        root=tmp_path,
        tier="dispatch",
        scenario="same_repo_prt",
        self_review="analyzers",
    )
    assert decision_honours_override(decision) is False


@pytest.mark.parametrize("self_review", SELF_REVIEW_LEVELS)
def test_self_review_level_does_not_change_matrix_cells(tmp_path: Path, self_review: str) -> None:
    """Symmetric guard — flipping selfReview must not change any matrix cell."""
    for tier in AGENT_SANDBOX_TIERS:
        for scenario in HEAD_SCENARIOS:
            decision = resolve_agent_sandbox_decision(
                root=tmp_path,
                tier=tier,
                scenario=scenario,
                self_review=self_review,  # type: ignore[arg-type]
            )
            expected = SANDBOX_MATRIX[(tier, scenario)]
            assert decision_honours_override(decision) is expected


def test_merged_only_honours_when_head_is_ancestor_of_default(tmp_path: Path) -> None:
    """merged-only uses merge-base against the bound head SHA on the default branch."""
    with patch(
        "mergecraft.config.trust_policy.subprocess.run",
        return_value=type("R", (), {"returncode": 0})(),
    ):
        decision = resolve_agent_sandbox_decision(
            root=tmp_path,
            tier="merged-only",
            scenario="head_on_default",
            head_sha=DEFAULT_BRANCH_SHA,
        )
    assert decision_honours_override(decision) is True


def test_merged_only_refuses_when_default_branch_unfetched(tmp_path: Path) -> None:
    """An unfetched default branch is a refuse, not a crash or an honour."""
    with patch(
        "mergecraft.config.trust_policy.subprocess.run",
        return_value=type("R", (), {"returncode": 1})(),
    ):
        decision = resolve_agent_sandbox_decision(
            root=tmp_path,
            tier="merged-only",
            scenario="head_on_default",
            head_sha=DEFAULT_HEAD_SHA,
            simulate_merged_only_git=False,
        )
    assert decision_honours_override(decision) is False


def test_refused_override_logs_warning_with_contract_fields(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """D2 — refusal warns with head repo, event, tier, and override requested."""
    messages: list[str] = []
    handler_id = logger.add(
        lambda record: messages.append(record.record["message"]), level="WARNING"
    )
    try:
        resolve_agent_sandbox_decision(
            root=tmp_path,
            tier="dispatch",
            scenario="same_repo_prt",
            operator_override_requested=True,
        )
    finally:
        logger.remove(handler_id)
    joined = "\n".join(messages).lower()
    assert "pull_request_target" in joined or "prt" in joined
    assert "dispatch" in joined
    assert "override" in joined or "danger-full-access" in joined or "sandbox" in joined
    assert "acme" in joined or "alexhawat" in joined or "repo" in joined


def test_granted_override_is_recorded_in_run_manifest(tmp_path: Path) -> None:
    """D2a — honoured overrides land in the run record, not only refusals."""
    manifest_fn = import_trust_policy_symbol("agent_sandbox_manifest_fields")
    decision = resolve_agent_sandbox_decision(
        root=tmp_path,
        tier="same-repo",
        scenario="same_repo_pr",
    )
    fields = manifest_fn(decision)
    assert fields.get("agent_sandbox_honoured") == "true" or fields.get("agent_sandbox_granted")
    assert fields.get("agent_sandbox_tier") or fields.get("configured_agent_sandbox")
    assert fields.get("agent_sandbox_event") or fields.get("event_name")


def test_unrecognised_codex_sandbox_env_warns_and_returns_none(
    monkeypatch: MonkeyPatch,
) -> None:
    """Regression — unknown MERGECRAFT_CODEX_SANDBOX values stay ignored (codex.py)."""
    monkeypatch.setenv(CODEX_SANDBOX_ENV, "typo-danger-full-access")
    with patch.object(logger, "warning") as warn_mock:
        assert _operator_sandbox_override() is None
    warn_mock.assert_called_once()
    call_args = warn_mock.call_args[0]
    assert CODEX_SANDBOX_ENV in str(call_args[0]) or CODEX_SANDBOX_ENV in str(call_args)


@pytest.mark.parametrize("raw", ["", "not-a-tier", "DISPATCH"])
def test_absent_or_malformed_agent_sandbox_defaults_to_dispatch(tmp_path: Path, raw: str) -> None:
    """Absent / malformed trust.agentSandbox falls back to dispatch, not same-repo."""
    write_trust_config(tmp_path, agent_sandbox=raw if raw else None)
    resolve = import_trust_policy_symbol("resolve_agent_sandbox_decision")
    event_name, event = scenario_event_and_name("workflow_dispatch")
    from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot

    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    decision = resolve(
        event=event,
        event_name=event_name,
        config_root=tmp_path,
        settings_snapshot=snapshot,
        head_sha=DEFAULT_HEAD_SHA,
        operator_override_requested=True,
    )
    assert decision_honours_override(decision) is True
    tier = getattr(decision, "configured_tier", None) or getattr(decision, "resolved_tier", None)
    assert tier in {None, "dispatch"}


def test_agent_sandbox_policy_reads_base_snapshot_not_pr_head(tmp_path: Path) -> None:
    """D1d/D16 — PR-head config edits cannot flip the sandbox policy mid-run."""
    write_trust_config(tmp_path, agent_sandbox="same-repo", self_review="off")
    from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot

    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    write_trust_config(tmp_path, agent_sandbox="never", self_review="off")
    decision = resolve_agent_sandbox_decision(
        root=tmp_path,
        tier="same-repo",
        scenario="same_repo_pr",
        settings_snapshot=snapshot,
    )
    assert decision_honours_override(decision) is True


def test_operator_override_requested_false_never_honours(tmp_path: Path) -> None:
    """Without MERGECRAFT_CODEX_SANDBOX the gate must not grant unsandboxed mode."""
    decision = resolve_agent_sandbox_decision(
        root=tmp_path,
        tier="same-repo",
        scenario="workflow_dispatch",
        operator_override_requested=False,
    )
    assert decision_honours_override(decision) is False


def test_codex_unsandboxed_constant_is_stable() -> None:
    """Regression guard — the env value the workflow documents stays stable."""
    assert CODEX_SANDBOX_UNSANDBOXED == "danger-full-access"
