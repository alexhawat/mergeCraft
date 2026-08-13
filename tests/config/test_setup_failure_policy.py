"""Plan S1 — ``setupFailurePolicy`` input (D10).

Contracts:

- D10 default is ``inconclusive`` (D5's ``RunOutcome.inconclusive``).
- ``setupFailurePolicy: fail`` → ``RunOutcome.configuration_error`` (the run
  cannot continue with an under-provisioned environment).
- ``setupFailurePolicy: warn`` → today's behaviour: the run continues, but the
  prompt **still** carries the failure text so the agent knows its tree may be
  partially provisioned (D6 — the prompt branch at ``instructions.py:454-458``
  must fire on the warn path too).
- An unknown policy value is a ``configuration_error`` (``extra="forbid"`` on
  the security/runtime config surface — convention 6, plan S3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.config.settings import RepoSettings
from mergecraft.run_outcome import RunOutcome
from tests.support.run_main_harness import FakeAgent, run_main_for_test

if TYPE_CHECKING:
    import pytest

_TRUSTED_EVENT = "workflow_dispatch"
_TRUSTED_PAYLOAD: dict[str, object] = {"action": "workflow_dispatch"}


# ── Pending (RED — green after S1.2) ─────────────────────────────────────────


async def test_policy_defaults_to_inconclusive(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """D10 — input unset → ``setupFailurePolicy`` defaults to ``inconclusive``.

    Today (pre-S1.2): the input does not exist and trusted-tier failures are
    warn-only — this test is RED. After S1.2 the default becomes
    ``inconclusive``, matching D5.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        env={"GITHUB_EVENT_NAME": _TRUSTED_EVENT},
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is not None, "MainResult.outcome must be set"
    assert outcome is RunOutcome.inconclusive, (
        f"D10 default violated: unset setupFailurePolicy must yield inconclusive, "
        f"got {outcome!r} (result={rec.result!r})"
    )


