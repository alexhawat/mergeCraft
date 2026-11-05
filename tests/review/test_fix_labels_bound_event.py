"""Label-based fix detection survives a bound pull request (#1056 part 5, review round 4).

A review started from a comment on the pull request (``issue_comment``) or from a
``workflow_dispatch`` naming it binds the target pull request into the event with
only ``number``/``head``/``base`` (``bind_target_pull_request``): no ``labels``.
Reading the labels off that stub made every such run see an unlabelled pull
request, so a ``bug``-labelled fix with a non-``fix`` title was ``fix.not-required``
and could stay in the low lane the gate exists to prevent. Pinned here:

- ``event_pull_request_labels`` skips a ``pull_request`` without a ``labels`` key and
  reads ``issue.labels`` on a comment event; it is ``None`` only when the event has
  no labels anywhere, never an empty list by default;
- ``fix_proof_signal_for_context`` prefers ``ToolState.pull_request_labels`` and
  otherwise the event's labels, so a bound comment event still makes a labelled
  pull request a fix;
- at run start (the real ``_run_review_after_analyze``), a dispatch-bound event
  reads the pull request once and records its labels on
  ``ToolState.pull_request_labels``; a read that fails leaves ``None`` and the run
  goes on with title-only detection.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import mergecraft.main as main_mod
from mergecraft.config.settings import default_settings
from mergecraft.config.trust_policy import bind_target_pull_request
from mergecraft.evidence.run_packet import (
    event_pull_request_labels,
    fix_proof_signal_for_context,
)
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


def _pull(labels: list[str]) -> dict[str, Any]:
    return {
        "number": 42,
        "title": "Handle empty input",
        "labels": [{"name": name} for name in labels],
        "base": {"sha": BASE_SHA, "ref": "main", "repo": {"full_name": "acme/demo"}},
        "head": {"sha": HEAD_SHA, "ref": "fix-it", "repo": {"full_name": "acme/demo"}},
    }


def _comment_event(labels: list[str]) -> dict[str, Any]:
    """An ``issue_comment`` on a pull request, bound the way ``_resolve_credentials`` binds it."""
    raw = {
        "action": "created",
        "issue": {
            "number": 42,
            "title": "Handle empty input",
            "labels": [{"name": name} for name in labels],
            "pull_request": {"url": "https://api.github.com/repos/acme/demo/pulls/42"},
        },
        "comment": {"body": "@mergecraft review"},
    }
    return bind_target_pull_request(raw, _pull(labels))


def _dispatch_event() -> dict[str, Any]:
    """A PR-naming ``workflow_dispatch``, bound: no labels anywhere on the event."""
    raw = {"inputs": {"prompt": "Review pull request #42."}}
    return bind_target_pull_request(raw, _pull(["bug"]))


# --- event_pull_request_labels ------------------------------------------------------


def test_a_bound_comment_event_still_gives_the_issue_labels() -> None:
    assert event_pull_request_labels(_comment_event(["bug", "docs"])) == ["bug", "docs"]


def test_a_pull_request_event_gives_its_own_labels() -> None:
    event = {"pull_request": _pull(["fix"])}

    assert event_pull_request_labels(event) == ["fix"]


def test_a_bound_dispatch_event_has_no_labels_to_give() -> None:
    assert event_pull_request_labels(_dispatch_event()) is None


def test_an_unlabelled_pull_request_is_an_empty_list_not_unknown() -> None:
    event = {"pull_request": _pull([])}

    assert event_pull_request_labels(event) == []


def test_malformed_label_entries_are_skipped() -> None:
    event = {"pull_request": {"number": 1, "labels": [{"name": "bug"}, "fix", {"id": 3}, None]}}

    assert event_pull_request_labels(event) == ["bug"]


# --- fix_proof_signal_for_context -------------------------------------------------


def _tool_context(
    tmp_path: Path, *, gh_event: dict[str, Any], read_labels: tuple[str, ...] | None
) -> Any:

    from mergecraft.config.settings_snapshot import RepoSettingsSnapshot
    from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.modes import compute_modes
    from mergecraft.utils.github import GitHubClient

    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    diff_path = tmp_path / "pr-42.diff"
    diff_path.write_text("diff --git a/x.py b/x.py\n", encoding="utf-8")
    primary_repo_state(tool_state).diff_path = str(diff_path)
    tool_state.fix_labels = ("bug", "fix")
    tool_state.pull_request_labels = read_labels
    settings = default_settings()
    snapshot = RepoSettingsSnapshot(
        settings=settings, config_hash="", repo_root=tmp_path, operator_owned=True
    )
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(
                trigger="issue_comment", issue_number=42, is_pr=True, title="Handle empty input"
            ),
        ),
        github=GitHubClient(token=""),
        modes=compute_modes("claude"),
        tool_state=tool_state,
        tmpdir=str(tmp_path),
        resolved_model="claude-sonnet-4-5",
        trust_tier="trusted",
        repo_settings_snapshot=snapshot,
        gh_event=gh_event,
    )


def test_a_bug_labelled_pull_request_is_a_fix_on_a_bound_comment_event(tmp_path: Path) -> None:
    ctx = _tool_context(tmp_path, gh_event=_comment_event(["bug"]), read_labels=None)

    signal = fix_proof_signal_for_context(ctx)

    assert signal["required"] is True
    assert signal["status"] == "no-receipt"


def test_labels_read_at_run_start_win_over_the_event(tmp_path: Path) -> None:
    ctx = _tool_context(tmp_path, gh_event=_dispatch_event(), read_labels=("bug",))

    signal = fix_proof_signal_for_context(ctx)

    assert signal["required"] is True


def test_a_bound_dispatch_event_with_nothing_read_falls_back_to_the_title(tmp_path: Path) -> None:
    ctx = _tool_context(tmp_path, gh_event=_dispatch_event(), read_labels=None)

    signal = fix_proof_signal_for_context(ctx)

    assert signal == {"required": False, "status": "not-required"}


def test_an_unlabelled_comment_event_is_not_a_fix(tmp_path: Path) -> None:
    ctx = _tool_context(tmp_path, gh_event=_comment_event([]), read_labels=None)

    assert fix_proof_signal_for_context(ctx)["required"] is False


# --- run start reads the labels through the SCM -----------------------------------


class _Scm:
    """Answers ``get_pull`` with the labelled pull request; records each call."""

    def __init__(self, *, pull: dict[str, Any] | None, fail: bool = False) -> None:
        self.pull = pull
        self.fail = fail
        self.get_pull_calls: list[tuple[str, str, int]] = []

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        self.get_pull_calls.append((owner, repo, pull_number))
        if self.fail:
            msg = "boom"
            raise RuntimeError(msg)
        return dict(self.pull or {})

    async def closing_issues(self, owner: str, repo: str, number: int) -> tuple[Any, ...]:
        return ()

    async def get(self, path: str, **kwargs: object) -> object:
        return {}


def _run_ctx(tmp_path: Path, scm: _Scm, *, gh_event: dict[str, Any]) -> Any:
    ctx = main_mod.RunContext()
    ctx.settings = default_settings()
    ctx.tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    ctx.tool_context = SimpleNamespace(
        repo=SimpleNamespace(owner="acme", name="demo"), scm=scm, tool_state=ctx.tool_state
    )
    ctx.gh_event = gh_event
    ctx.pr_number = 42
    ctx.settings_snapshot_operator_owned = True
    return ctx


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the I/O phases; record the tool state at the triage gate and stop there."""
    record: dict[str, Any] = {}

    async def _noop(*args: Any, **kwargs: Any) -> None:
        return None

    async def _triage(ctx: Any) -> Any:
        record["pull_request_labels"] = ctx.tool_state.pull_request_labels
        record["fix_labels"] = ctx.tool_state.fix_labels
        return main_mod.SkipAgentReview(reason="stopped at triage by the test")

    monkeypatch.setattr(main_mod, "_apply_overrides_and_setup_git", _noop)
    monkeypatch.setattr(main_mod, "_run_setup_script_phase", _noop)
    monkeypatch.setattr(main_mod, "ingest_ci_sarif_from_action_env", _noop)
    monkeypatch.setattr(main_mod, "_triage_gate", _triage)
    return record


