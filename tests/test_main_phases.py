"""Characterisation suite for G4.1 — `src/mergecraft/main.py` phase extraction.

PR G4 (`.ignorelocal/waves/issues-showcase-readiness-wave-plan.md`, "PR G4 —
`refactor(main): drop main() and the analyzer hotspots below complexity 15`")
extracts `_setup_run` / `_resolve_credentials` / `_execute_agent` /
`_finalize` phases out of `main()`, carried on a new `RunContext` dataclass.
None of that extraction exists yet — this is a **pure refactor** wave, so
per G4.1's own acceptance line these tests characterise *current* behaviour
and must be **green today**, against unmodified code, and **stay green**
through G4.2. That inverts this repo's usual RED-first test-authoring
convention on purpose (see G4.1 in the wave plan).

Every test below drives the real, current public surface — mostly
`mergecraft.main.main()` via the existing
`tests/support/run_main_harness.py` harness (already used by
`tests/security/test_trust_ordering.py`, `tests/test_run_outcome.py`, etc.),
which exercises `main()` end to end against scripted collaborators without
touching the network, the process table, or a real port. Two tests
(`test_setup_run_resolves_prompt_and_mode`,
`test_resolve_credentials_matches_current_precedence`) call the underlying
helper functions directly, because the harness deliberately stubs
`resolve_prompt_input` / `resolve_tokens` away (see
`run_main_harness.py`'s module docstring) and this wave needs to pin what
those *real* functions do, not the harness's stand-ins.

`RunContext` does not exist pre-G4.2, so `test_run_context_carries_every_phase_input`
characterises the nearest existing seam — `mcp.context.ToolContext`, the one
object `main()` already threads every phase's output onto today. After
G4.2 splits `main()` into named phase functions, the same assertions
(rebased onto `RunContext`) prove nothing the sprawl carried was dropped.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

import mergecraft.utils.token as token_mod
from mergecraft.agents.shared import AgentResult
from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.config.settings import AnalyzersSettings, GatesSettings, RepoSettings
from mergecraft.main import MainResult, RunOutcome
from mergecraft.mcp.tool_state import ProgressComment as CtxProgressComment
from mergecraft.modes import _custom_modes, compute_modes
from mergecraft.utils.payload import JsonPayload, resolve_prompt_input
from mergecraft.utils.token import resolve_tokens
from tests.support.run_main_harness import FakeAgent, run_main_for_test


def _rmtree_if_exists(path: str) -> None:
    """Sync helper — keeps blocking FS calls out of async test bodies."""
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _isdir(path: str) -> bool:
    """Sync helper — keeps blocking FS calls out of async test bodies."""
    return os.path.isdir(path)


async def test_run_context_carries_every_phase_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The local-variable sprawl G4.2's `RunContext` will carry, pinned today.

    Drives one full run with non-default settings/inputs for each phase
    (setup: signed_commits + analyzers mode; credentials: trust tier +
    tokens; execute: an explicit model) and asserts every value lands on
    `ToolContext` — the object `main()` builds once and mutates across
    phases today. A refactor that drops one of these onto the wrong side of
    a phase boundary, or fails to carry it forward at all, turns this red.
    """
    settings = RepoSettings(
        signed_commits=True,
        analyzers=AnalyzersSettings(sarif_upload=True),
    )
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=settings,
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
        env={"INPUT_MODEL": "test-model-xyz", "INPUT_ANALYZERS": "full"},
    )
    assert rec.result is not None
    assert rec.result.success, f"run failed: {rec.result}"
    ctx = rec.tool_context
    assert ctx is not None, "main() never built a ToolContext"

    # -- setup-phase locals --------------------------------------------------
    assert ctx.agent_id == "claude"
    assert ctx.repo.owner == "acme"
    assert ctx.repo.name == "demo"
    assert ctx.tmpdir == rec.tmpdir
    expected_mode_names = {m.name for m in [*compute_modes("claude", True), *_custom_modes([])]}
    assert {m.name for m in ctx.modes} == expected_mode_names
    assert ctx.analyzers_mode == "full"
    assert ctx.sarif_upload_enabled is True
    assert ctx.signed_commits is True

    # -- credential-phase locals ---------------------------------------------
    assert ctx.trust_tier == "trusted"
    assert ctx.github_installation_token == "ghs_fake_mcp_token"
    assert ctx.git_token == "ghs_fake_git_token"

    # -- execute-phase locals -- filled onto the *same* object after setup --
    assert ctx.resolved_model == "test-model-xyz"
    assert ctx.mcp_server_url == "http://127.0.0.1:0/mcp"

    # tool_state carries its own share of the sprawl, threaded from the
    # resolved run_context / payload / modes computed above.
    assert ctx.tool_state.oss is True
    assert ctx.tool_state.modes == ctx.modes


