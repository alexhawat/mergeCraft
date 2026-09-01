"""W1.4 — Action log group contracts (lane D, green after W6)."""

from __future__ import annotations

import io
import sys
from typing import TYPE_CHECKING

import pytest
from tests.support.run_main_harness import FakeAgent, run_main_for_test

from mergecraft.config.settings import RepoSettings
from mergecraft.utils import gha_log

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

W6_XFAIL = pytest.mark.xfail(
    reason="green after W6: gha_log.group around Action phases",
    strict=True,
)

_GROUP_TITLES = ("setup", "model-chain", "publish")


def _capture_stdout(monkeypatch: MonkeyPatch) -> io.StringIO:
    buffer = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buffer)
    return buffer


def _groups_in_output(text: str, title: str) -> bool:
    return f"::group::{title}" in text and "::endgroup::" in text


@W6_XFAIL
@pytest.mark.asyncio
async def test_main_emits_log_groups_for_setup_model_chain_publish(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """D13 — setup / model-chain / publish phases collapse under GitHub log groups."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    buffer = _capture_stdout(monkeypatch)
    await run_main_for_test(tmp_path, monkeypatch, agent=FakeAgent())
    output = buffer.getvalue()
    for title in _GROUP_TITLES:
        assert _groups_in_output(output, title), f"missing log group for {title!r}"


@W6_XFAIL
@pytest.mark.asyncio
async def test_setup_failure_reason_is_logged_outside_group(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Plan 12 B5 — run-record failure reasons must also appear outside any open group."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    buffer = _capture_stdout(monkeypatch)
    await run_main_for_test(
        tmp_path,
        monkeypatch,
        agent=FakeAgent(),
        setup_script_rc=1,
        setup_script_stderr="setup exploded",
        settings=RepoSettings(setup_script="./broken-setup.sh"),
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
    )
    output = buffer.getvalue()
    assert "setup exploded" in output
    if "::group::setup" in output:
        after_group = output.split("::endgroup::", 1)[-1]
        assert "setup exploded" in after_group


def test_gha_log_group_emits_nothing_without_github_actions(
    monkeypatch: MonkeyPatch,
) -> None:
    """Existing ``gha_log`` contract — no workflow-command noise outside Actions."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    buffer = _capture_stdout(monkeypatch)
    with gha_log.group("setup"):
        sys.stdout.write("plain log line\n")
    assert buffer.getvalue() == "plain log line\n"
