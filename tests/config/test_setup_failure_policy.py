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
from tests.support.run_main_harness import run_main_for_test

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
    # AND the prompt carries the failure text — D6 wiring.
    assert captured.get("setup_hook_failure"), (
        "setup_hook_failure was never passed to resolve_instructions — "
        "main.py:500 / :560 still hardcode the empty string (D6 violation)"
    )
    prompt = captured["full"]
    assert "SETUP HOOK FAILED" in prompt, (
        "warn path must still inject the SETUP HOOK FAILED section so the "
        "agent knows its environment may be under-provisioned (D6)"
    )
    assert captured["setup_hook_failure"] in prompt, (
        f"setup_hook_failure value did not reach the prompt body; "
        f"captured={captured['setup_hook_failure']!r}"
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


__all__ = [
    "test_invalid_policy_value_fails_closed",
    "test_policy_defaults_to_inconclusive",
    "test_policy_fail_yields_configuration_error",
    "test_policy_warn_reproduces_legacy_continue",
]