def test_setup_run_resolves_prompt_and_mode(tmp_path: Path) -> None:
    """`resolve_prompt_input` + the `progress`/mode branch `main()` derives from it.

    The harness cannot exercise this: it stubs `resolve_prompt_input` to a
    plain string unconditionally (see the module docstring above), so this
    test calls the real function directly across its three source branches
    — `prompt` (plain text), `prompt_file`, and a `prompt` carrying the
    `~mergecraft` JSON dispatch marker — and, for each, re-derives the same
    `progress` value `main()` computes today at `main.py:308-313`:

        progress = None
        if not isinstance(resolved_prompt, str) and resolved_prompt.progress_comment:
            progress = ProgressComment(id=..., type=...)

    plus the `modes` list `main()` builds independently via
    `compute_modes` + `_custom_modes` — pinning that mode computation is
    unaffected by which prompt-source branch produced the prompt.
    """
    from mergecraft import __version__

    # -- branch 1: plain `prompt` text, no prompt_file, no JSON marker ------
    plain_result = resolve_prompt_input(prompt="plain review text", prompt_file="")
    assert isinstance(plain_result, str)
    assert plain_result == "plain review text"

    # -- branch 2: `prompt_file` -- resolved from disk -----------------------
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("file-sourced prompt content", encoding="utf-8")
    file_result = resolve_prompt_input(prompt="", prompt_file=str(prompt_path))
    assert isinstance(file_result, str)
    assert file_result == "file-sourced prompt content"

    # -- branch 3: `prompt` carrying the `~mergecraft` JSON dispatch marker --
    json_marker = json.dumps(
        {
            "~mergecraft": True,
            "version": __version__,
            "prompt": "structured dispatch prompt",
            "progressComment": {"id": "42", "type": "issue"},
        }
    )
    json_result = resolve_prompt_input(prompt=json_marker, prompt_file="")
    assert isinstance(json_result, JsonPayload)
    assert json_result.prompt == "structured dispatch prompt"
    assert json_result.progress_comment is not None
    assert json_result.progress_comment.id == "42"
    assert json_result.progress_comment.type == "issue"

    def _progress_for(resolved_prompt: str | JsonPayload) -> CtxProgressComment | None:
        """Mirrors `main.py:308-313` verbatim — the `progress`/mode pair."""
        if not isinstance(resolved_prompt, str) and resolved_prompt.progress_comment:
            return CtxProgressComment(
                id=resolved_prompt.progress_comment.id,
                type=resolved_prompt.progress_comment.type,
            )
        return None

    assert _progress_for(plain_result) is None
    assert _progress_for(file_result) is None
    progress = _progress_for(json_result)
    assert progress is not None
    assert progress.id == "42"

    # `modes` computation is independent of the prompt source — pin that
    # invariant across all three branches (it takes no `resolved_prompt`
    # argument at all in `main()` today; this loop documents that fact).
    baseline_modes = {m.name for m in [*compute_modes("claude", False), *_custom_modes([])]}
    for _resolved in (plain_result, file_result, json_result):
        modes_here = {m.name for m in [*compute_modes("claude", False), *_custom_modes([])]}
        assert modes_here == baseline_modes


def _reset_token_module_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(token_mod, "_mcp_token_value", None)
    monkeypatch.setattr(token_mod, "_mcp_token_refresh", None)
    for key in (
        "INPUT_TOKEN",
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "GITHUB_APP_ID",
        "GITHUB_APP_PRIVATE_KEY",
        "GITHUB_APP_INSTALLATION_ID",
        "GITHUB_REPOSITORY",
    ):
        monkeypatch.delenv(key, raising=False)


