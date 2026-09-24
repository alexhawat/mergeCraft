"""The credential record must describe the chain the run actually executes.

A fallback rung that runs one model used to report every configured entry as a
reviewer slot, including a tail provider it had no credential for — a
degradation line for a slot that was never going to run. The record must follow
the executed chain: a pinned rung reports only its head, and an unpinned rung
reports the genuinely uncredentialed tail at its real slot index.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings import RepoSettings
from mergecraft.utils.agent_resolve import collect_roster_credential_degradations

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_NOUS_TAIL = "nous/tencent/hy3"
_OPENAI_HEAD = "openai/gpt-terra"

# Credential vars any provider in this fixture could read, cleared so the only
# available credential is the one each test sets explicitly.
_CREDENTIAL_ENV = (
    "NOUS_API_KEY",
    "OPENAI_API_KEY",
    "CODEX_AUTH_JSON",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
)


def _settings() -> RepoSettings:
    return RepoSettings.model_validate({"models": [_NOUS_TAIL]})


def _clear_credentials(monkeypatch: MonkeyPatch) -> None:
    for key in _CREDENTIAL_ENV:
        monkeypatch.delenv(key, raising=False)
    # Indexed gateway credentials (`..._0`, `..._1`, …) also count.
    for key in list(_CREDENTIAL_ENV):
        for index in range(4):
            monkeypatch.delenv(f"{key}_{index}", raising=False)


@pytest.mark.xfail(reason="green after SW4.2: pinned rung reports only its head", strict=False)
def test_pinned_rung_reports_no_slot_for_an_uncredentialed_tail(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fixture")
    degradations = collect_roster_credential_degradations(
        settings=_settings(),
        cwd=tmp_path,
        model_head=_OPENAI_HEAD,
        model_pin=True,
    )
    assert degradations == (), (
        "a pinned rung runs only its head model, so a credential-less configured "
        f"tail must not produce a reviewer-slot warning: {degradations!r}"
    )


@pytest.mark.xfail(reason="green after SW4.2: record follows the run chain", strict=False)
def test_unpinned_rung_reports_the_uncredentialed_tail_at_its_slot(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _clear_credentials(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fixture")
    degradations = collect_roster_credential_degradations(
        settings=_settings(),
        cwd=tmp_path,
        model_head=_OPENAI_HEAD,
        model_pin=False,
    )
    assert len(degradations) == 1, (
        "the run chain is [head, configured tail]; only the uncredentialed tail "
        f"should be reported: {degradations!r}"
    )
    line = degradations[0]
    assert "p1" in line, f"the tail is slot p1, not the head's p0: {line!r}"
    assert "nous" in line.lower(), f"the reported provider must be the tail: {line!r}"
    assert all("p0" not in entry for entry in degradations), (
        f"the head model has an OpenAI credential and must not be reported: {degradations!r}"
    )