@pytest.mark.asyncio
async def test_run_start_reads_the_labels_of_a_dispatch_bound_pull_request(
    tmp_path: Path, seen: dict[str, Any]
) -> None:
    scm = _Scm(pull=_pull(["bug"]))
    ctx = _run_ctx(tmp_path, scm, gh_event=_dispatch_event())

    result = await main_mod._run_review_after_analyze(ctx)

    assert isinstance(result, main_mod.SkipAgentReview)
    assert seen["pull_request_labels"] == ("bug",)
    assert ("acme", "demo", 42) in scm.get_pull_calls


@pytest.mark.asyncio
async def test_run_start_takes_the_labels_from_a_comment_event_without_a_read(
    tmp_path: Path, seen: dict[str, Any]
) -> None:
    scm = _Scm(pull=_pull(["bug"]))
    ctx = _run_ctx(tmp_path, scm, gh_event=_comment_event(["bug", "docs"]))

    await main_mod._run_review_after_analyze(ctx)

    assert seen["pull_request_labels"] == ("bug", "docs")


@pytest.mark.asyncio
async def test_a_failed_label_read_leaves_title_only_detection_and_the_run_going(
    tmp_path: Path, seen: dict[str, Any]
) -> None:
    scm = _Scm(pull=None, fail=True)
    ctx = _run_ctx(tmp_path, scm, gh_event=_dispatch_event())

    result = await main_mod._run_review_after_analyze(ctx)

    assert isinstance(result, main_mod.SkipAgentReview)
    assert seen["pull_request_labels"] is None
    assert seen["fix_labels"] is not None, "the base fix labels are still resolved"
