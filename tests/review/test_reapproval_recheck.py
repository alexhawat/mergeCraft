"""The deterministic recheck behind a re-approval under a changed review policy.

When the pull request's own changes are proven unchanged but the review policy moved,
the prior pass carries over only after the analyzers and static checks ran clean on the
new head, with no model. These tests drive ``run_deterministic_recheck`` with the three
tool bodies replaced by scripted ones, then drive ``main()`` to show the run publishes a
carried-over pass after a clean recheck and takes the normal review after anything else.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import mergecraft.reapproval as reapproval_mod
from mergecraft.action import reapproval_recheck, review_policy
from mergecraft.action.reapproval_recheck import RecheckOutcome, run_deterministic_recheck
from mergecraft.classify.reapproval import (
    RECHECK_SKIPPED_WORK,
    ReapprovalRecord,
    ReapprovalVerdict,
    ReviewStamp,
)
from mergecraft.config.settings import RepoSettings
from mergecraft.mcp.shared import ToolClass, ToolResult, ToolSpec
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.reapproval import ReapprovalOutcome
from mergecraft.run_outcome import RunOutcome
from tests.support.run_main_harness import FakeAgent, run_main_for_test

_PRIOR = "a" * 40
_HEAD = "c" * 40
_PULL = 1280
_PRIOR_URL = "https://github.com/acme/demo/actions/runs/42697047477"
_STAMP = ReviewStamp(pull_number=_PULL, base_ref="main", policy_digest="d" * 64)
_DIFF = (
    "diff --git a/src/app.py b/src/app.py\n"
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def handler(x):\n"
    "-    return x + 1\n"
    "+    return x + 2\n"
)
_CLEAN_ANALYZERS: dict[str, Any] = {
    "ran": True,
    "analyzers": [
        {"id": "ruff", "status": "passed", "reason": None, "findingCount": 0},
        {"id": "typos", "status": "unavailable", "reason": "withheld", "findingCount": 0},
    ],
    "findingCount": 0,
}
_CLEAN_CHECKS: dict[str, Any] = {
    "ran": True,
    "allPassed": True,
    "checks": [{"name": "lint", "status": "passed"}],
}


class _Tools:
    """Scripted ``checkout_pr`` / ``run_analyzers`` / ``run_static_checks`` bodies."""

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        *,
        checkout: dict[str, Any] | None = None,
        checkout_error: str | None = None,
        checkout_sha: str = _HEAD,
        analyzers: dict[str, Any] | Exception | str | None = None,
        checks: dict[str, Any] | Exception | None = None,
        analyzers_on: bool = True,
        checks_on: bool = True,
        hang: str | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._tmp = tmp_path
        self._checkout = checkout or {}
        self._checkout_error = checkout_error
        self._checkout_sha = checkout_sha
        self._analyzers = _CLEAN_ANALYZERS if analyzers is None else analyzers
        self._checks = _CLEAN_CHECKS if checks is None else checks
        self._checks_on = checks_on
        self._hang = hang
        import mergecraft.analyzers.trust as trust
        import mergecraft.mcp.analyzers as analyzers_mod
        import mergecraft.mcp.checkout as checkout_mod
        import mergecraft.mcp.static_checks as checks_mod

        monkeypatch.setattr(checkout_mod, "checkout_pr_tool", self._checkout_tool)
        monkeypatch.setattr(analyzers_mod, "run_analyzers_tool", self._analyzers_tool)
        monkeypatch.setattr(checks_mod, "run_static_checks_tool", self._checks_tool)
        monkeypatch.setattr(trust, "analyzers_enabled", lambda _ctx: analyzers_on)

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def _spec(self, name: str, body: Any, *, timeout_ms: int | None = None) -> ToolSpec:
        async def _execute(params: Any) -> ToolResult:
            self.calls.append((name, dict(params)))
            if self._hang == name:
                await asyncio.sleep(3600)
            result = body(dict(params))
            if isinstance(result, Exception):
                return ToolResult(
                    content=[{"type": "text", "text": f"Error: {result}"}], is_error=True
                )
            text = result if isinstance(result, str) else json.dumps(result)
            return ToolResult(content=[{"type": "text", "text": text}])

        return ToolSpec(
            name=name,
            description=name,
            input_schema={"type": "object"},
            execute=_execute,
            tool_class=ToolClass.ANALYSIS,
            timeout_ms=timeout_ms,
        )

    def _checkout_tool(self, ctx: Any) -> ToolSpec:
        def _body(params: dict[str, Any]) -> Any:
            if self._checkout_error is not None:
                return RuntimeError(self._checkout_error)
            # What the real checkout leaves behind: a diff on disk registered as the
            # review scope, the delivered diff recorded for coverage, the head bound.
            from mergecraft.mcp.checkout import _record_delivered_diff
            from mergecraft.mcp.verdict import register_review_scope

            diff_path = self._tmp / f"pr-{params['pull_number']}.diff"
            diff_path.write_text(_DIFF, encoding="utf-8")
            register_review_scope(ctx.tool_state, diff_path=str(diff_path), provenance="checkout")
            _record_delivered_diff(ctx, _DIFF, unreviewable=[], truncated=False)
            primary_repo_state(ctx.tool_state).checkout_sha = self._checkout_sha
            return {
                "pullNumber": params["pull_number"],
                "headSha": self._checkout_sha,
                "diffPath": str(diff_path),
                **self._checkout,
            }

        return self._spec("checkout_pr", _body)

    def _analyzers_tool(self, _ctx: Any) -> ToolSpec:
        return self._spec("run_analyzers", lambda _params: self._analyzers, timeout_ms=50)

    def _checks_tool(self, ctx: Any) -> ToolSpec:
        ctx.static_checks_enabled = self._checks_on
        return self._spec("run_static_checks", lambda _params: self._checks)


def _ctx(tmp_path: Path, *, static_checks: bool = True) -> Any:
    from tests.evidence.test_run_packet import _make_ctx

    ctx = _make_ctx(tmp_path, diff_text=None, findings=[])
    ctx.tool_state.analyzer_run = None
    ctx.static_checks_enabled = static_checks
    return ctx


async def _recheck(ctx: Any) -> RecheckOutcome:
    return await run_deterministic_recheck(ctx, pull_number=_PULL, head_sha=_HEAD)


# ── the recheck itself ────────────────────────────────────────────────────────


async def test_a_clean_recheck_runs_the_three_steps_in_order_and_states_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools = _Tools(monkeypatch, tmp_path)

    outcome = await _recheck(_ctx(tmp_path))

    assert outcome == RecheckOutcome(
        clean=True,
        ran=(
            "analyzers: 1 ran, 1 unavailable, 0 findings",
            "static checks: 1 declared, all that ran passed",
        ),
    )
    assert tools.names() == ["checkout_pr", "run_analyzers", "run_static_checks"]
    assert tools.calls[0][1] == {"pull_number": _PULL}
    assert tools.calls[1][1]["changed_files"] == ["src/app.py"]
    assert tools.calls[1][1]["diff_path"].endswith(f"pr-{_PULL}.diff")
    assert tools.calls[2][1] == {"changed_files": ["src/app.py"]}


async def test_a_clean_recheck_leaves_no_review_scope_behind(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mergecraft.evidence.coverage import coverage_section_for_state

    _Tools(monkeypatch, tmp_path)
    ctx = _ctx(tmp_path)

    assert (await _recheck(ctx)).clean

    repo = primary_repo_state(ctx.tool_state)
    assert repo.checkout_sha == _HEAD, "the run stays bound to the head it checked"
    assert repo.diff_path is None
    assert ctx.tool_state.coverage.authoritative_diff is None
    assert coverage_section_for_state(ctx.tool_state) is None, (
        "no reviewer was handed the diff, so there is no coverage to account for"
    )


async def test_a_recheck_that_is_not_clean_keeps_the_scope_for_the_normal_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Tools(monkeypatch, tmp_path, analyzers={**_CLEAN_ANALYZERS, "findingCount": 1})
    ctx = _ctx(tmp_path)

    assert not (await _recheck(ctx)).clean

    assert primary_repo_state(ctx.tool_state).diff_path is not None


@pytest.mark.parametrize(
    ("analyzers", "reason"),
    [
        ({**_CLEAN_ANALYZERS, "findingCount": 2}, "analyzers reported findings (2)"),
        ({**_CLEAN_ANALYZERS, "findingCount": None}, "analyzers reported findings (None)"),
        ({**_CLEAN_ANALYZERS, "findingCount": True}, "analyzers reported findings (True)"),
        (
            {
                "ran": True,
                "findingCount": 0,
                "analyzers": [{"id": "ruff", "status": "failed", "findingCount": 0}],
            },
            "analyzers reported a failure (ruff)",
        ),
        (
            {
                "ran": True,
                "findingCount": 0,
                "analyzers": [{"id": "semgrep", "status": "tool-error", "findingCount": 0}],
            },
            "analyzers reported a failure (semgrep)",
        ),
        (RuntimeError("catalog unavailable"), "run_analyzers failed (Error: catalog unavailable)"),
        ("not json", "run_analyzers returned an unreadable result"),
        ("[1, 2]", "run_analyzers returned an unexpected result"),
    ],
)
async def test_an_analyzer_that_speaks_against_the_change_is_not_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, analyzers: Any, reason: str
) -> None:
    tools = _Tools(monkeypatch, tmp_path, analyzers=analyzers)

    outcome = await _recheck(_ctx(tmp_path))

    assert not outcome.clean
    assert outcome.reason == reason
    assert "run_static_checks" not in tools.names(), "the first not-clean step ends the recheck"


@pytest.mark.parametrize(
    ("checks", "reason"),
    [
        ({"ran": True, "allPassed": False, "checks": []}, "a static check failed"),
        ({"ran": True, "checks": []}, "a static check failed"),
        ({"checks": []}, "run_static_checks returned an unexpected result"),
        (RuntimeError("make: *** [lint]"), "run_static_checks failed (Error: make: *** [lint])"),
    ],
)
async def test_a_failing_static_check_is_not_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checks: Any, reason: str
) -> None:
    _Tools(monkeypatch, tmp_path, checks=checks)

    outcome = await _recheck(_ctx(tmp_path))

    assert not outcome.clean
    assert outcome.reason == reason
    assert outcome.ran == ("analyzers: 1 ran, 1 unavailable, 0 findings",)


@pytest.mark.parametrize(
    ("checkout", "reason"),
    [
        ({"scope": "api-only"}, "the head could not be checked out completely"),
        ({"degraded": "git diff failed"}, "the head could not be checked out completely"),
        ({"diffTruncated": True}, "the change could not be read completely"),
        ({"unreviewablePaths": ["big.bin"]}, "the change could not be read completely"),
        ({"diffPath": ""}, "the checkout produced no diff"),
        ({"diffPath": "/nonexistent/pr.diff"}, "the checkout's diff could not be read"),
    ],
)
async def test_a_head_that_was_not_fully_materialized_is_not_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, checkout: dict[str, Any], reason: str
) -> None:
    tools = _Tools(monkeypatch, tmp_path, checkout=checkout)

    outcome = await _recheck(_ctx(tmp_path))

    assert outcome == RecheckOutcome(clean=False, reason=reason)
    assert tools.names() == ["checkout_pr"], "nothing is analyzed on a tree that is not the head"


async def test_a_checkout_of_another_revision_is_not_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools = _Tools(monkeypatch, tmp_path, checkout_sha="e" * 40)

    outcome = await _recheck(_ctx(tmp_path))

    assert outcome.reason == "the checked-out revision is not the head under review"
    assert tools.names() == ["checkout_pr"]


async def test_a_refused_checkout_is_not_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Tools(monkeypatch, tmp_path, checkout_error="cannot checkout PR while the tree is dirty")

    outcome = await _recheck(_ctx(tmp_path))

    assert not outcome.clean
    assert "checkout_pr failed" in outcome.reason
    assert "tree is dirty" in outcome.reason


async def test_a_step_that_outlives_its_timeout_is_not_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _Tools(monkeypatch, tmp_path, hang="run_analyzers")

    outcome = await asyncio.wait_for(_recheck(_ctx(tmp_path)), timeout=5)

    assert outcome == RecheckOutcome(clean=False, reason="run_analyzers timed out")


async def test_an_unexpected_error_is_not_clean_and_never_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import mergecraft.mcp.checkout as checkout_mod

    def _boom(_ctx: Any) -> ToolSpec:
        raise KeyError("repos")

    monkeypatch.setattr(checkout_mod, "checkout_pr_tool", _boom)

    outcome = await _recheck(_ctx(tmp_path))

    assert outcome == RecheckOutcome(
        clean=False, reason="the deterministic checks could not run (KeyError)"
    )


async def test_checks_the_run_does_not_enable_are_stated_not_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tools = _Tools(monkeypatch, tmp_path, analyzers_on=False)

    outcome = await _recheck(_ctx(tmp_path, static_checks=False))

    assert outcome == RecheckOutcome(
        clean=True,
        ran=(
            "analyzers: not enabled for this run",
            "static checks: not enabled for this run",
        ),
    )
    assert tools.names() == ["checkout_pr"]


async def test_static_checks_that_could_not_run_here_are_stated_and_clean(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    unavailable = {
        "ran": False,
        "reason": "withheld under shell: disabled",
        "checks": [{"name": "lint", "status": "unavailable"}],
    }
    _Tools(monkeypatch, tmp_path, checks=unavailable)

    outcome = await _recheck(_ctx(tmp_path))

    assert outcome.clean
    assert outcome.ran[-1] == "static checks: 1 declared, none could run here"


# ── through ``main()`` ────────────────────────────────────────────────────────

_EVENT: dict[str, Any] = {
    "action": "synchronize",
    "number": _PULL,
    "pull_request": {
        "number": _PULL,
        "title": "Merge main",
        "body": "",
        "head": {"ref": "feature", "sha": _HEAD, "repo": {"full_name": "acme/demo", "fork": False}},
        "base": {"ref": "main", "sha": "b" * 40, "repo": {"full_name": "acme/demo"}},
    },
    "repository": {"full_name": "acme/demo", "owner": {"login": "acme"}, "name": "demo"},
}


def _record(*, policy_changed: bool = True) -> ReapprovalRecord:
    return ReapprovalRecord(
        prior_url=_PRIOR_URL,
        prior_check_id=101,
        prior_head_sha=_PRIOR,
        head_sha=_HEAD,
        prior_merge_base="1" * 40,
        merge_base="2" * 40,
        qualifying_paths=(),
        preserved_paths=("src/app.py",),
        inherited_paths=("src/other.py",),
        skipped=RECHECK_SKIPPED_WORK,
        policy_changed=policy_changed,
    )


def _settings() -> RepoSettings:
    return RepoSettings.model_validate(
        {
            "trust": {"selfReview": "full"},
            "review": {
                "fastPath": {
                    "enabled": True,
                    "reapproval": {"enabled": True, "trustedCheckApps": ["mergecraft-reviewer"]},
                }
            },
        }
    )


@pytest.fixture
def policy_changed(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The proof holds, but under a review policy that changed since the prior pass."""
    from mergecraft.classify.triage import TriageInputs

    record = _record()
    calls: list[dict[str, Any]] = []

    async def _evaluate(*_args: Any, **kwargs: Any) -> ReapprovalOutcome:
        calls.append(kwargs)
        return ReapprovalOutcome(verdict=ReapprovalVerdict(record, record.reason()), stamp=_STAMP)

    async def _inputs(*_args: Any, **_kwargs: Any) -> TriageInputs:
        return TriageInputs(diff_text="", head_files={}, passed_checks=())

    monkeypatch.setattr(reapproval_mod, "evaluate_reapproval", _evaluate)
    monkeypatch.setattr(review_policy, "load_triage_inputs", _inputs, raising=False)
    return calls


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    agent: FakeAgent | None = None,
    env: dict[str, str] | None = None,
) -> Any:
    return await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=_settings(),
        env=env,
        event_name="pull_request_target",
        event_payload=_EVENT,
        agent=agent,
        capture_status_checks=True,
    )


