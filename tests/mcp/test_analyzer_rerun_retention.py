"""Partial analyzer reruns must not erase earlier blockers (RA1.4, N2/D9).

``_store_run_state`` replaces the whole ``AnalyzerRunState`` on every call, so a
clean re-run over a *different* covered scope discards findings the previous
pass produced for files it never looked at. Retention is keyed by
(immutable snapshot, analyzer, covered scope); a rerun supersedes only for an
equivalent covered scope. The terminal-approve guard is the consequence.
"""

from __future__ import annotations

import asyncio
import json
from itertools import permutations
from typing import TYPE_CHECKING, Any

import pytest
from tests.findings.support import make_finding

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        analyzers_settings_enabled=True,
        analyzers_mode="auto",
        trust_tier="trusted",
    )


def _row(fingerprint: str, severity: str) -> dict[str, Any]:
    return make_finding(
        tool="bandit",
        rule_id=f"rule-{fingerprint}",
        category="Security & Privacy",
        severity=severity,
        confidence="certain",
        message=f"finding {fingerprint}",
        path="bug.py",
        start_line=10,
        end_line=10,
        source="analyzer",
        fingerprint=fingerprint,
        introduced_by_pr="true",
    ).model_dump()


def _state(*fingerprints: tuple[str, str], ran: bool = True, reason: str | None = None) -> Any:
    return AnalyzerRunState(
        ran=ran,
        reason=reason,
        findings=[_row(fingerprint, severity) for fingerprint, severity in fingerprints],
    )


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Route every covered scope to a configured state; record the bug call count."""
    calls: dict[str, int] = {"bug": 0}
    controls: dict[str, Any] = {"docs": _state(), "unavailable": _state(ran=False, reason="none")}

    def _fake(**kwargs: Any) -> Any:
        changed = set(kwargs.get("changed_files") or [])
        if "bug.py" in changed:
            calls["bug"] += 1
            return _state(("major-bug", "Major")) if calls["bug"] == 1 else _state()
        if "docs.md" in changed:
            return controls["docs"]
        if "a.py" in changed:
            return _state(("fp-a", "Major"))
        if "b.py" in changed:
            return _state(("fp-b", "Major"))
        return _state(ran=False, reason="no analyzers matched")

    monkeypatch.setattr("mergecraft.analyzers.pipeline.run_analyzer_pipeline", _fake)
    return controls


async def _run(ctx: ToolContext, **params: Any) -> dict[str, Any]:
    from mergecraft.mcp.analyzers import run_analyzers_tool

    result = await run_analyzers_tool(ctx).execute(params)
    return json.loads(result.content[0]["text"])


async def _retained_fingerprints(ctx: ToolContext) -> set[str]:
    from mergecraft.mcp.analyzers import analyzer_findings_tool

    payload = json.loads((await analyzer_findings_tool(ctx).execute({})).content[0]["text"])
    return {row.get("fingerprint") for row in payload["findings"]}


@pytest.mark.asyncio
async def test_clean_partial_rerun_does_not_erase_a_prior_blocker(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    ctx = _ctx(tmp_path)
    await _run(ctx, changed_files=["bug.py"])
    assert await _retained_fingerprints(ctx) == {"major-bug"}

    await _run(ctx, changed_files=["docs.md"])

    assert "major-bug" in await _retained_fingerprints(ctx)


@pytest.mark.asyncio
async def test_same_scope_rerun_supersedes(tmp_path: Path, pipeline: dict[str, Any]) -> None:
    """A genuine rerun over the same covered scope replaces the earlier result."""
    ctx = _ctx(tmp_path)
    await _run(ctx, changed_files=["bug.py"])
    stored = ctx.tool_state.analyzer_run
    assert stored is not None
    stored.key = None  # force a fresh run rather than the reuse fast-path

    await _run(ctx, changed_files=["bug.py"])

    assert await _retained_fingerprints(ctx) == set()


@pytest.mark.asyncio
async def test_unavailable_analyzer_rerun_does_not_supersede(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    ctx = _ctx(tmp_path)
    await _run(ctx, changed_files=["bug.py"])
    pipeline["docs"] = pipeline["unavailable"]

    await _run(ctx, changed_files=["docs.md"])

    assert "major-bug" in await _retained_fingerprints(ctx)


@pytest.mark.asyncio
async def test_no_match_rerun_does_not_supersede(tmp_path: Path, pipeline: dict[str, Any]) -> None:
    ctx = _ctx(tmp_path)
    await _run(ctx, changed_files=["bug.py"])

    await _run(ctx, changed_files=["docs.md"])

    assert "major-bug" in await _retained_fingerprints(ctx)


@pytest.mark.asyncio
async def test_terminal_approve_stays_rejected_after_a_partial_clean_rerun(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    from mergecraft.mcp.verdict import validate_submission, validation_state_from_tool_state

    ctx = _ctx(tmp_path)
    await _run(ctx, changed_files=["bug.py"])
    blocking = validate_submission(
        {"verdict": "approve", "summary": "ok", "findings": []},
        state=validation_state_from_tool_state(ctx.tool_state),
    )
    assert blocking.accepted is False

    await _run(ctx, changed_files=["docs.md"])

    still = validate_submission(
        {"verdict": "approve", "summary": "ok", "findings": []},
        state=validation_state_from_tool_state(ctx.tool_state),
    )
    assert still.accepted is False, "a partial clean rerun cleared a prior blocker"


@pytest.mark.asyncio
async def test_concurrent_overlapping_runs_do_not_lose_findings(
    tmp_path: Path, pipeline: dict[str, Any]
) -> None:
    ctx = _ctx(tmp_path)

    await asyncio.gather(
        _run(ctx, changed_files=["a.py"]),
        _run(ctx, changed_files=["b.py"]),
    )

    fingerprints = await _retained_fingerprints(ctx)
    assert {"fp-a", "fp-b"} <= fingerprints


def test_overlapping_scopes_preserve_strongest_occurrence_in_every_order(tmp_path: Path) -> None:
    from mergecraft.agents.gates import decide_approval
    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.analyzers import _store_run_state
    from mergecraft.mcp.tool_state import analyzer_run_key

    states = []
    for index, severity in enumerate(["Minor", "Major", "Minor"]):
        row = _row("shared", severity)
        row["evidence"] = [f"scope-{index}"]
        key = analyzer_run_key(
            repo_root=tmp_path,
            changed_files=["bug.py", f"scope-{index}.py"],
            tier="trusted",
            shell="restricted",
            mode="auto",
            inline_budget=10,
            offline=True,
            base_ref="base",
            diff_text="diff",
        )
        states.append(
            AnalyzerRunState(
                ran=True,
                key=key,
                covered_scope=key,
                findings=[row],
                inline=[{"finding": row, "inlineBody": severity, "path": "bug.py", "line": 10}],
                deferred_findings=[
                    {
                        "fingerprint": "shared",
                        "severity": severity,
                        "path": "bug.py",
                        "line": 10,
                        "body": "same defect",
                    }
                ],
            )
        )
    reference = None
    for ordering in permutations(states):
        ctx = _ctx(tmp_path)
        for state in ordering:
            _store_run_state(ctx, state)
        result = ctx.tool_state.analyzer_run
        assert result is not None
        assert [row["severity"] for row in result.findings] == ["Major"]
        assert result.findings[0]["evidence"] == ["scope-0", "scope-1", "scope-2"]
        assert result.inline[0]["finding"]["severity"] == "Major"
        assert result.inline[0]["inlineBody"] == "Major"
        assert result.deferred_findings[0]["severity"] == "Major"
        assert (
            decide_approval(
                [Finding.model_validate(row) for row in result.findings],
                run_succeeded=True,
                tier="trusted",
            )
            == "failure"
        )
        output = (result.findings, result.inline, result.deferred_findings)
        assert reference is None or output == reference
        reference = output
