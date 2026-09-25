"""The post-run sink scan fails the run and removes the sink before upload (S10).

A credential that reached a local log sink has already left the agent's process;
the honest post-run response is to stop the run, name the sink path (never its
contents), force the approval conclusion to ``failure``, and delete the matching
files before the workflow's artifact-upload step can ship them. Every artifact
source the evidence and trace uploads are assembled from is in scope, not only
the run's temp directory.

The scan runs before ``_publish``, so the artifact the run generates *during*
publication — the emitted packet / run packet — is a second timing hazard: the
generated sink must be re-checked after it is written and deleted before upload,
or a credential that only ever reached the packet ships anyway.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.main import RunOutcome
from mergecraft.utils.status_checks import APPROVAL_CHECK, COMPLETION_CHECK
from tests.support.run_main_harness import run_main_for_test

_SCM_CANARY = "ghs_fake_git_token"
_PROVIDER_CANARY = "sk-ant-review-sink-canary"

_ARTIFACT_SOURCES = (
    "packet-nous.json",
    "packet-codex.json",
    "packet-claude.json",
    "mergecraft/run-packet.json",
    "shadow-compare.jsonl",
)

_GENERATED_PACKET = "mergecraft/run-packet.json"


class _SinkWritingAgent:
    """Agent stand-in that plants one canary sink during the run."""

    def __init__(self, *, run_tmpdir_sink: bool) -> None:
        self.name = "claude"
        self.calls: list[str] = []
        self._run_tmpdir_sink = run_tmpdir_sink
        self.seen_tmpdir: str | None = None

    async def install(self, token: str | None = None) -> str:
        return self.name

    async def run(self, ctx: Any) -> AgentResult:
        self.calls.append(self.name)
        payload = f"scm={_SCM_CANARY}\nprovider={_PROVIDER_CANARY}\n"
        tmpdir = ctx.tmpdir
        self.seen_tmpdir = tmpdir
        if self._run_tmpdir_sink:
            (Path(tmpdir) / "leak.log").write_text(payload, encoding="utf-8")
        return AgentResult(success=True, output="fake-agent-output")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location",
    ["run-tmpdir", *_ARTIFACT_SOURCES],
    ids=["run-tmpdir", *[source.replace("/", "-") for source in _ARTIFACT_SOURCES]],
)
async def test_canary_sink_fails_the_run_names_the_path_and_is_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    runner_temp = tmp_path / "runner-temp"
    run_tmpdir_sink = location == "run-tmpdir"
    agent = _SinkWritingAgent(run_tmpdir_sink=run_tmpdir_sink)

    if not run_tmpdir_sink:
        real_run = agent.run

        async def _run_with_artifact(ctx: object) -> AgentResult:
            sink = Path(os.environ["RUNNER_TEMP"]) / location
            sink.parent.mkdir(parents=True, exist_ok=True)
            sink.write_text(f"scm={_SCM_CANARY}\nprovider={_PROVIDER_CANARY}\n", encoding="utf-8")
            return await real_run(ctx)

        agent.run = _run_with_artifact  # type: ignore[method-assign] — per-case sink placement

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        cleanup_tmpdir=False,
        agent=agent,  # type: ignore[arg-type] — duck-typed agent, same protocol as FakeAgent
        env={"ANTHROPIC_API_KEY": _PROVIDER_CANARY},
        capture_status_checks=True,
    )

    assert rec.raised is None, rec.raised
    assert rec.result is not None
    assert rec.result.success is False
    assert rec.result.outcome is RunOutcome.failed
    error = rec.result.error or ""
    if run_tmpdir_sink:
        expected_path = str(Path(agent.seen_tmpdir or "") / "leak.log")
    else:
        expected_path = str(runner_temp / location)
    assert expected_path in error, error
    assert _SCM_CANARY not in error, error
    assert _PROVIDER_CANARY not in error, error

    # The sink hit must fail the run *and* force the merge gate closed. The
    # completion check alone is not enough: ``mergecraft-approval`` is the
    # check the merge gate reads, and it is derived from the packet verdict
    # unless the sink hit overrides it (SX-D10). Assert the check the operator
    # actually gates on, not merely that some check concluded ``failure``.
    completion_runs = [run for run in rec.status_check_runs if run.get("name") == COMPLETION_CHECK]
    assert completion_runs, rec.status_check_runs
    assert completion_runs[-1].get("conclusion") == "failure", completion_runs
    approval_runs = [run for run in rec.status_check_runs if run.get("name") == APPROVAL_CHECK]
    assert approval_runs, rec.status_check_runs
    assert all(run.get("conclusion") == "failure" for run in approval_runs), approval_runs

    if not run_tmpdir_sink:
        assert not (runner_temp / location).exists(), "the sink must be removed before upload"


@pytest.mark.asyncio
async def test_canary_in_the_generated_packet_fails_before_upload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A credential the run writes into its own packet is caught after publication.

    The post-run sink scan runs before ``_publish``, so a credential that first
    reaches an artifact the run generates *during publication* — the emitted
    ``packet-*.json`` / run packet, which the scanner itself treats as an upload
    source — would otherwise ship untouched (SX-D10). The packet below is
    written at publication time, not during the agent phase, so only a
    post-publish re-scan can see it: the run must fail, name the path, force the
    ``mergecraft-approval`` conclusion to ``failure`` and delete the file before
    the workflow's artifact upload, without printing its contents.
    """
    runner_temp = tmp_path / "runner-temp"
    packet_path = runner_temp / _GENERATED_PACKET
    payload = f"scm={_SCM_CANARY}\nprovider={_PROVIDER_CANARY}\n"
    agent = _SinkWritingAgent(run_tmpdir_sink=False)

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        cleanup_tmpdir=False,
        agent=agent,  # type: ignore[arg-type] — duck-typed agent, same protocol as FakeAgent
        env={"ANTHROPIC_API_KEY": _PROVIDER_CANARY},
        capture_status_checks=True,
        packet_path=packet_path,
        packet_payload=payload,
    )

    assert rec.raised is None, rec.raised
    assert rec.result is not None
    assert rec.result.success is False
    assert rec.result.outcome is RunOutcome.failed
    error = rec.result.error or ""
    assert str(packet_path) in error, error
    assert _SCM_CANARY not in error, error
    assert _PROVIDER_CANARY not in error, error

    completion_runs = [run for run in rec.status_check_runs if run.get("name") == COMPLETION_CHECK]
    assert completion_runs, rec.status_check_runs
    assert completion_runs[-1].get("conclusion") == "failure", completion_runs
    approval_runs = [run for run in rec.status_check_runs if run.get("name") == APPROVAL_CHECK]
    assert approval_runs, rec.status_check_runs
    assert approval_runs[-1].get("conclusion") == "failure", approval_runs

    assert not packet_path.exists(), (
        "the run-generated packet holding credential material must be removed "
        "before the workflow's artifact upload"
    )


@pytest.mark.asyncio
async def test_clean_sinks_change_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner_temp = tmp_path / "runner-temp"
    agent = _SinkWritingAgent(run_tmpdir_sink=False)

    async def _run_with_clean_sink(ctx: object) -> AgentResult:
        sink = Path(os.environ["RUNNER_TEMP"]) / "packet-nous.json"
        sink.write_text('{"verdict": "pass"}\n', encoding="utf-8")
        return AgentResult(success=True, output="fake-agent-output")

    agent.run = _run_with_clean_sink  # type: ignore[method-assign] — benign sink placement

    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        cleanup_tmpdir=False,
        agent=agent,  # type: ignore[arg-type] — duck-typed agent, same protocol as FakeAgent
    )

    assert rec.raised is None, rec.raised
    assert rec.result is not None
    assert rec.result.success is True
    assert (runner_temp / "packet-nous.json").exists()