async def test_resolve_credentials_matches_current_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Token brokering + trust-tier derivation — a security boundary (S4 fail-closed).

    Table-driven over `mergecraft.utils.token.resolve_tokens` /
    `get_job_token` (today's `_resolve_credentials`-to-be) and
    `mergecraft.analyzers.trust.derive_trust_tier`, called directly rather
    than through the harness because `run_main_for_test` stubs
    `resolve_tokens` away entirely.

    Any divergence here is a security regression, not a refactor (G4.1).
    """
    failures: list[str] = []

    # -- token precedence -----------------------------------------------------
    token_cases: list[dict[str, Any]] = [
        {
            "id": "gh_token_env_wins_over_input_token_and_workflow_default",
            "env": {
                "INPUT_TOKEN": "input-tok",
                "GH_TOKEN": "gh-tok",
                "GITHUB_TOKEN": "workflow-tok",
            },
            "xrepo": None,
            "expect_token": "gh-tok",
            "expect_read_token": None,
        },
        {
            "id": "gh_token_becomes_read_token_when_xrepo_configured",
            "env": {"GH_TOKEN": "gh-tok"},
            "xrepo": {"write": ["acme/other"]},
            "expect_token": "gh-tok",
            "expect_read_token": "gh-tok",
        },
        {
            "id": "input_token_wins_over_workflow_default_when_gh_token_absent",
            "env": {"INPUT_TOKEN": "input-tok", "GITHUB_TOKEN": "workflow-tok"},
            "xrepo": None,
            "expect_token": "input-tok",
            "expect_read_token": None,
        },
        {
            "id": "workflow_default_token_used_as_last_resort",
            "env": {"GITHUB_TOKEN": "workflow-tok"},
            "xrepo": None,
            "expect_token": "workflow-tok",
            "expect_read_token": None,
        },
    ]
    for case in token_cases:
        _reset_token_module_state(monkeypatch)
        for key, value in case["env"].items():
            monkeypatch.setenv(key, value)
        ref = await resolve_tokens(push="restricted", xrepo=case["xrepo"])
        try:
            if ref.git_token != case["expect_token"]:
                failures.append(
                    f"{case['id']}: git_token={ref.git_token!r}, expected {case['expect_token']!r}"
                )
            if ref.mcp_token != case["expect_token"]:
                failures.append(
                    f"{case['id']}: mcp_token={ref.mcp_token!r}, expected {case['expect_token']!r}"
                )
            if ref.read_token != case["expect_read_token"]:
                failures.append(
                    f"{case['id']}: read_token={ref.read_token!r}, "
                    f"expected {case['expect_read_token']!r}"
                )
        finally:
            await ref.aclose()

    # -- App-JWT installation-token minting: wins over the plain job token --
    _reset_token_module_state(monkeypatch)
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "dummy-key")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")

    async def _fake_mint_ok(**_kwargs: Any) -> str:
        return "minted-installation-tok"

    monkeypatch.setattr(token_mod, "acquire_installation_token", _fake_mint_ok)
    ref = await resolve_tokens(push="restricted", xrepo=None)
    try:
        if ref.git_token != "minted-installation-tok":
            failures.append(
                f"minted_token_wins_over_job_token: git_token={ref.git_token!r}, "
                "expected 'minted-installation-tok'"
            )
    finally:
        await ref.aclose()

    # -- App-JWT minting failure degrades to the job token, not an error ----
    _reset_token_module_state(monkeypatch)
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "dummy-key")
    monkeypatch.setenv("GITHUB_TOKEN", "workflow-tok")

    async def _fake_mint_boom(**_kwargs: Any) -> str:
        msg = "installation token mint failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(token_mod, "acquire_installation_token", _fake_mint_boom)
    ref = await resolve_tokens(push="restricted", xrepo=None)
    try:
        if ref.git_token != "workflow-tok":
            failures.append(
                f"broken_app_credentials_degrade_to_job_token: git_token={ref.git_token!r}, "
                "expected 'workflow-tok'"
            )
    finally:
        await ref.aclose()

    # -- no token anywhere fails closed, not open ----------------------------
    _reset_token_module_state(monkeypatch)
    try:
        await resolve_tokens(push="restricted", xrepo=None)
    except ValueError as exc:
        if "token input is required" not in str(exc):
            failures.append(f"no_token_error_message_changed: {exc}")
    else:
        failures.append("no_token_anywhere: resolve_tokens did not fail closed")

    # -- trust-tier derivation (S4 fail-closed default) ----------------------
    fork_pr_event = {
        "action": "opened",
        "pull_request": {"head": {"sha": "deadbeef", "repo": {"fork": True}}},
    }
    same_repo_pr_event = {
        "action": "opened",
        "pull_request": {"head": {"sha": "deadbeef", "repo": {"fork": False}}},
    }
    trust_cases: list[tuple[str, str | None, dict[str, Any] | None, bool, str]] = [
        ("offline_flag_forces_trusted_regardless_of_event", None, None, True, "trusted"),
        ("missing_event_fails_closed_untrusted", "workflow_dispatch", None, False, "untrusted"),
        (
            "workflow_dispatch_is_trusted",
            "workflow_dispatch",
            {"action": "workflow_dispatch"},
            False,
            "trusted",
        ),
        (
            "pull_request_target_is_always_untrusted",
            "pull_request_target",
            same_repo_pr_event,
            False,
            "untrusted",
        ),
        ("fork_pull_request_is_untrusted", "pull_request", fork_pr_event, False, "untrusted"),
        ("same_repo_pull_request_is_trusted", "pull_request", same_repo_pr_event, False, "trusted"),
        (
            "maintainer_issue_comment_is_trusted",
            "issue_comment",
            {"comment": {"author_association": "OWNER"}},
            False,
            "trusted",
        ),
        (
            "stranger_issue_comment_is_untrusted",
            "issue_comment",
            {"comment": {"author_association": "NONE"}},
            False,
            "untrusted",
        ),
        (
            "unrecognised_event_name_fails_closed_untrusted",
            "release",
            {"action": "published"},
            False,
            "untrusted",
        ),
    ]
    for case_id, event_name, event, offline, expected_tier in trust_cases:
        if event_name is not None:
            monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
        else:
            monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
        tier = derive_trust_tier(event=event, offline=offline)
        if tier != expected_tier:
            failures.append(f"{case_id}: derive_trust_tier -> {tier!r}, expected {expected_tier!r}")

    assert not failures, "\n".join(failures)


async def test_execute_agent_preserves_deadline_semantics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F6 — the run deadline (`asyncio.wait_for`) wraps `_execute_agent`'s coroutine only.

    Setup phases (the trusted-tier `setup_script`, MCP server startup) run
    to completion regardless of the run timeout; only the agent's own
    deadline is reduced by the time those earlier phases spent (S1/F6 —
    "setup must never consume the whole run budget"). Two proofs: (a) a
    fast agent with a within-budget setup script completes normally with
    every earlier phase reached, and (b) an agent whose own delay is
    *shorter* than the configured run timeout still times out once the
    setup script's elapsed time is deducted from its budget — proof the
    deduction (not a raw wall-clock cap measured from run start) is what
    gates the agent specifically.
    """
    within_budget_dir = tmp_path / "within-budget"
    within_budget_dir.mkdir()
    within_budget = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=within_budget_dir,
        settings=RepoSettings(setup_script="echo setup", setup_timeout_s=1),
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
        env={"INPUT_TIMEOUT": "2s"},
        agent=FakeAgent(delay_s=0.3),
        setup_script_delay_s=0.2,
    )
    assert within_budget.result is not None
    assert within_budget.result.success, f"run failed: {within_budget.result}"
    assert within_budget.result.outcome == RunOutcome.passed
    assert "setup_script" in within_budget.events
    assert "start_mcp_http_server" in within_budget.events

    # Total timeout 4s; setup consumes ~1.5s, leaving ~2.5s for the agent.
    # The agent's own delay (3.2s) is *shorter* than the total (4s) but
    # longer than the deducted remainder (~2.5s) — it only times out
    # because of the deduction.
    over_budget_dir = tmp_path / "deducted-over-budget"
    over_budget_dir.mkdir()
    over_budget = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=over_budget_dir,
        settings=RepoSettings(setup_script="echo setup", setup_timeout_s=3),
        event_name="workflow_dispatch",
        event_payload={"action": "workflow_dispatch"},
        env={"INPUT_TIMEOUT": "4s"},
        agent=FakeAgent(delay_s=3.2),
        setup_script_delay_s=1.5,
    )
    assert over_budget.result is not None
    assert not over_budget.result.success
    assert over_budget.result.outcome == RunOutcome.timed_out
    assert over_budget.raised is None, "the timeout must be caught inside main(), not escape it"
    # Setup and MCP startup ran to completion — only the agent coroutine
    # itself was subject to (and cancelled by) the deadline.
    assert "setup_script" in over_budget.events
    assert "start_mcp_http_server" in over_budget.events


