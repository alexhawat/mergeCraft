"""``trust.sandboxTrustedAuthors`` — additive author-gate on the Codex sandbox override.

fix/verdict-integrity-and-publication Task A: closes the "fork PR checked out onto
a local branch looks like a same-repo head" gap documented in ``docs/trust-policy.md``.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
from mergecraft.config.trust_policy import (
    AgentSandboxDecision,
    agent_sandbox_manifest_fields,
    resolve_agent_sandbox_decision,
)
from tests.analyzers.support import FORK_PULL_REQUEST_EVENT, SAME_REPO_PULL_REQUEST_EVENT
from tests.trust_credentials.support import AGENT_SANDBOX_TIERS, write_trust_config

_HEAD_SHA = "c" * 40
_TRUSTED = "trusted@example.com"
_ALSO_TRUSTED = "also-trusted@example.com"
_FOREIGN = "attacker@evil.example"


def _same_repo_event(head_sha: str = _HEAD_SHA) -> dict[str, Any]:
    event = deepcopy(SAME_REPO_PULL_REQUEST_EVENT)
    event["pull_request"]["head"]["sha"] = head_sha  # type: ignore[index]
    return event


class _GitResult:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _mock_git_log(emails: list[str] | None, *, returncode: int = 0) -> Any:
    """Patch ``subprocess.run`` so ``git log --format=%ae%n%ce ...`` answers deterministically."""
    stdout = "".join(f"{email}\n" for email in (emails or []))
    result = _GitResult(returncode=returncode, stdout=stdout)
    return patch("mergecraft.config.trust_policy.subprocess.run", return_value=result)


def _write_config(
    root: Path,
    *,
    tier: str,
    trusted_authors: list[str] | None,
) -> None:
    extra = ""
    if trusted_authors is not None:
        if trusted_authors:
            items = "\n".join(f"    - '{email}'" for email in trusted_authors)
            extra = f"  sandboxTrustedAuthors:\n{items}"
        else:
            extra = "  sandboxTrustedAuthors: []"
    write_trust_config(root, agent_sandbox=tier, self_review="off", extra_lines=extra)


def _resolve(
    tmp_path: Path,
    *,
    tier: str,
    trusted_authors: list[str] | None,
    event: dict[str, Any] | None = None,
    event_name: str = "pull_request_target",
    head_sha: str = _HEAD_SHA,
) -> AgentSandboxDecision:
    _write_config(tmp_path, tier=tier, trusted_authors=trusted_authors)
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    return resolve_agent_sandbox_decision(
        event=event if event is not None else _same_repo_event(head_sha=head_sha),
        event_name=event_name,
        config_root=tmp_path,
        settings_snapshot=snapshot,
        head_sha=head_sha,
        operator_override_requested=True,
    )


@pytest.mark.parametrize("tier", AGENT_SANDBOX_TIERS)
def test_empty_allowlist_is_a_noop_at_every_tier(tmp_path: Path, tier: str) -> None:
    """Empty ``sandboxTrustedAuthors`` (the default) must not change any tier's outcome."""
    event_name, head_sha = "workflow_dispatch", _HEAD_SHA
    event: dict[str, Any] = {
        "repository": {"full_name": "acme/demo", "default_branch": "main"},
        "ref": "refs/heads/feature-branch",
        "head_sha": head_sha,
    }
    baseline = _resolve(
        tmp_path, tier=tier, trusted_authors=None, event=event, event_name=event_name
    )
    explicit_empty = _resolve(
        tmp_path, tier=tier, trusted_authors=[], event=event, event_name=event_name
    )
    assert explicit_empty.honour == baseline.honour
    assert explicit_empty.reason == baseline.reason
    assert explicit_empty.author_gate == "not-configured"
    assert explicit_empty.author_gate_offending_email is None


def test_foreign_author_refuses_at_same_repo(tmp_path: Path) -> None:
    """One commit outside the allowlist refuses the override, even at ``same-repo``."""
    with _mock_git_log([_TRUSTED, _FOREIGN]):
        decision = _resolve(tmp_path, tier="same-repo", trusted_authors=[_TRUSTED])
    assert decision.honour is False
    assert decision.author_gate == "refused"
    assert decision.author_gate_offending_email == _FOREIGN