async def test_policy_fail_yields_configuration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """D10 — ``setupFailurePolicy: fail`` → ``RunOutcome.configuration_error``.

    Operators that opt into the hard-fail path get a different bucket than
    the default — the run is configurationally rejected, not just inconclusive,
    because the consumer has explicitly declared the failure is unrecoverable.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(
            setup_script="./broken-setup.sh",
            # ``setup_failure_policy`` is a NEW field; the impl wave adds it.
            # Pydantic will accept unknown keys for ``RepoSettings`` if its
            # model_config switches — but ``RepoSettings`` is
            # ``extra="forbid"`` today, so model_validate will reject it.
            # We use ``model_construct`` to side-step validation for the test:
            # the impl wave switches the field on for real.
        ),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_SETUP_FAILURE_POLICY": "fail",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is not None
    assert outcome is RunOutcome.configuration_error, (
        f"D10 `fail` policy violated: expected configuration_error, got {outcome!r}"
    )
    assert not rec.result.success


async def test_policy_warn_reproduces_legacy_continue(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """D10 — ``setupFailurePolicy: warn`` keeps today's continue-on-failure
    behaviour AND threads the failure text into the prompt (D6).

    The prompt assertion is the load-bearing pin: even on the warn path,
    the agent must know its environment failed to provision. Today's code
    hardcodes ``setup_hook_failure=""`` at both call sites
    (``main.py:500, :560``), so the prompt branch at
    ``instructions.py:454-458`` cannot fire — S1.2 fixes that.
    """
    captured: dict[str, str] = {}

    import mergecraft.main as main_mod
    import mergecraft.utils.instructions as instructions_mod

    real_resolve = instructions_mod.resolve_instructions

    def _patched_resolve(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        result = real_resolve(*args, **kwargs)
        captured["full"] = getattr(result, "full", "")
        # S1 review follow-up — capture the surface the runtime drivers
        # actually send to the model (``instructions.system``) so the
        # test asserts on the field that reaches the agent, not the
        # structurally-dead ``full`` field.
        captured["system"] = getattr(result, "system", "")
        if kwargs.get("setup_hook_failure"):
            captured["setup_hook_failure"] = str(kwargs["setup_hook_failure"])
        return result

    monkeypatch.setattr(main_mod, "resolve_instructions", _patched_resolve)
    monkeypatch.setattr(instructions_mod, "resolve_instructions", _patched_resolve)

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_SETUP_FAILURE_POLICY": "warn",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None
    # Warn path: the run continues (today's behaviour).
    assert rec.result.success, (
        f"D10 `warn` policy must reproduce today's continue-on-failure; got {rec.result!r}"
    )
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.passed, (
        f"D10 `warn` policy: outcome must be `passed` (run continues); got {outcome!r}"
    )
    # AND the prompt carries the failure text — D6 wiring. The driver
    # only sends ``instructions.system``, so assert on that surface too.
    assert captured.get("setup_hook_failure"), (
        "setup_hook_failure was never passed to resolve_instructions — "
        "main.py:500 / :560 still hardcode the empty string (D6 violation)"
    )
    for surface_name, surface_key in (("full", "full"), ("system", "system")):
        prompt = captured[surface_key]
        assert "SETUP HOOK FAILED" in prompt, (
            f"warn path must inject the SETUP HOOK FAILED section on the "
            f"{surface_name!r} surface so the agent knows its environment "
            f"may be under-provisioned (D6) — drivers only read system"
        )
        assert captured["setup_hook_failure"] in prompt, (
            f"setup_hook_failure value did not reach the {surface_name!r} "
            f"surface; captured={captured['setup_hook_failure']!r}"
        )


async def test_policy_fail_aborts_before_agent_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 review / F4 follow-up — ``setupFailurePolicy: fail`` must abort the
    run *before* the agent executes.

    Today the ``fail`` policy is enforced only in the post-run outcome
    resolution block — after the agent runs. The agent may already have
    posted reviews, pushed branches, or made other external mutations by
    the time the run is mapped to ``configuration_error``. The S1 review
    flagged this as violating the documented "run aborts" semantics. The
    fix raises ``_ConfigurationError`` immediately after the setup-script
    block (before the agent loop) when the policy is ``fail`` and setup
    failed.
    """
    from mergecraft.agents.shared import AgentResult

    sentinel_agent = FakeAgent(
        name="claude",
        result=AgentResult(success=True, output="must-not-run"),
    )

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_SETUP_FAILURE_POLICY": "fail",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
        agents_by_slug={"claude": sentinel_agent},
    )
    assert rec.result is not None
    # The agent must NEVER have been invoked — its only purpose in this
    # test is to record invocations so the assertion can prove the
    # short-circuit is in place.
    assert sentinel_agent.calls == [], (
        f"F4 follow-up violated: agent ran {len(sentinel_agent.calls)} "
        f"times under setupFailurePolicy=fail — must be 0. The fail policy "
        f"must abort before the agent loop, not after."
    )
    # The outcome should still be configuration_error so the operator's
    # intent is preserved.
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.configuration_error, (
        f"setupFailurePolicy=fail must yield configuration_error; got {outcome!r}"
    )
    # S1 review / NEW2 — the F4 fail-policy short-circuit raises while
    # ``tool_context`` is already built. The outer handler therefore has
    # a context to call ``report_status_checks`` on, and the harness
    # records that call.
    assert rec.report_status_calls, (
        f"NEW2 violated: F4 fail-policy guard raised but the outer "
        f"handler did not call report_status_checks — tool_context was "
        f"None when the guard raised; report_status_calls={rec.report_status_calls!r}"
    )
    last = rec.report_status_calls[-1]
    assert last.get("failure_reason"), (
        f"NEW2 violated: report_status_checks was called without a failure_reason; got {last!r}"
    )


async def test_setup_failure_shortcircuits_before_agent_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 review — ``inconclusive``/``fail`` setup failure must not run the agent.

    A Review agent must never be dispatched (and thus cannot submit a GitHub
    review) when the outcome is already decided by the setup failure policy.
    Only ``warn`` proceeds to the agent.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_SETUP_FAILURE_POLICY": "fail",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.configuration_error
    assert rec.agent_runs == [], (
        f"agent must not be dispatched on a fail-policy setup failure; ran {rec.agent_runs!r}"
    )


