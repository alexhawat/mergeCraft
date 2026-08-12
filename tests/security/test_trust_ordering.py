"""Plan W1 — trust classification precedes any repo-controlled execution.

Contracts (plan wave W1, punch list ``#4``):

- ``derive_trust_tier`` runs immediately after ``resolve_run_context_data`` and
  **before** ``setup_git``, token side effects, and the repo-controlled
  ``setup_script`` (W1.1).
- ``setup_script`` is gated on the derived tier: untrusted events never
  execute it; trusted events keep today's behavior (W1.2).
- Everything between config load and trust classification is re-checked for
  repo-controlled influence (W1.3).

The tests drive the real ``mergecraft.main.main()`` through
``tests/support/run_main_harness.py`` with a scripted shell spawn, so the
recorded event order is the product's own, not a re-implementation's.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.config.settings import RepoSettings
from tests.support.run_main_harness import run_main_for_test

FORK_PR_PAYLOAD: dict[str, Any] = {
    "action": "opened",
    "pull_request": {"head": {"sha": "deadbeef", "repo": {"fork": True}}},
}
SAME_REPO_PR_PAYLOAD: dict[str, Any] = {
    "action": "opened",
    "pull_request": {"head": {"sha": "deadbeef", "repo": {"fork": False}}},
}
PR_TARGET_PAYLOAD: dict[str, Any] = {
    "action": "opened",
    "pull_request": {"head": {"sha": "deadbeef", "repo": {"fork": False}}},
}
DISPATCH_PAYLOAD: dict[str, Any] = {"action": "workflow_dispatch"}

_SETUP_SCRIPT = "echo repo-controlled-setup"


@pytest.mark.parametrize(
    ("event_name", "event_payload", "expected_tier"),
    [
        ("pull_request", FORK_PR_PAYLOAD, "untrusted"),
        ("pull_request_target", PR_TARGET_PAYLOAD, "untrusted"),
        ("workflow_dispatch", DISPATCH_PAYLOAD, "trusted"),
        ("pull_request", SAME_REPO_PR_PAYLOAD, "trusted"),
    ],
    ids=["fork-pr", "pull-request-target", "workflow-dispatch", "same-repo-pr"],
)
async def test_main_derives_expected_tier_for_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    event_name: str,
    event_payload: dict[str, Any],
    expected_tier: str,
) -> None:
    """W1.4(a) — crafted event payloads derive the documented tier."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        event_name=event_name,
        event_payload=event_payload,
    )
    assert rec.tool_context is not None, f"main() did not reach ToolContext: {rec.raised!r}"
    assert rec.tool_context.trust_tier == expected_tier


@pytest.mark.parametrize(
    ("event_name", "event_payload"),
    [
        ("pull_request", FORK_PR_PAYLOAD),
        ("pull_request_target", PR_TARGET_PAYLOAD),
    ],
    ids=["fork-pr", "pull-request-target"],
)
async def test_setup_script_never_runs_on_untrusted_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    event_name: str,
    event_payload: dict[str, Any],
) -> None:
    """W1.2 — repo-controlled setup code must not execute for untrusted events.

    Fails if the gate is deleted: the scripted shell spawn records every
    invocation, so a regression that re-runs ``setup_script`` pre-trust turns
    this red again. Also pins ``tool_state.setup_script_skip_reason``.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script=_SETUP_SCRIPT),
        event_name=event_name,
        event_payload=event_payload,
    )
    assert rec.tool_context is not None, f"main() did not reach ToolContext: {rec.raised!r}"
    assert rec.tool_context.trust_tier == "untrusted"
    assert rec.setup_script_commands == [], (
        f"untrusted {event_name} executed setup_script: {rec.setup_script_commands}"
    )
    assert rec.tool_context.tool_state.setup_script_skip_reason == (
        f"skipped setup_script on untrusted tier ({event_name} event)"
    )


@pytest.mark.parametrize(
    ("event_name", "event_payload"),
    [
        ("workflow_dispatch", DISPATCH_PAYLOAD),
        ("pull_request", SAME_REPO_PR_PAYLOAD),
    ],
    ids=["workflow-dispatch", "same-repo-pr"],
)
async def test_setup_script_still_runs_on_trusted_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    event_name: str,
    event_payload: dict[str, Any],
) -> None:
    """W1.2 — trusted events keep running the configured setup_script."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script=_SETUP_SCRIPT),
        event_name=event_name,
        event_payload=event_payload,
    )
    assert rec.tool_context is not None, f"main() did not reach ToolContext: {rec.raised!r}"
    assert rec.tool_context.trust_tier == "trusted"
    assert rec.setup_script_commands == [_SETUP_SCRIPT]
    assert rec.tool_context.tool_state.setup_script_skip_reason is None


async def test_trust_classification_precedes_repo_controlled_execution(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W1.1 — tier is derived immediately after context resolution.

    The pinned order is: ``resolve_run_context_data`` → ``derive_trust_tier``
    → everything else that can execute repo-controlled code (``setup_git``
    hook surface, ``setup_script`` shell, dependency install).
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script=_SETUP_SCRIPT),
        event_name="pull_request",
        event_payload=SAME_REPO_PR_PAYLOAD,
    )
    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    trust_idx = rec.index("derive_trust_tier")
    assert trust_idx != -1, f"derive_trust_tier never ran: {rec.events}"
    assert trust_idx > rec.index("resolve_run_context_data"), (
        f"trust must come from the resolved run context: {rec.events}"
    )
    for later in ("setup_git", "setup_script", "start_installation"):
        later_idx = rec.index(later)
        assert later_idx == -1 or trust_idx < later_idx, (
            f"{later} ran before trust classification: {rec.events}"
        )


async def test_trust_classification_precedes_token_resolution(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """W1.1 — token resolution side effects happen after classification.

    ``resolve_tokens`` mints credentials; an untrusted event must already be
    classified (and thus gated everywhere downstream) before that happens.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        event_name="pull_request_target",
        event_payload=PR_TARGET_PAYLOAD,
    )
    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    trust_idx = rec.index("derive_trust_tier")
    tokens_idx = rec.index("resolve_tokens")
    assert trust_idx != -1, f"derive_trust_tier never ran: {rec.events}"
    assert tokens_idx != -1, f"resolve_tokens never ran: {rec.events}"
    assert trust_idx < tokens_idx, f"token resolution preceded trust classification: {rec.events}"
