"""Plan S1 — trusted-tier ``setup_script`` failure mode (D5, D6, convention 7, 8).

Contracts:

- D5: a trusted-tier ``setup_script`` non-zero exit produces ``RunOutcome.inconclusive``
  (not ``passed``, not ``configuration_error``). The config was valid; the
  *environment* failed.
- D6: ``setup_hook_failure`` is wired through ``resolve_instructions`` at both
  ``main.py`` call sites so the prompt branch at ``instructions.py:454-458``
  actually fires — the failure reason reaches the reviewing agent.
- Convention 7: stderr reaching the prompt **and** the ``result`` output is
  passed through ``analyzers.redact.redact_secrets`` first.
- Convention 8: trust check at ``main.py:368`` precedes any subprocess spawn;
  untrusted tiers still never execute ``setup_script``.

The five regression pins (5/6/7) must pass today; the four pending tests
(1/2/3/4) surface as natural failures until S1.2 lands.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mergecraft.config.settings import RepoSettings
from mergecraft.run_outcome import RUN_OUTCOME_CONCLUSION, RunOutcome
from tests.support.run_main_harness import run_main_for_test

if TYPE_CHECKING:
    import pytest

# Workflow_dispatch is the canonical trusted-tier event in the suite.
_TRUSTED_EVENT = "workflow_dispatch"
_TRUSTED_PAYLOAD: dict[str, object] = {"action": "workflow_dispatch"}
_FORK_PR_PAYLOAD: dict[str, object] = {
    "action": "opened",
    "pull_request": {"head": {"sha": "deadbeef", "repo": {"fork": True}}},
}


# ── Pending (RED — green after S1.2) ─────────────────────────────────────────


async def test_trusted_setup_script_nonzero_exit_yields_inconclusive(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """D5 — a trusted-tier ``setup_script`` non-zero exit maps to ``inconclusive``.

    Today (pre-S1.2) the run is reported ``passed`` because the warn-only block
    at ``main.py:376-381`` swallows the failure. S1.2 inverts this — the run
    must surface as ``inconclusive`` so an under-provisioned tree never
    receives a review verdict.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
    )
    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    assert rec.tool_context is not None, "main() did not reach ToolContext"
    assert rec.tool_context.trust_tier == "trusted"
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is not None, "MainResult.outcome must be set on a setup-script failure path"
    assert outcome is RunOutcome.inconclusive, (
        f"D5 violation: trusted setup_script non-zero exit mapped to {outcome!r} "
        f"(must be inconclusive, not passed / configuration_error); "
        f"result={rec.result!r}"
    )
    assert not rec.result.success, (
        "inconclusive outcome must surface as a non-success MainResult "
        "(run_succeeded_for_outcome is False for every non-passed value)"
    )


def test_inconclusive_maps_to_neutral_check_conclusion() -> None:
    """Convention 6 / D3 — the existing completion-check conclusion mapping is
    closed: ``RunOutcome.inconclusive`` maps to ``"neutral"``, never
    ``"success"``.

    Convention 6 forbids widening the taxonomy; this test pins the existing
    mapping so a future drift (e.g. a one-letter typo turning ``"neutral"``
    into ``"failure"`` or worse into ``"success"``) is caught immediately.
    """
    assert RunOutcome.inconclusive in RUN_OUTCOME_CONCLUSION
    assert RUN_OUTCOME_CONCLUSION[RunOutcome.inconclusive] == "neutral", (
        "inconclusive must map to 'neutral' for the mergecraft completion check — "
        "no widening of RunOutcome is allowed"
    )
    # And the inverse invariant: only `passed` may ever produce `success`.
    for outcome, conclusion in RUN_OUTCOME_CONCLUSION.items():
        if outcome is RunOutcome.passed:
            assert conclusion == "success", (
                f"{outcome!r} must keep 'success' as the only positive conclusion"
            )
        else:
            assert conclusion in {"failure", "neutral", "timed_out"}, (
                f"{outcome!r} mapped to an unknown / success conclusion {conclusion!r}"
            )


async def test_setup_failure_reason_recorded_on_result_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """D6 / D5 — the structured ``result`` payload carries the redacted
    failure reason.

    The ``result`` JSON is produced by ``cli/gha_cmd.py::_structured_failure_result``,
    which puts the redacted message into ``error.message`` and a stable
    machine-readable code into ``error.code`` (``error_code_for_outcome``).
    When the harness is driven via ``run_main_for_test``, ``MainResult.result``
    carries the same JSON on the GHA success path — but on the failure path
    we drive ``_structured_failure_result`` directly to assert the contract
    without depending on the harness bypass.
    """
    from mergecraft.cli.gha_cmd import _structured_failure_result

    payload = _structured_failure_result(
        RunOutcome.inconclusive, "setup script failed (exit 1): leaked ghp_abcdef0123456789abcdef"
    )
    parsed = json.loads(payload)
    assert parsed["outcome"] == "inconclusive"
    error = parsed["error"]
    assert error["code"] == "mergecraft.inconclusive", (
        f"error.code must be the stable machine-readable outcome; got {error.get('code')!r}"
    )
    assert "ghp_abcdef0123456789abcdef" not in error["message"], (
        f"setup-script stderr carrying a GitHub PAT leaked into result payload: {error['message']!r}"
    )
    assert "[REDACTED]" in error["message"], (
        f"redaction marker missing from result message: {error['message']!r}"
    )
    # And the failure reason itself must still surface (just redacted) — the
    # agent and human reviewer both need to know *something* went wrong.
    assert "setup script failed" in error["message"]