async def test_setup_failure_inconclusive_shortcircuits_before_agent_dispatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 review — the default ``inconclusive`` policy also short-circuits."""
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.inconclusive
    assert rec.agent_runs == [], (
        f"agent must not be dispatched on an inconclusive setup failure; ran {rec.agent_runs!r}"
    )


async def test_invalid_policy_value_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Unknown ``setupFailurePolicy`` value is a ``configuration_error``.

    The policy is a security/runtime surface (the run's outcome depends on
    it). It must be validated under ``extra="forbid"`` semantics: a typo
    cannot silently land on the default branch — that would be exactly the
    S3 fail-open shape S1 must not introduce.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_SETUP_FAILURE_POLICY": "definitely-not-a-policy",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is not None
    assert outcome is RunOutcome.configuration_error, (
        f"invalid setupFailurePolicy must fail closed; got {outcome!r}"
    )
    assert not rec.result.success


async def test_invalid_setup_failure_policy_does_not_spawn_setup_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 review / NEW1 — invalid ``setupFailurePolicy`` rejects BEFORE setup runs.

    The prior fix captured the ``ValueError`` into a sentinel and re-raised
    it after ``tool_state`` was constructed — that meant the setup script
    could still start executing and run for up to its full budget before
    the configuration error fired. This test pins the NEW1 fix:
    ``apply_setup_overrides`` (and the other input validators) now raise
    ``_ConfigurationError`` *before* ``asyncio.create_subprocess_shell`` is
    ever called for the setup script.

    The test uses the harness's own monkeypatch on
    ``asyncio.create_subprocess_shell`` and asserts ``rec.setup_script_commands``
    is empty — no subprocess was spawned, regardless of how the policy
    string would otherwise have routed the run.
    """
    import asyncio

    spawn_calls: list[tuple[str, object]] = []
    real_create_subprocess_shell = asyncio.create_subprocess_shell

    async def _counting_create_subprocess_shell(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        # Record the call site so the assertion can prove the
        # configuration-error guard fired *before* the spawn, not after.
        spawn_calls.append((str(args[0]) if args else "", kwargs))
        return await real_create_subprocess_shell(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _counting_create_subprocess_shell)

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="echo would-have-run"),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_SETUP_FAILURE_POLICY": "bogus",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None
    # The harness records each call to ``asyncio.create_subprocess_shell``
    # on ``rec.setup_script_commands``. The NEW1 fix means the invalid
    # policy raises ``_ConfigurationError`` *before* the setup block runs.
    assert rec.setup_script_commands == [], (
        f"NEW1 violated: setup_script was spawned despite an invalid "
        f"setup_failure_policy; spawn_calls={spawn_calls!r}, "
        f"setup_script_commands={rec.setup_script_commands!r}"
    )
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.configuration_error, (
        f"invalid setupFailurePolicy must fail closed as configuration_error; got {outcome!r}"
    )


