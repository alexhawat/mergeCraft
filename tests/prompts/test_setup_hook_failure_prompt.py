"""Plan S1 — ``setup_hook_failure`` and ``setup_script_skip_reason`` reach the prompt (F1, F3).

Contracts:

- F1: ``setup_hook_failure`` is wired through ``resolve_instructions`` at both
  ``main.py`` call sites. The prompt branch at ``instructions.py:454-458``
  renders when the value is non-empty.
- F3: ``tool_state.setup_script_skip_reason`` is threaded into the prompt
  assembly (S1.2 adds the parameter). The agent must be told the script was
  skipped, and why.

Both branches use the same render shape as today — the existing
``setup_hook_failure`` branch at ``instructions.py:454-458`` (D6 wiring).
The new ``skip_reason`` branch is a sibling paragraph in S1.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.config.settings import RepoInfo, RepoSettings
from mergecraft.modes import Mode
from mergecraft.utils.instructions import resolve_instructions
from tests.support.run_main_harness import FakeAgent, run_main_for_test

if TYPE_CHECKING:
    from typing import Any

    import pytest


# ── Shared fixtures / helpers ────────────────────────────────────────────────


def _basic_payload() -> dict[str, object]:
    """Minimal payload that resolves to a populated prompt assembly."""
    return {
        "~mergecraft": True,
        "prompt": "review this",
        "shell": "restricted",
        "push": "restricted",
        "event": {
            "trigger": "pull_request_opened",
            "is_pr": True,
            "issue_number": 42,
            "title": "Add feature",
            "body": "",
            "author": "alice",
        },
        "model": "anthropic/claude-sonnet",
    }


def _repo() -> RepoInfo:
    return RepoInfo(owner="acme", name="widgets", data={"default_branch": "main"})


def _modes() -> list[Mode]:
    return [Mode(name="Review", description="Review", prompt="do")]


def _patch_resolve_for_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Patch ``resolve_instructions`` to capture the rendered prompt.

    Returns a dict the test can read; ``captured["full"]`` holds the
    last-rendered ``ResolvedInstructions.full``, ``captured["all_full"]``
    is a list of every prompt built (primary + retry paths).
    """
    captured: dict[str, Any] = {"full": "", "all_full": []}

    import mergecraft.main as main_mod
    import mergecraft.utils.instructions as instructions_mod

    real_resolve = instructions_mod.resolve_instructions

    def _patched_resolve(*args: Any, **kwargs: Any) -> Any:
        result = real_resolve(*args, **kwargs)
        full = getattr(result, "full", "")
        captured["full"] = full
        captured["all_full"].append(full)
        return result

    monkeypatch.setattr(main_mod, "resolve_instructions", _patched_resolve)
    monkeypatch.setattr(instructions_mod, "resolve_instructions", _patched_resolve)
    # S1/S3/S5 split (commit 4e8f420+): the inner-loop ``resolve_instructions``
    # call now lives in ``mergecraft.main_agent``. Patch that binding too so the
    # fallback retry (which loops through ``_run_agent_once``) is captured by
    # the test's wrapper.
    from mergecraft import main_agent as main_agent_mod

    monkeypatch.setattr(main_agent_mod, "resolve_instructions", _patched_resolve)
    return captured


# ── Pending (RED — green after S1.2) ─────────────────────────────────────────


def test_setup_hook_failure_branch_is_reachable() -> None:
    """F1 — ``resolve_instructions(setup_hook_failure="boom")`` renders the
    prompt branch at ``instructions.py:454-458``.

    Today the parameter exists but the call sites at ``main.py:500, :560``
    hardcode the empty string — so the branch is structurally reachable but
    functionally dead. After S1.2, the call sites pass the value through.

    The test calls the function directly with the param, which makes the
    branch render today (the param is real). This pins the rendered shape.
    """
    resolved = resolve_instructions(
        payload=_basic_payload(),
        repo=_repo(),
        modes=_modes(),
        agent_id="claude",
        setup_hook_failure="setup script failed (exit 1): boom",
    )
    prompt = resolved.full
    assert "SETUP HOOK FAILED" in prompt, (
        "F1 violation: setup_hook_failure did not render the prompt branch "
        "at instructions.py:454-458 — the param is accepted but the branch "
        "is not being emitted, or the section heading was renamed"
    )
    assert "setup script failed (exit 1): boom" in prompt, (
        "setup_hook_failure text must reach the prompt body verbatim so the agent knows what failed"
    )


async def test_skip_reason_reaches_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """F3 — ``tool_state.setup_script_skip_reason`` reaches the prompt.

    The impl wave adds a new parameter ``setup_script_skip_reason`` to
    ``resolve_instructions``. Today the parameter does not exist, so the
    prompt cannot carry the skip paragraph — that is the RED signal.

    The test drives ``main()`` through the harness with an untrusted event
    so the production code sets ``tool_state.setup_script_skip_reason``.
    The harness wraps ``resolve_instructions`` to capture the rendered
    prompt. After S1.2, the prompt must contain the skip paragraph;
    today it does not (the test fails on the assertion, not on a
    ``TypeError``).
    """
    captured = _patch_resolve_for_capture(monkeypatch)

    # Untrusted pull_request → tool_state.setup_script_skip_reason is set
    # at main.py:387 today. The harness drives the real event path.
    untrusted_event = "pull_request"
    untrusted_payload: dict[str, object] = {
        "action": "opened",
        "pull_request": {"head": {"sha": "deadbeef", "repo": {"fork": True}}},
    }
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="echo repo-controlled"),
        event_name=untrusted_event,
        event_payload=untrusted_payload,
    )
    assert rec.result is not None
    assert captured["full"], "resolve_instructions was not invoked by main() during the run"
    prompt = captured["full"]
    skip_reason = "skipped setup_script on untrusted tier (pull_request event)"
    assert skip_reason in prompt, (
        f"F3 violation: setup_script_skip_reason text did not reach the "
        f"prompt body; agent has no way to know the setup was skipped. "
        f"Prompt first 500 chars: {prompt[:500]!r}"
    )
    # The skip paragraph should be a distinct, named section — not a bare
    # paragraph mid-prompt — so the agent can tell it apart from the
    # setup-failure paragraph.
    assert "SETUP SCRIPT SKIPPED" in prompt, (
        "skip reason must surface in a clearly-named section, mirroring the "
        "SETUP HOOK FAILED section's structural pattern"
    )