async def test_a_clean_recheck_carries_the_pass_over_with_zero_llm_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, policy_changed: list[dict[str, Any]]
) -> None:
    """The whole path: real recheck, real publish, scripted tool bodies."""
    tools = _Tools(monkeypatch, tmp_path)
    agent = FakeAgent()

    rec = await _run(monkeypatch, tmp_path, agent)

    assert rec.raised is None, rec.raised
    assert tools.names() == ["checkout_pr", "run_analyzers", "run_static_checks"]
    assert rec.agent_runs == []
    assert agent.calls == []
    assert rec.result is not None
    assert rec.result.outcome is RunOutcome.passed
    packet = rec.report_status_calls[-1]["packet"]
    assert packet.reviewed_head_sha == _HEAD
    assert (packet.triage.tier, packet.triage.recognizer) == ("skip", "reapproval")
    section = packet.triage.reapproval
    assert section.policy_changed is True
    assert section.rechecked == [
        "analyzers: 1 ran, 1 unavailable, 0 findings",
        "static checks: 1 declared, all that ran passed",
    ]
    assert section.qualifying_paths == []
    assert "analyzers" not in section.skipped
    assert packet.coverage is None
    assert packet.decision.verdict == "success"
    by_name = {run["name"]: run for run in rec.status_check_runs}
    approval = by_name["mergecraft-approval"]
    assert approval["conclusion"] == "success"
    assert approval["head_sha"] == _HEAD
    summary = approval["output"]["summary"]
    assert "Review policy: changed since the prior review" in summary
    assert "Re-ran: analyzers: 1 ran, 1 unavailable, 0 findings" in summary
    assert "Re-ran: static checks: 1 declared, all that ran passed" in summary
    assert "Qualifying path: none" in summary
    assert "Skipped: LLM review, specialist and verifier agents, full-diff reads" in summary


