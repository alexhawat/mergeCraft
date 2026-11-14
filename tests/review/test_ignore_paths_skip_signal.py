"""An all-ignored pull request through ``main()``: the signal the review gate reads.

The required ``mergecraft review`` gate passes a pull request whose every changed file
is ignored by the review ignore paths, and only that one, on a ``neutral`` verdict. It
learns the reason from this run's own evidence packet: ``decision.verdict`` is
``neutral`` and ``triage`` records ``tier=skip`` with ``recognizer=ignorePaths``. The
``mergecraft-approval`` check the gate corroborates against is ``neutral`` and bound to
this run's ``<run id>:<attempt>``. A partially ignored pull request carries no such
triage record, so its neutral (if any) keeps failing the gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import mergecraft.main as main_mod
from tests.support.run_main_harness import FakeAgent, run_main_for_test

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_HEAD = "c" * 40
_RUN_ID = "4242"
_RUN_ATTEMPT = "3"

_EVENT: dict[str, Any] = {
    "action": "synchronize",
    "number": 1444,
    "pull_request": {
        "number": 1444,
        "title": "docs(changelog): note the release",
        "body": "",
        "head": {
            "ref": "docs/changelog",
            "sha": _HEAD,
            "repo": {"full_name": "acme/demo", "fork": False},
        },
        "base": {"ref": "main", "sha": "b" * 40, "repo": {"full_name": "acme/demo"}},
    },
    "repository": {"full_name": "acme/demo", "owner": {"login": "acme"}, "name": "demo"},
}


def _listing(monkeypatch: pytest.MonkeyPatch, paths: list[str]) -> list[int]:
    """Answer the pull request file listing; the SCM fake has no ``/files`` route."""
    calls: list[int] = []

    async def _paths(
        _scm: Any, _owner: str, _repo: str, number: int, **_identity: Any
    ) -> list[str]:
        calls.append(number)
        return list(paths)

    monkeypatch.setattr(main_mod, "list_pull_request_paths", _paths)
    return calls


async def _run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, agent: FakeAgent) -> Any:
    return await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        event_name="pull_request_target",
        event_payload=_EVENT,
        env={"GITHUB_RUN_ID": _RUN_ID, "GITHUB_RUN_ATTEMPT": _RUN_ATTEMPT},
        agent=agent,
        capture_status_checks=True,
    )


async def test_an_all_ignored_pr_records_the_ignore_reason_on_a_neutral_packet(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    listed = _listing(monkeypatch, ["CHANGELOG.md", "uv.lock"])
    agent = FakeAgent()

    rec = await _run(monkeypatch, tmp_path, agent)

    assert rec.raised is None, rec.raised
    assert listed == [1444]
    assert agent.calls == [], "an all-ignored pull request makes no LLM call"
    packet = rec.report_status_calls[-1]["packet"]
    assert packet.decision.verdict == "neutral"
    assert packet.triage is not None
    assert (packet.triage.tier, packet.triage.recognizer) == ("skip", "ignorePaths")
    assert "all 2 changed file(s) are ignored" in packet.triage.reason


async def test_the_neutral_approval_check_is_bound_to_this_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The gate's corroboration filter (head, issuer, external id) still applies."""
    _listing(monkeypatch, ["CHANGELOG.md"])

    rec = await _run(monkeypatch, tmp_path, FakeAgent())

    assert rec.raised is None, rec.raised
    approval = {run["name"]: run for run in rec.status_check_runs}["mergecraft-approval"]
    assert approval["conclusion"] == "neutral"
    assert approval["external_id"] == f"{_RUN_ID}:{_RUN_ATTEMPT}"


async def test_a_partially_ignored_pr_carries_no_ignore_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _listing(monkeypatch, ["CHANGELOG.md", "src/app.py"])
    agent = FakeAgent()

    rec = await _run(monkeypatch, tmp_path, agent)

    assert rec.raised is None, rec.raised
    assert agent.calls, "a pull request with a reviewable file reaches the agent"
    packet = rec.report_status_calls[-1]["packet"]
    assert packet.triage is None or packet.triage.recognizer != "ignorePaths"
