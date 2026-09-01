"""W1.3 env-lane contracts for CI SARIF ingest (lane D, split from W4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.ci.evidence import ci_evidence_findings
from mergecraft.ci.sarif_ingest import ci_wait_inputs_from_env, ingest_ci_sarif_from_action_env
from mergecraft.utils import gha_log
from tests.ci.support_self_review_sarif import (
    ArtifactGitHub,
    head_sha,
    sarif_document,
    tool_context,
    zip_bytes,
)

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_HEAD_SHA = head_sha()


def test_ci_wait_inputs_from_env_returns_none_without_vars(monkeypatch: MonkeyPatch) -> None:
    """D9 — action env lane is a no-op when wait outputs were not forwarded."""
    monkeypatch.delenv("MERGECRAFT_CI_WAIT_STATE", raising=False)
    monkeypatch.delenv("CI_STATE", raising=False)
    assert ci_wait_inputs_from_env() is None


@pytest.mark.parametrize(
    ("state_var", "count_var", "state", "count"),
    [
        ("MERGECRAFT_CI_WAIT_STATE", "MERGECRAFT_CI_FAILED_COUNT", "complete", "2"),
        ("CI_STATE", "CI_FAILED_COUNT", "complete", "1"),
    ],
)
def test_ci_wait_inputs_from_env_reads_action_aliases(
    monkeypatch: MonkeyPatch,
    state_var: str,
    count_var: str,
    state: str,
    count: str,
) -> None:
    """D9 — wait-for-ci outputs may arrive via MERGECRAFT_* or CI_* env aliases."""
    monkeypatch.delenv("MERGECRAFT_CI_WAIT_STATE", raising=False)
    monkeypatch.delenv("CI_STATE", raising=False)
    monkeypatch.delenv("MERGECRAFT_CI_FAILED_COUNT", raising=False)
    monkeypatch.delenv("CI_FAILED_COUNT", raising=False)
    monkeypatch.setenv(state_var, state)
    monkeypatch.setenv(count_var, count)
    assert ci_wait_inputs_from_env() == (state, int(count))


def test_ci_wait_inputs_from_env_invalid_failed_count_defaults_to_zero(
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — non-numeric failed-count env values coerce to zero with a warning."""
    warnings: list[str] = []
    monkeypatch.setattr(gha_log, "warning", lambda msg: warnings.append(msg))
    monkeypatch.setenv("MERGECRAFT_CI_WAIT_STATE", "complete")
    monkeypatch.setenv("MERGECRAFT_CI_FAILED_COUNT", "not-a-number")
    assert ci_wait_inputs_from_env() == ("complete", 0)
    assert warnings


@pytest.mark.asyncio
async def test_ingest_ci_sarif_from_action_env_no_wait_state(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — action env lane returns when wait outputs are absent."""
    monkeypatch.delenv("MERGECRAFT_CI_WAIT_STATE", raising=False)
    monkeypatch.delenv("CI_STATE", raising=False)
    github = ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: zip_bytes("ruff.sarif.json", sarif_document())},
    )
    tool_ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_from_action_env(tool_ctx, {})
    assert not github.head_sha_queries


@pytest.mark.asyncio
async def test_ingest_ci_sarif_from_action_env_no_head_sha(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — action env lane returns when the event has no bound head SHA."""
    monkeypatch.setenv("MERGECRAFT_CI_WAIT_STATE", "complete")
    monkeypatch.setenv("MERGECRAFT_CI_FAILED_COUNT", "0")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    github = ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: zip_bytes("ruff.sarif.json", sarif_document())},
    )
    tool_ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_from_action_env(tool_ctx, {})
    assert not github.head_sha_queries


@pytest.mark.asyncio
async def test_ingest_ci_sarif_from_action_env_ingests_when_forwarded(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D9 — forwarded wait outputs trigger head-SHA SARIF ingest in the action lane."""
    monkeypatch.setenv("MERGECRAFT_CI_WAIT_STATE", "complete")
    monkeypatch.setenv("MERGECRAFT_CI_FAILED_COUNT", "0")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    github = ArtifactGitHub(
        artifacts=[{"id": 7, "name": "ruff-sarif"}],
        archives={7: zip_bytes("ruff.sarif.json", sarif_document())},
    )
    tool_ctx = tool_context(tmp_path, github)
    await ingest_ci_sarif_from_action_env(
        tool_ctx,
        {"pull_request": {"head": {"sha": _HEAD_SHA}}},
    )
    assert github.head_sha_queries == [_HEAD_SHA]
    assert ci_evidence_findings(tool_ctx.tool_state)