@pytest.mark.parametrize(
    "tools_kwargs",
    [
        {"analyzers": {**_CLEAN_ANALYZERS, "findingCount": 1}},
        {"checks": {"ran": True, "allPassed": False, "checks": []}},
        {"checkout": {"scope": "api-only"}},
    ],
)
async def test_a_recheck_that_is_not_clean_runs_the_normal_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    policy_changed: list[dict[str, Any]],
    tools_kwargs: dict[str, Any],
) -> None:
    _Tools(monkeypatch, tmp_path, **tools_kwargs)
    agent = FakeAgent()

    rec = await _run(monkeypatch, tmp_path, agent)

    assert rec.raised is None, rec.raised
    assert rec.agent_runs, "anything but a clean recheck is the normal review"
    packet = rec.report_status_calls[-1]["packet"]
    assert packet.triage is None or packet.triage.reapproval is None


async def test_an_unchanged_policy_never_runs_the_recheck(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, policy_changed: list[dict[str, Any]]
) -> None:
    record = _record(policy_changed=False)

    async def _evaluate(*_args: Any, **_kwargs: Any) -> ReapprovalOutcome:
        return ReapprovalOutcome(verdict=ReapprovalVerdict(record, record.reason()), stamp=_STAMP)

    async def _never(*_args: Any, **_kwargs: Any) -> RecheckOutcome:
        raise AssertionError("an unchanged policy owes no recheck")

    monkeypatch.setattr(reapproval_mod, "evaluate_reapproval", _evaluate)
    monkeypatch.setattr(review_policy, "run_deterministic_recheck", _never)

    rec = await _run(monkeypatch, tmp_path, FakeAgent())

    assert rec.raised is None, rec.raised
    assert rec.agent_runs == []
    packet = rec.report_status_calls[-1]["packet"]
    assert packet.triage.reapproval.policy_changed is False
    assert packet.decision.verdict == "success"


async def test_the_gate_hands_the_running_action_pin_to_the_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, policy_changed: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(
        review_policy,
        "run_deterministic_recheck",
        _fixed(RecheckOutcome(clean=True, ran=("analyzers: 0 ran, 0 unavailable, 0 findings",))),
    )

    rec = await _run(monkeypatch, tmp_path, FakeAgent(), env={"MERGECRAFT_ACTION_SHA": "7" * 40})

    assert rec.raised is None, rec.raised
    assert [call["action_pin"] for call in policy_changed] == ["7" * 40]


def _fixed(outcome: RecheckOutcome) -> Any:
    async def _recheck_stub(*_args: Any, **_kwargs: Any) -> RecheckOutcome:
        return outcome

    return _recheck_stub


def test_the_recheck_module_names_its_public_surface() -> None:
    assert set(reapproval_recheck.__all__) == {"RecheckOutcome", "run_deterministic_recheck"}
    assert replace(RecheckOutcome(clean=True), ran=("x",)).ran == ("x",)