async def test_invalid_setup_timeout_does_not_spawn_setup_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 review / NEW1 — invalid ``INPUT_SETUP_TIMEOUT`` rejects BEFORE setup runs.

    Same contract as ``test_invalid_setup_failure_policy_does_not_spawn_setup_script``
    but for the ``setup_timeout`` input: an unparseable duration must fail
    closed *before* the setup script is spawned. The fix moves
    ``apply_setup_overrides`` (and the timeout parsing in
    ``main.py``) above ``setup_git`` and the ``asyncio.create_subprocess_shell``
    call.
    """
    import asyncio

    spawn_calls: list[tuple[str, object]] = []
    real_create_subprocess_shell = asyncio.create_subprocess_shell

    async def _counting_create_subprocess_shell(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        spawn_calls.append((str(args[0]) if args else "", kwargs))
        return await real_create_subprocess_shell(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _counting_create_subprocess_shell)

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="echo would-have-run"),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_SETUP_TIMEOUT": "not-a-duration",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None
    assert rec.setup_script_commands == [], (
        f"NEW1 violated: setup_script was spawned despite an invalid "
        f"setup_timeout; spawn_calls={spawn_calls!r}"
    )
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.configuration_error, (
        f"invalid INPUT_SETUP_TIMEOUT must fail closed as configuration_error; got {outcome!r}"
    )


async def test_invalid_run_timeout_does_not_spawn_setup_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 review / NEW1 — invalid ``INPUT_TIMEOUT`` rejects BEFORE setup runs.

    Third member of the NEW1 family. The action-input ``timeout`` parses
    through ``resolve_timeout_ms``; an unparseable value must raise
    ``_ConfigurationError`` immediately, before the setup script starts.
    """
    import asyncio

    spawn_calls: list[tuple[str, object]] = []
    real_create_subprocess_shell = asyncio.create_subprocess_shell

    async def _counting_create_subprocess_shell(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        spawn_calls.append((str(args[0]) if args else "", kwargs))
        return await real_create_subprocess_shell(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_shell", _counting_create_subprocess_shell)

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="echo would-have-run"),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_TIMEOUT": "not-a-duration",
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None
    assert rec.setup_script_commands == [], (
        f"NEW1 violated: setup_script was spawned despite an invalid "
        f"run timeout; spawn_calls={spawn_calls!r}"
    )
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.configuration_error, (
        f"invalid INPUT_TIMEOUT must fail closed as configuration_error; got {outcome!r}"
    )


async def test_inconclusive_policy_skips_agent_but_yields_inconclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 review / N2 — ``setupFailurePolicy: inconclusive`` (default) must
    short-circuit the agent loop AND land the run as ``inconclusive``.

    Pre-N2 the default ``inconclusive`` policy only resolved at the late
    outcome block *after* the agent had run. The agent could post a
    review, push a branch, or invoke mutation tools before being told the
    run would be marked no-verdict. The N2 fix: the helper
    :func:`mergecraft.main._short_circuit_setup_failure` returns
    ``("skip_agent", reason)`` for ``inconclusive``; ``main`` returns a
    ``MainResult(outcome=RunOutcome.inconclusive)`` immediately,
    bypassing the agent loop entirely.

    Asserts:

    1. ``sentinel_agent.calls == []`` — the agent was never invoked.
    2. ``outcome is RunOutcome.inconclusive`` — the documented contract.
    3. ``report_status_checks`` was called with the ``inconclusive``
       conclusion so the consumer repo's status check fires.
    """
    from mergecraft.agents.shared import AgentResult

    sentinel_agent = FakeAgent(
        name="claude",
        result=AgentResult(success=True, output="must-not-run"),
    )

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        # ``setup_failure_policy`` defaults to ``inconclusive`` — this
        # test pins the default, so leaving it implicit documents the
        # contract for operators who do NOT set the action input.
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        env={"GITHUB_EVENT_NAME": _TRUSTED_EVENT},
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
        agents_by_slug={"claude": sentinel_agent},
    )
    # (1) the agent must NEVER have been invoked.
    assert sentinel_agent.calls == [], (
        f"N2 violated: agent ran {len(sentinel_agent.calls)} times under "
        f"the default setupFailurePolicy=inconclusive — must be 0. The "
        f"inconclusive policy must skip the agent loop, not run it and "
        f"then rewrite the outcome."
    )
    # (2) outcome is ``inconclusive`` (the documented contract).
    assert rec.result is not None
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.inconclusive, (
        f"N2 violated: inconclusive policy must yield RunOutcome.inconclusive; got {outcome!r}"
    )
    # (3) the publish block still runs — ``report_status_checks`` is the
    # consumer-facing surface; skipping it would leave the run without a
    # status check.
    assert rec.report_status_calls, (
        "N2 violated: inconclusive skip-path must still call "
        "report_status_checks so the consumer repo's status check fires; "
        f"report_status_calls={rec.report_status_calls!r}"
    )
    # The agent did not run, so the run is *not* a success.
    assert not rec.result.success


async def test_inconclusive_policy_does_not_invoke_review_or_mutation_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 review / N2 — review / mutation MCP tools must NOT fire under
    ``inconclusive`` policy.

    The review / mutation surface is the MCP server the agent talks to
    (``post_review``, ``push_branch``, etc.). Under the inconclusive
    skip-path the agent loop never executes, so no MCP tool is ever
    invoked — and the MCP server itself is not started, because the
    short-circuit returns before :func:`start_mcp_http_server` is
    called. The publish block uses ``tool_context`` directly, not the
    MCP transport, so the server is not needed on this path.

    The harness's :class:`FakeAgent` records each invocation in
    ``sentinel_agent.calls``; ``start_mcp_http_server`` is patched
    here to record every call. A regression that re-introduces the
    "agent runs first, outcome rewritten later" shape would surface
    here as either a non-empty ``sentinel_agent.calls`` or a
    non-empty ``mcp_starts`` (the agent-side surface would be live).
    """
    from mergecraft.agents.shared import AgentResult

    sentinel_agent = FakeAgent(
        name="claude",
        result=AgentResult(success=True, output="must-not-run"),
    )
    mcp_starts: list[str] = []

    async def _tracking_mcp_server(tool_context, **_kwargs):  # type: ignore[no-untyped-def]
        tool_context.mcp_server_url = "http://127.0.0.1:0/mcp"
        mcp_starts.append("started")
        return "http://127.0.0.1:0/mcp", lambda: None

    monkeypatch.setattr("mergecraft.main.start_mcp_http_server", _tracking_mcp_server)

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        env={"GITHUB_EVENT_NAME": _TRUSTED_EVENT},
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
        agents_by_slug={"claude": sentinel_agent},
    )
    assert rec.result is not None
    # The agent must never have been invoked — that's the load-bearing
    # assertion: with no agent run, no review / mutation MCP tool can be
    # called (those tools are agent-side).
    assert sentinel_agent.calls == [], (
        f"N2 violated: agent ran {len(sentinel_agent.calls)} times under "
        f"the inconclusive policy — must be 0 (no review / mutation tool can "
        f"fire without an agent run)"
    )
    # The MCP server also was not started — the short-circuit returns
    # *before* ``start_mcp_http_server``. That's the strongest possible
    # proof the agent-side tool surface was never reachable: not just
    # "no tool calls were made" but "the server didn't even come up".
    assert mcp_starts == [], (
        f"N2 violated: MCP server started under the inconclusive skip-path; "
        f"mcp_starts={mcp_starts!r}. The short-circuit must return before "
        f"start_mcp_http_server is called — otherwise the agent-side tool "
        f"surface is reachable."
    )
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.inconclusive, (
        f"N2 violated: outcome must be inconclusive; got {outcome!r}"
    )