def test_all_trusted_authors_still_grants(tmp_path: Path) -> None:
    """Every author/committer email on the allowlist — the override is still honoured."""
    with _mock_git_log([_TRUSTED, _ALSO_TRUSTED, _TRUSTED]):
        decision = _resolve(tmp_path, tier="same-repo", trusted_authors=[_TRUSTED, _ALSO_TRUSTED])
    assert decision.honour is True
    assert decision.author_gate == "passed"
    assert decision.author_gate_offending_email is None


def test_fork_floor_still_refuses_even_when_every_author_is_trusted(tmp_path: Path) -> None:
    """The fork floor runs first and wins — an all-trusted commit range does not matter."""
    fork_event = deepcopy(FORK_PULL_REQUEST_EVENT)
    fork_event["pull_request"]["head"]["sha"] = _HEAD_SHA  # type: ignore[index]
    with patch("mergecraft.config.trust_policy.subprocess.run") as run_mock:
        decision = _resolve(
            tmp_path,
            tier="same-repo",
            trusted_authors=[_TRUSTED],
            event=fork_event,
        )
    assert decision.honour is False
    assert "fork" in decision.reason.lower()
    # Fork floor short-circuits before any git range is computed.
    run_mock.assert_not_called()


def test_git_failure_fails_closed(tmp_path: Path) -> None:
    """A ``git log`` failure over the head range refuses, it never falls through to honour."""
    with _mock_git_log(None, returncode=1):
        decision = _resolve(tmp_path, tier="same-repo", trusted_authors=[_TRUSTED])
    assert decision.honour is False
    assert decision.author_gate == "refused"


def test_empty_commit_range_fails_closed(tmp_path: Path) -> None:
    """No commits returned when commits were expected — fail closed, not an empty-range pass."""
    with _mock_git_log([], returncode=0):
        decision = _resolve(tmp_path, tier="same-repo", trusted_authors=[_TRUSTED])
    assert decision.honour is False
    assert decision.author_gate == "refused"


def test_gate_never_grants_what_the_tier_refuses(tmp_path: Path) -> None:
    """Additive-only — an all-trusted range cannot turn a refusing tier into a grant."""
    with _mock_git_log([_TRUSTED]):
        decision = _resolve(
            tmp_path,
            tier="dispatch",
            trusted_authors=[_TRUSTED],
            event=_same_repo_event(),
            event_name="pull_request",  # dispatch only grants on workflow_dispatch
        )
    assert decision.honour is False


def test_manifest_field_populated_when_passed(tmp_path: Path) -> None:
    with _mock_git_log([_TRUSTED]):
        decision = _resolve(tmp_path, tier="same-repo", trusted_authors=[_TRUSTED])
    fields = agent_sandbox_manifest_fields(decision)
    assert fields["agent_sandbox_author_gate"] == "passed"
    assert "agent_sandbox_author_gate_offending_email" not in fields


def test_manifest_field_populated_when_refused(tmp_path: Path) -> None:
    with _mock_git_log([_FOREIGN]):
        decision = _resolve(tmp_path, tier="same-repo", trusted_authors=[_TRUSTED])
    fields = agent_sandbox_manifest_fields(decision)
    assert fields["agent_sandbox_author_gate"] == "refused"
    assert fields["agent_sandbox_author_gate_offending_email"] == _FOREIGN


def test_manifest_field_not_configured_when_allowlist_empty(tmp_path: Path) -> None:
    decision = _resolve(tmp_path, tier="same-repo", trusted_authors=[])
    fields = agent_sandbox_manifest_fields(decision)
    assert fields["agent_sandbox_author_gate"] == "not-configured"
    assert "agent_sandbox_author_gate_offending_email" not in fields


def test_manifest_field_unevaluated_when_tier_already_refuses(tmp_path: Path) -> None:
    """Gate status is 'unevaluated', not 'refused', when the tier itself never honours here."""
    decision = _resolve(
        tmp_path,
        tier="dispatch",
        trusted_authors=[_TRUSTED],
        event=_same_repo_event(),
        event_name="pull_request",
    )
    fields = agent_sandbox_manifest_fields(decision)
    assert fields["agent_sandbox_author_gate"] == "unevaluated"
