"""#1009 — an expired Codex login fails over to the Claude backstop.

The Codex rung on a retired subscription login ends as ``infra_error`` and is
deliberately not ``retryable``. It still emits an evidence packet whose verdict
is ``neutral`` (a failed run never yields more), and the backstop decision
treats a ``neutral`` packet or check-run as a posted verdict. The rung's
``failover_eligible`` action output says "this neutral is the infra failure,
not a review", so the backstop is spent. Only failure|success still hold it
back, and without the flag nothing changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.ci.support_self_review_cascade import (
    decide_script,
    evidence_packet,
    run_decide_script,
    step_by_id,
    write_gh_mock,
)
from tests.ci.workflow_support import job, load_workflow

if TYPE_CHECKING:
    from pathlib import Path

_CLAUDE_SCRIPT = decide_script("claude_fallback")


def _env(**overrides: str) -> dict[str, str]:
    env = {
        "OPENCODE_GO_OUTCOME": "failure",
        "CODEX_OUTCOME": "failure",
        "OPENCODE_GO_PACKET": "",
        "CODEX_PACKET": evidence_packet(verdict="neutral"),
        "CODEX_FAILOVER_ELIGIBLE": "true",
    }
    env.update(overrides)
    return env


def test_opencode_without_verdict_and_expired_codex_selects_the_claude_backstop(
    tmp_path: Path,
) -> None:
    outputs, completed = run_decide_script(tmp_path, _CLAUDE_SCRIPT, env=_env())

    assert outputs.get("need") == "true"
    assert "failover-eligible" in completed.stdout


def test_without_the_flag_a_neutral_codex_packet_still_holds_the_backstop(
    tmp_path: Path,
) -> None:
    """Control: the pre-#1009 behaviour is unchanged for an ordinary failure."""
    outputs, _ = run_decide_script(
        tmp_path, _CLAUDE_SCRIPT, env=_env(CODEX_FAILOVER_ELIGIBLE="false")
    )

    assert outputs.get("need") == "false"


@pytest.mark.parametrize("verdict", ["success", "failure"])
def test_a_real_verdict_still_holds_the_backstop_when_failover_eligible(
    tmp_path: Path, verdict: str
) -> None:
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env=_env(CODEX_PACKET=evidence_packet(verdict=verdict)),
    )

    assert outputs.get("need") == "false"


def test_a_neutral_check_run_does_not_hold_the_backstop_when_failover_eligible(
    tmp_path: Path,
) -> None:
    gh_dir = write_gh_mock(tmp_path, check_run_id="444555666", conclusion="neutral")
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env=_env(CODEX_PACKET=""),
        gh_mock_dir=gh_dir,
    )

    assert outputs.get("need") == "true"


def test_the_flag_only_counts_for_the_rung_that_failed(tmp_path: Path) -> None:
    """A stale Codex flag cannot reopen the backstop after Codex succeeded."""
    outputs, _ = run_decide_script(tmp_path, _CLAUDE_SCRIPT, env=_env(CODEX_OUTCOME="success"))

    assert outputs.get("need") == "false"


def test_opencode_go_failover_flag_applies_when_codex_did_not_run(tmp_path: Path) -> None:
    outputs, _ = run_decide_script(
        tmp_path,
        _CLAUDE_SCRIPT,
        env=_env(
            CODEX_OUTCOME="skipped",
            CODEX_PACKET="",
            CODEX_FAILOVER_ELIGIBLE="",
            OPENCODE_GO_PACKET=evidence_packet(verdict="neutral"),
            OPENCODE_GO_FAILOVER_ELIGIBLE="true",
        ),
    )

    assert outputs.get("need") == "true"


def test_the_workflow_wires_both_rungs_flags_into_the_decide_step() -> None:
    """Each rung's flag crosses jobs as an output of the job that ran it."""
    doc = load_workflow("mergecraft.yml")
    env = step_by_id("claude_fallback").get("env") or {}

    assert "needs.review-codex.outputs.codex_failover_eligible" in env["CODEX_FAILOVER_ELIGIBLE"]
    assert (
        "needs.review.outputs.opencode_go_failover_eligible" in env["OPENCODE_GO_FAILOVER_ELIGIBLE"]
    )
    review_outputs = job(doc, "review")["outputs"]
    codex_outputs = job(doc, "review-codex")["outputs"]
    assert (
        "steps.mergecraft_opencode_go.outputs.failover_eligible"
        in review_outputs["opencode_go_failover_eligible"]
    )
    assert (
        "steps.mergecraft_codex.outputs.failover_eligible"
        in codex_outputs["codex_failover_eligible"]
    )
