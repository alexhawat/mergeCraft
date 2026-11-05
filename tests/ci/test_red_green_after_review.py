"""The receipt reader that runs after the review (#1056 part 5, round three).

``ingest_red_green_after_review`` is the only production reader of the declared
fail-then-pass receipt. The pre-agent action-side lane runs with
``red_green=False``, before ``checkout_pr`` has written the review diff, so the
receipt is read here, after the agent phase and the roster. What is pinned:

- the reader itself, against a fake GitHub client: a proven receipt from the
  declared same-repository run on the head SHA is ``proven``; a ``wait-for-ci``
  state that is not ``complete`` (or was not forwarded) is ``no-receipt`` naming
  the state, with nothing listed or downloaded; an incomplete listing, an unknown
  client or head SHA and a listing error are each ``no-receipt`` and never raise;
- the call site, through the real ``main._run_review_after_analyze``: the runs
  are listed exactly once, after the agent stub wrote the review diff and after
  the roster, and ``ToolState.red_green`` comes from that read. Removing the call
  leaves ``ToolState.red_green`` unset and fails the test;
- the pre-agent lane is called with ``red_green=False``, and with that flag the
  shared head-SHA ingest never downloads or records a receipt.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

import mergecraft.main as main_mod
from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import default_settings
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.scm.types import ListedItems
from tests.ci.support_crap import zip_artifact
from tests.ci.test_red_green_ingest import (
    _DOCS_DIFF,
    ARTIFACT,
    HEAD,
    RUN_URL,
    WORKFLOW,
    _artifact,
    _ctx,
    _declaration,
    _ingest,
    _receipt,
    _ReceiptGitHub,
    _run,
)

_WAIT_ENV = ("MERGECRAFT_CI_WAIT_STATE", "CI_STATE")
_BASE_CONFIG = (
    "push: restricted\n"
    "ciEvidence:\n"
    "  redGreen:\n"
    f"    artifact: {ARTIFACT}\n"
    f"    workflow: {WORKFLOW}\n"
)


class _OrderedGitHub(_ReceiptGitHub):
    """Fake GitHub that serves the base config and logs listings into a shared order."""

    def __init__(
        self,
        *,
        order: list[str] | None = None,
        incomplete: bool = False,
        list_error: Exception | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.order = order if order is not None else []
        self.incomplete = incomplete
        self.list_error = list_error
        self.listings = 0

    async def get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(f"GET {path}")
        if path.endswith("/contents/.mergecraft/config.yaml"):
            content = base64.b64encode(_BASE_CONFIG.encode("utf-8")).decode("ascii")
            return {"type": "file", "encoding": "base64", "content": content}
        return {}

    async def list_workflow_runs_for_head_sha(
        self, owner: str, repo: str, head_sha: str
    ) -> ListedItems:
        self.listings += 1
        self.order.append("list-runs")
        if self.list_error is not None:
            raise self.list_error
        listed = await super().list_workflow_runs_for_head_sha(owner, repo, head_sha)
        return ListedItems(items=list(listed.items), incomplete=self.incomplete)


def _proven_github(**kwargs: Any) -> _OrderedGitHub:
    archive = zip_artifact("red-green.json", _receipt())
    return _OrderedGitHub(
        artifacts_by_run={88: [_artifact(7, archive)]},
        archives={7: archive},
        runs=[_run(88)],
        **kwargs,
    )


@pytest.fixture
def ci_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _WAIT_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MERGECRAFT_CI_WAIT_STATE", "complete")
    monkeypatch.setenv("MERGECRAFT_CI_FAILED_COUNT", "0")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")


async def _read(ctx: Any) -> None:
    await _ingest().ingest_red_green_after_review(ctx, ctx.gh_event, event_name="pull_request")


# ── the reader ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.usefixtures("ci_complete")
async def test_the_reader_records_a_proven_receipt_from_the_declared_run(
    tmp_path: Path,
) -> None:
    github = _proven_github()
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())

    await _read(ctx)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "proven"
    assert evidence.artifact == ARTIFACT
    assert evidence.run_url == RUN_URL
    assert github.listings == 1
    assert github.downloaded == [7]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["timeout", "absent", "skipped", "pending"])
async def test_the_reader_reads_nothing_until_ci_is_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    for name in _WAIT_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MERGECRAFT_CI_WAIT_STATE", state)
    github = _proven_github()
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())

    await _read(ctx)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "no-receipt"
    assert state in evidence.detail
    assert github.listings == 0
    assert github.downloaded == []


@pytest.mark.asyncio
async def test_the_reader_reads_nothing_when_the_wait_state_was_not_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in _WAIT_ENV:
        monkeypatch.delenv(name, raising=False)
    github = _proven_github()
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())

    await _read(ctx)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "no-receipt"
    assert "not forwarded" in evidence.detail
    assert github.listings == 0
    assert github.downloaded == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("ci_complete")
async def test_an_incomplete_listing_records_no_receipt_and_downloads_nothing(
    tmp_path: Path,
) -> None:
    github = _proven_github(incomplete=True)
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())

    await _read(ctx)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "no-receipt"
    assert "incomplete" in evidence.detail
    assert github.downloaded == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("ci_complete")
async def test_no_github_client_records_no_receipt(tmp_path: Path) -> None:
    github = _proven_github()
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())
    ctx.scm = object()  # type: ignore[assignment]  # — a non-GitHub provider has no client

    await _read(ctx)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "no-receipt"
    assert evidence.detail
    assert github.listings == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("ci_complete")
async def test_no_head_sha_records_no_receipt(tmp_path: Path) -> None:
    github = _proven_github()
    ctx = _ctx(tmp_path, github=github, declaration=_declaration(), head_sha="")

    await _read(ctx)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "no-receipt"
    assert evidence.detail
    assert github.listings == 0
    assert github.downloaded == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("ci_complete")
async def test_a_listing_error_records_no_receipt_and_never_raises(tmp_path: Path) -> None:
    github = _proven_github(list_error=RuntimeError("boom"))
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())

    await _read(ctx)

    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "no-receipt"
    assert "RuntimeError" in evidence.detail
    assert github.downloaded == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("ci_complete")
async def test_the_reader_does_nothing_without_a_declaration(tmp_path: Path) -> None:
    github = _proven_github()
    ctx = _ctx(tmp_path, github=github)

    await _read(ctx)

    assert ctx.tool_state.red_green is None
    assert github.listings == 0


# ── the pre-agent lane ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(("red_green", "expected"), [(False, None), (True, "proven")])
async def test_the_head_sha_ingest_reads_the_receipt_only_when_asked(
    tmp_path: Path, red_green: bool, expected: str | None
) -> None:
    github = _proven_github()
    ctx = _ctx(tmp_path, github=github, declaration=_declaration())

    await _ingest().ingest_ci_sarif_for_head_sha(ctx, HEAD, red_green=red_green)

    evidence = ctx.tool_state.red_green
    assert (evidence.status if evidence is not None else None) == expected
    assert github.downloaded == ([] if expected is None else [7])


# ── the call site ────────────────────────────────────────────────────────────


@pytest.fixture
def run_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ci_complete: None
) -> dict[str, Any]:
    """A real ``_run_review_after_analyze`` with git, setup, MCP and the agent stubbed."""
    _ = ci_complete
    order: list[str] = []
    github = _proven_github(order=order)
    tool_context = _ctx(tmp_path, github=github, diff=None)
    ctx = main_mod.RunContext()
    ctx.settings = default_settings()
    ctx.tool_state = tool_context.tool_state
    ctx.tool_context = tool_context
    ctx.gh_event = tool_context.gh_event
    ctx.settings_snapshot_operator_owned = False
    record: dict[str, Any] = {"ctx": ctx, "github": github, "order": order, "pre_agent": []}

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    async def _pre_agent_ingest(*args: Any, **kwargs: Any) -> None:
        order.append("pre-agent-ingest")
        record["pre_agent"].append(kwargs)

    async def _agent(run_ctx: Any) -> AgentResult:
        state = run_ctx.tool_state
        record["red_green_before_agent"] = state.red_green
        diff_path = tmp_path / "pr-42.diff"
        diff_path.write_text(_DOCS_DIFF, encoding="utf-8")
        primary_repo_state(state).diff_path = str(diff_path)
        order.append("agent")
        return AgentResult(success=True, output="reviewed")

    async def _roster(run_ctx: Any) -> None:
        order.append("roster")

    monkeypatch.setattr(main_mod, "_apply_overrides_and_setup_git", _noop)
    monkeypatch.setattr(main_mod, "ingest_ci_sarif_from_action_env", _pre_agent_ingest)
    monkeypatch.setattr(main_mod, "_run_setup_script_phase", _noop)
    monkeypatch.setattr(main_mod, "_triage_gate", _noop)
    monkeypatch.setattr(main_mod, "_ignore_paths_gate", _noop)
    monkeypatch.setattr(main_mod, "_prepare_agent_dispatch", _noop)
    monkeypatch.setattr(main_mod, "_dispatch_agent_with_deadline", _agent)
    monkeypatch.setattr(main_mod, "_run_server_roster_reviewers_if_needed", _roster)
    return record


@pytest.mark.asyncio
async def test_the_receipt_is_read_once_after_the_agent_and_the_roster(
    run_harness: dict[str, Any],
) -> None:
    ctx = run_harness["ctx"]
    github = run_harness["github"]

    result = await main_mod._run_review_after_analyze(ctx)

    assert isinstance(result, AgentResult)
    assert run_harness["order"] == ["pre-agent-ingest", "agent", "roster", "list-runs"]
    assert github.listings == 1
    assert github.downloaded == [7]


@pytest.mark.asyncio
async def test_the_receipt_read_after_the_review_sets_tool_state(
    run_harness: dict[str, Any],
) -> None:
    ctx = run_harness["ctx"]

    await main_mod._run_review_after_analyze(ctx)

    assert run_harness["red_green_before_agent"] is None
    evidence = ctx.tool_state.red_green
    assert evidence is not None
    assert evidence.status == "proven"
    assert evidence.run_url == RUN_URL


@pytest.mark.asyncio
async def test_the_pre_agent_lane_never_reads_the_receipt(
    run_harness: dict[str, Any],
) -> None:
    ctx = run_harness["ctx"]

    await main_mod._run_review_after_analyze(ctx)

    calls = run_harness["pre_agent"]
    assert len(calls) == 1
    assert calls[0].get("red_green") is False