async def test_empty_action_default_lets_yaml_win(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """S1 review / N1 — empty ``INPUT_SETUP_FAILURE_POLICY`` (the new
    action metadata default) is treated as unset.

    Pre-N1, ``action.yml`` shipped with ``default: "inconclusive"``,
    which GitHub Actions always injects. The documented "action input
    > YAML > default" precedence therefore collapsed to "action input
    always wins" on real runs — an operator who set
    ``setupFailurePolicy: warn`` in YAML got ``inconclusive`` because
    the action metadata overwrote it.

    The N1 fix flips ``action.yml`` to ``default: ""``; this test pins
    the action-metadata path: when the input is the empty string, the
    YAML's ``setup_failure_policy`` survives, and the run does NOT
    short-circuit (warn policy under a setup failure lets the agent
    run, matching today's documented behaviour).
    """
    # Set ``setup_failure_policy="warn"`` in YAML; inject the new empty
    # action-metadata default into the runtime; ensure the run still
    # continues (warn policy, agent runs).
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(
            setup_script="./broken-setup.sh",
            setup_failure_policy="warn",
        ),
        env={
            "GITHUB_EVENT_NAME": _TRUSTED_EVENT,
            "INPUT_SETUP_FAILURE_POLICY": "",  # the new action.yml default
        },
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None
    # Warn policy → run continues (the YAML layer won over the empty
    # action input). Outcome is ``passed`` because the agent produced a
    # successful result and the warn policy does not rewrite.
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.passed, (
        f"N1 violated: warn policy under empty INPUT_SETUP_FAILURE_POLICY "
        f"must let YAML win and continue the run; got {outcome!r}. "
        f"Pre-N1 the action.yml default 'inconclusive' would have "
        f"overwritten YAML here."
    )
    assert rec.result.success


__all__ = [
    "test_empty_action_default_lets_yaml_win",
    "test_inconclusive_policy_does_not_invoke_review_or_mutation_tools",
    "test_inconclusive_policy_skips_agent_but_yields_inconclusive",
    "test_invalid_policy_value_fails_closed",
    "test_policy_defaults_to_inconclusive",
    "test_policy_fail_aborts_before_agent_runs",
    "test_policy_fail_yields_configuration_error",
    "test_policy_warn_reproduces_legacy_continue",
    "test_setup_failure_inconclusive_shortcircuits_before_agent_dispatch",
    "test_setup_failure_shortcircuits_before_agent_dispatch",
]