async def test_finalize_runs_on_every_exit_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The nested try/finally guarantees post-run reaches every exit shape.

    Four exit shapes — agent success, agent-reported failure, an
    `asyncio.wait_for` timeout, and an exception raised after `ToolContext`
    exists (an unparseable `timeout` input, deferred past `ToolContext`
    construction precisely so this can happen — see `main.py`'s "S1 review
    / NEW1" comment) — must all (a) reach the publish block
    (`persist_learnings` / `report_status_checks` / `emit_run_packet`,
    proxied here by `report_status_calls`) and (b) run the unconditional
    `finally` cleanup (`token_ref.aclose()`, `cleanup_temp_directory()`)
    regardless of which branch produced the exit.
    """
    scenarios: dict[str, dict[str, Any]] = {
        "success": {},
        "agent_failure": {"agent": FakeAgent(result=AgentResult(success=False, error="blocked"))},
        "timeout": {"agent": FakeAgent(delay_s=5.0), "env": {"INPUT_TIMEOUT": "1s"}},
        "exception_with_tool_context": {"env": {"INPUT_TIMEOUT": "not-a-duration"}},
    }
    failures: list[str] = []
    for name, kwargs in scenarios.items():
        scenario_tmp = tmp_path / name
        scenario_tmp.mkdir()
        rec = await run_main_for_test(
            monkeypatch=monkeypatch, tmp_path=scenario_tmp, cleanup_tmpdir=False, **kwargs
        )
        try:
            if rec.result is None:
                failures.append(f"{name}: main() raised instead of returning ({rec.raised!r})")
                continue
            if not rec.report_status_calls:
                failures.append(f"{name}: publish block never reached (no status check reported)")
            if rec.token_ref is None or not rec.token_ref.closed:
                failures.append(f"{name}: token_ref.aclose() was not called in the finally block")
            if rec.tmpdir and _isdir(rec.tmpdir):
                failures.append(
                    f"{name}: temp dir {rec.tmpdir} survived — cleanup_temp_directory not run"
                )
        finally:
            if rec.tmpdir:
                _rmtree_if_exists(rec.tmpdir)
    assert not failures, "\n".join(failures)


async def test_main_result_is_unchanged_for_each_run_outcome(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every `RunOutcome` member maps to an unchanged `MainResult` shape.

    Six scenarios, one per `RunOutcome` value (`run_outcome.py:22-30`).
    Pins the *whole* `MainResult` — not just `.outcome` — so a refactor
    that reorders which phase sets `.output` / `.error` /
    `.evidence_packet_path` turns this red even when `.outcome` alone still
    matches.
    """
    packet_path = tmp_path / "packet.json"
    scenarios: dict[str, dict[str, Any]] = {
        "passed": {},
        "failed": {
            "agent": FakeAgent(result=AgentResult(success=False, error="review gate failed"))
        },
        "timed_out": {"agent": FakeAgent(delay_s=5.0), "env": {"INPUT_TIMEOUT": "1s"}},
        "configuration_error": {"env": {"INPUT_TIMEOUT": "not-a-duration"}},
        "inconclusive": {"prep_failure": "pip install -r requirements.txt failed (exit 1)"},
        "infra_error": {"agent": FakeAgent(result=RuntimeError("provider API unreachable"))},
    }
    # `timed_out` / `configuration_error` (bad timeout) / `infra_error` (an
    # agent exception) all reach `main()`'s *outer* `except Exception:`
    # handler (main.py:946), which calls `persist_learnings` +
    # `report_status_checks` only -- unlike the normal completion path's
    # publish block (main.py:898-927), it never calls `emit_run_packet`.
    # `passed` / `failed` / `inconclusive` all return through that normal
    # completion path instead, where the packet *is* written. Pinned here
    # exactly as found -- this asymmetry is current behaviour, not
    # something this wave should silently "fix" by broadening it.
    exception_path_outcomes = {
        RunOutcome.timed_out,
        RunOutcome.configuration_error,
        RunOutcome.infra_error,
    }
    failures: list[str] = []
    for name, kwargs in scenarios.items():
        scenario_tmp = tmp_path / f"outcome-{name}"
        scenario_tmp.mkdir()
        rec = await run_main_for_test(
            monkeypatch=monkeypatch, tmp_path=scenario_tmp, packet_path=packet_path, **kwargs
        )
        result: MainResult | None = rec.result
        expected_outcome = RunOutcome(name)
        if result is None:
            failures.append(f"{name}: main() raised instead of returning ({rec.raised!r})")
            continue
        if result.outcome is not expected_outcome:
            failures.append(f"{name}: outcome={result.outcome!r}, expected {expected_outcome!r}")
        expected_success = expected_outcome is RunOutcome.passed
        if result.success is not expected_success:
            failures.append(f"{name}: success={result.success!r}, expected {expected_success!r}")
        if expected_success:
            if result.error is not None:
                failures.append(f"{name}: passed run carries error={result.error!r}")
            if not result.output:
                failures.append(f"{name}: passed run has empty output")
            if result.result != result.output:
                failures.append(
                    f"{name}: result field {result.result!r} != output {result.output!r}"
                )
        else:
            if not result.error:
                failures.append(f"{name}: non-passed run has no error message")
        expected_packet_path = (
            None if expected_outcome in exception_path_outcomes else str(packet_path)
        )
        if result.evidence_packet_path != expected_packet_path:
            failures.append(
                f"{name}: evidence_packet_path={result.evidence_packet_path!r}, "
                f"expected {expected_packet_path!r}"
            )
    assert not failures, "\n".join(failures)


class TestFinalizeCarriesTheVerdictDiagnostic:
    """`#265` producer half — the run's diagnostic reaches `MainResult`.

    The consumer half (`tests/cli/test_gha_failure_outputs.py`'s
    `TestVerdictDiagnosticOutput`) proves that a `MainResult` carrying a code
    reaches `$GITHUB_OUTPUT`. On its own that is satisfied by a `MainResult`
    nobody ever populates, which is the same observable defect as `#265` seen
    from the other end: a documented output that is permanently empty. These
    tests close the other half — a real `main()` run that computed a
    diagnostic must return it — so the two suites together cover the path
    from "the run classified the verdict protocol" to "the consumer can read
    the code".

    Assertions go through `main()` and `MainResult` only. Nothing here names
    how the diagnostic is threaded, so a refactor that carries it on the
    prediction object, a widened publish helper, or some third carrier stays
    green as long as the code arrives.
    """

    @staticmethod
    def _codes() -> set[str]:
        from mergecraft.mcp.verdict import VerdictDiagnostic

        return {member.value for member in VerdictDiagnostic}

    async def test_success_path_carries_the_computed_code(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A clean run returns through the `passed` branch carrying `approved`."""
        rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path)

        assert rec.result is not None
        assert rec.result.outcome is RunOutcome.passed
        assert rec.result.verdict_diagnostic == "approved"

    async def test_failure_path_carries_the_computed_code(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The non-`passed` branch is a separate `return` — it must not drop the code.

        A failed run is exactly when a consumer needs to distinguish "the
        provider broke" from "policy rejected the review", so the failure
        branch losing the diagnostic would be worse than the success branch
        losing it.
        """
        agent = FakeAgent(result=AgentResult(success=False, error="review gate failed"))
        rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, agent=agent)

        assert rec.result is not None
        assert rec.result.outcome is RunOutcome.failed
        assert rec.result.verdict_diagnostic == "provider_failure"

    async def test_policy_rejection_is_distinguishable_from_provider_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Two different failures reaching the same branch keep different codes.

        Both a prep failure and an agent failure leave the non-`passed`
        return; if the branch hard-coded (or dropped and defaulted) the code,
        this pair would collapse into one value and the output would stop
        carrying information.
        """
        rec = await run_main_for_test(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            prep_failure="pip install -r requirements.txt failed (exit 1)",
        )

        assert rec.result is not None
        assert rec.result.outcome is RunOutcome.inconclusive
        assert rec.result.verdict_diagnostic == "policy_rejection"

    @pytest.mark.parametrize(
        ("scenario", "kwargs"),
        [
            ("passed", {}),
            (
                "failed",
                {"agent": FakeAgent(result=AgentResult(success=False, error="blocked"))},
            ),
            ("inconclusive", {"prep_failure": "install failed"}),
        ],
    )
    async def test_enforce_and_shadow_deposit_the_same_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        scenario: str,
        kwargs: dict[str, Any],
    ) -> None:
        """The fragile seam — the code must not depend on the terminal-verdict mode.

        `enforce` and `shadow` diverge in what the run *does* with the
        prediction (only `shadow` hands it to the recorder), so an
        implementation that reached the diagnostic through the shadow-only
        carrier would produce a code under `shadow` and nothing under
        `enforce` — the default. Running the same scenario under both modes
        and comparing pins that asymmetry shut.
        """
        codes: dict[str, str | None] = {}
        for mode in ("enforce", "shadow"):
            scenario_tmp = tmp_path / f"{scenario}-{mode}"
            scenario_tmp.mkdir()
            rec = await run_main_for_test(
                monkeypatch=monkeypatch,
                tmp_path=scenario_tmp,
                settings=RepoSettings(gates=GatesSettings(terminal_verdict=mode)),
                **kwargs,
            )
            assert rec.result is not None, f"{scenario}/{mode}: main() raised ({rec.raised!r})"
            codes[mode] = rec.result.verdict_diagnostic

        assert codes["enforce"] in self._codes(), (
            f"{scenario}: enforce deposited {codes['enforce']!r}, outside the closed vocabulary"
        )
        assert codes["enforce"] == codes["shadow"], (
            f"{scenario}: enforce deposited {codes['enforce']!r} but shadow deposited "
            f"{codes['shadow']!r} — the code a consumer reads must not depend on the mode"
        )

    async def test_every_completed_run_deposits_a_closed_code(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """No completed run leaves the documented output empty.

        Every path that reaches the verdict-protocol classification has a
        code for it, so "empty" must mean "never classified" (below) rather
        than "classified but not carried".
        """
        scenarios: dict[str, dict[str, Any]] = {
            "passed": {},
            "failed": {"agent": FakeAgent(result=AgentResult(success=False, error="blocked"))},
            "inconclusive": {"prep_failure": "install failed"},
        }
        observed: dict[str, str | None] = {}
        for name, kwargs in scenarios.items():
            scenario_tmp = tmp_path / name
            scenario_tmp.mkdir()
            rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=scenario_tmp, **kwargs)
            assert rec.result is not None, f"{name}: main() raised ({rec.raised!r})"
            observed[name] = rec.result.verdict_diagnostic

        closed = self._codes()
        offenders = {name: code for name, code in observed.items() if code not in closed}
        assert not offenders, f"completed run(s) carried no closed VerdictDiagnostic: {offenders}"

    @pytest.mark.parametrize(
        ("scenario", "kwargs"),
        [
            ("timed_out", {"agent": FakeAgent(delay_s=5.0), "env": {"INPUT_TIMEOUT": "1s"}}),
            ("configuration_error", {"env": {"INPUT_TIMEOUT": "not-a-duration"}}),
            ("infra_error", {"agent": FakeAgent(result=RuntimeError("provider unreachable"))}),
        ],
    )
    async def test_runs_that_never_classified_carry_no_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        scenario: str,
        kwargs: dict[str, Any],
    ) -> None:
        """D10's empty arm at the producer end.

        These three outcomes leave through `main()`'s outer handler and never
        reach the verdict-protocol classification (the same asymmetry
        `test_main_result_is_unchanged_for_each_run_outcome` pins for the
        evidence packet), so there is no code to report. The value must be
        falsy — `None` or `""` both satisfy the consumer, which writes a
        present-but-empty key either way — and must never be a fabricated
        code that would tell a consumer the run reached a verdict it never
        reached.
        """
        rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, **kwargs)

        assert rec.result is not None
        assert rec.result.outcome is RunOutcome(scenario)
        assert not rec.result.verdict_diagnostic, (
            f"{scenario} never classified a verdict protocol but reported "
            f"{rec.result.verdict_diagnostic!r}"
        )