async def test_setup_script_stderr_is_redacted_before_surfacing(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Convention 7 — secrets in setup-script stderr never reach the prompt
    or the ``result`` output.

    The harness drives a trusted-tier setup with a stderr body carrying
    planted GitHub / OpenAI tokens. After the run:
      * ``tool_state.setup_hook_failure`` (set by the impl wave) must not
        contain the raw token bytes;
      * the agent prompt — captured from the live ``resolve_instructions``
        invocation that ``main()`` made — must not contain the raw bytes.
    The ``result`` payload is exercised by test 3 above.
    """
    planted_ghp = "ghp_AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    planted_sk = "sk-abcdefghijklmnopqrstuv1234567890"
    stderr_body = (
        "npm ERR! missing dep\n"
        f"npm ERR! token leaked: {planted_ghp}\n"
        f"npm ERR! openai key: {planted_sk}\n"
    ).encode()

    captured: dict[str, str] = {}

    # Resolve via the undecorated function if present; otherwise call through.
    # We import once and patch the module attribute the impl actually uses.
    import mergecraft.main as main_mod
    import mergecraft.utils.instructions as instructions_mod

    real_resolve = instructions_mod.resolve_instructions

    def _patched_resolve(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        result = real_resolve(*args, **kwargs)
        captured["full"] = getattr(result, "full", "")
        # ``setup_hook_failure`` is NOT a ToolState field yet; the impl wave
        # adds it. Pass the value through as a kwarg override so we exercise
        # the call site that S1.2 wires at ``main.py:500, :560``.
        if kwargs.get("setup_hook_failure"):
            captured["setup_hook_failure"] = str(kwargs["setup_hook_failure"])
        return result

    monkeypatch.setattr(main_mod, "resolve_instructions", _patched_resolve)
    # Also patch the module-level reference in case resolve_instructions is
    # imported into other modules at collection time.
    monkeypatch.setattr(instructions_mod, "resolve_instructions", _patched_resolve)

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="failing-with-tokens"),
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=1,
        setup_script_stderr=stderr_body,
    )
    assert rec.result is not None
    # The captured prompt is what the agent would have seen — assert on it.
    assert captured.get("full"), "resolve_instructions was not invoked by main() during the run"
    prompt = captured["full"]
    assert planted_ghp not in prompt, (
        "GitHub PAT from setup-script stderr leaked into the agent prompt — convention 7 violation"
    )
    assert planted_sk not in prompt, (
        "OpenAI key from setup-script stderr leaked into the agent prompt — convention 7 violation"
    )
    assert "[REDACTED]" in prompt or "[REDACT" in prompt, (
        f"redaction marker missing from prompt — expected at least one "
        f"[REDACTED] marker in a setup-failure paragraph: {prompt[:600]!r}"
    )
    # The run-level outcome is still ``inconclusive`` (D5) — redaction does
    # not change the outcome bucket.
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.inconclusive, f"expected inconclusive (D5), got {outcome!r}"


# ── Regression pins (must pass today) ─────────────────────────────────────────


async def test_trusted_setup_script_zero_exit_still_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Happy-path pin — trusted-tier ``setup_script`` rc 0 keeps the run green.

    Today and after S1.2: a successful setup on a trusted tier must still
    produce ``RunOutcome.passed``. The D5 / D10 contract is about the failure
    path, not this one — S1.2 must not break the happy case.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="echo ok"),
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
        setup_script_rc=0,
    )
    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    assert rec.result.success, (
        f"trusted setup_script rc 0 must remain a passing run; got {rec.result!r}"
    )
    outcome = getattr(rec.result, "outcome", None)
    assert outcome is RunOutcome.passed, f"happy-path outcome must be `passed`; got {outcome!r}"
    assert rec.setup_script_commands == ["echo ok"]


async def test_no_setup_script_configured_is_unaffected(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Baseline pin — no ``setup_script`` (None or unset) leaves the run green.

    The default ``RepoSettings.setup_script`` is ``None``; this test pins that
    a run without an explicit script never spawns a shell and never inherits
    a failure surface.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(),
        event_name=_TRUSTED_EVENT,
        event_payload=_TRUSTED_PAYLOAD,
    )
    assert rec.result is not None
    assert rec.result.success, f"no-setup-script run must succeed: {rec.result!r}"
    assert rec.setup_script_commands == [], (
        f"no setup_script was configured but subprocess was spawned: {rec.setup_script_commands!r}"
    )


async def test_untrusted_tier_never_executes_setup_script(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Convention 8 / W1.2 pin — untrusted events must not execute
    ``setup_script``, even when the script is configured.

    The trust check at ``main.py:368`` precedes every subprocess spawn. S1
    changes what happens *after* the trusted path completes; it must not
    move this gate. This test is the structural anchor — a regression that
    moves the check below the spawn turns this red.
    """
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script="echo repo-controlled-setup"),
        event_name="pull_request",
        event_payload=_FORK_PR_PAYLOAD,
    )
    assert rec.tool_context is not None
    assert rec.tool_context.trust_tier == "untrusted"
    assert rec.setup_script_commands == [], (
        f"untrusted pull_request executed setup_script: {rec.setup_script_commands!r}"
    )
    assert rec.tool_context.tool_state.setup_script_skip_reason == (
        "skipped setup_script on untrusted tier (pull_request event)"
    ), "skip reason must surface on tool_state so the impl wave (F3) can thread it into the prompt"


__all__ = [
    "test_inconclusive_maps_to_neutral_check_conclusion",
    "test_no_setup_script_configured_is_unaffected",
    "test_setup_failure_reason_recorded_on_result_output",
    "test_setup_script_stderr_is_redacted_before_surfacing",
    "test_trusted_setup_script_nonzero_exit_yields_inconclusive",
    "test_trusted_setup_script_zero_exit_still_passes",
    "test_untrusted_tier_never_executes_setup_script",
]