async def test_both_call_sites_pass_the_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """F1 / D6 structural pin — **the prompt built by both call paths**
    contains the failure reason.

    The plan mandates that the prompt built by both the primary path
    (``main.py:500``) and the retry/fallback path (``main.py:560``) carries
    the reason. Today both call sites hardcode ``setup_hook_failure=""``;
    S1.2 fixes both.

    The assertion is on the *built prompt*, NOT on the absence of `""` in
    the source. A source-grep is structural-only and the wave-verifier will
    reject it.

    The test drives a model chain (``models=["claude", "opencode"]``) so
    both call sites fire — the primary at ``main.py:500`` and the
    fallback at ``main.py:560`` (which is only reached when
    ``attempt_agent_id != agent_id``). The harness's
    ``agents_by_slug`` maps each slug to a ``FakeAgent``.
    """
    from mergecraft.agents.shared import AgentResult

    captured = _patch_resolve_for_capture(monkeypatch)

    trusted_event = "workflow_dispatch"
    trusted_payload: dict[str, object] = {"action": "workflow_dispatch"}
    head_agent = FakeAgent(
        name="claude",
        # ``retryable=True`` so the production chain advances to the fallback
        # slug; the test's whole point is to exercise both ``resolve_instructions``
        # call sites, which only happens when ``attempt_agent_id != agent_id``.
        result=AgentResult(success=False, error="primary failed", metadata={"retryable": True}),
    )
    fallback_agent = FakeAgent(
        name="opencode",
        result=AgentResult(success=True, output="fallback-output"),
    )
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(
            setup_script="./broken-setup.sh",
            models=["claude", "opencode"],
            setup_failure_policy="warn",  # must be "warn" so the short-circuit does not intercept
        ),
        event_name=trusted_event,
        event_payload=trusted_payload,
        setup_script_rc=1,
        agents_by_slug={"claude": head_agent, "opencode": fallback_agent},
    )
    assert rec.result is not None

    # Both call sites in main.py:500 / :560 call resolve_instructions once
    # each. Today both hardcode setup_hook_failure="" — so the captured
    # prompts will NOT contain "SETUP HOOK FAILED" in either case.
    # After S1.2, both must.
    assert captured["all_full"], "resolve_instructions was never called by main()"
    assert len(captured["all_full"]) >= 2, (
        f"F1 structural pin: expected both main.py:500 and :560 to call "
        f"resolve_instructions; got {len(captured['all_full'])} calls — "
        f"the fallback path was not exercised"
    )
    failure_paragraph_count = sum(
        1 for prompt in captured["all_full"] if "SETUP HOOK FAILED" in prompt
    )
    assert failure_paragraph_count == len(captured["all_full"]), (
        f"F1 / D6 wiring: only {failure_paragraph_count}/"
        f"{len(captured['all_full'])} built prompts carried the SETUP HOOK "
        f"FAILED paragraph — at least one call site is still hardcoding "
        f'setup_hook_failure="" (main.py:500 or :560)'
    )


# ── Regression pins (must pass today) ─────────────────────────────────────────


def test_setup_hook_failure_empty_omits_branch() -> None:
    """Pin — ``setup_hook_failure=""`` (today's hardcoded default) keeps the
    branch absent.

    The empty string must NOT inject the failure paragraph into the prompt.
    Today this is the only path actually exercised; S1.2 keeps this as the
    no-failure baseline.
    """
    resolved = resolve_instructions(
        payload=_basic_payload(),
        repo=_repo(),
        modes=_modes(),
        agent_id="claude",
        setup_hook_failure="",
    )
    assert "SETUP HOOK FAILED" not in resolved.full, (
        "empty setup_hook_failure must not inject the failure branch — the "
        "no-failure baseline is the regression pin"
    )


def test_skip_reason_absent_omits_branch() -> None:
    """Pin — when ``setup_script_skip_reason`` is absent, no skip paragraph
    appears in the prompt.

    Today the parameter doesn't exist; the test calls the function without
    it (the impl wave adds it with a default of ``None``/empty). Either way,
    the rendered prompt must not contain a skip paragraph.
    """
    resolved = resolve_instructions(
        payload=_basic_payload(),
        repo=_repo(),
        modes=_modes(),
        agent_id="claude",
    )
    assert "SETUP SCRIPT SKIPPED" not in resolved.full, (
        "absent setup_script_skip_reason must not inject the skip branch — "
        "the no-skip baseline is the regression pin"
    )


__all__ = [
    "test_both_call_sites_pass_the_reason",
    "test_setup_hook_failure_branch_is_reachable",
    "test_setup_hook_failure_empty_omits_branch",
    "test_skip_reason_absent_omits_branch",
    "test_skip_reason_reaches_prompt",
]
