"""CC1 — agent JSONL protocol (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Pins ``--agent`` streaming events for orchestrators consuming reviews line-by-line.
Authoring wave: **CC1.1** (RED). Implementation: **CC1.2**.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from tests.analyzers.support import import_module as import_analyzer_module
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.offline_review import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _agent_protocol_mod() -> Any:
    return import_analyzer_module("mergecraft.cli.agent_protocol")


def _protocol_version() -> str:
    mod = _agent_protocol_mod()
    version = getattr(mod, "AGENT_PROTOCOL_VERSION", None)
    if version is None:
        pytest.fail("AGENT_PROTOCOL_VERSION not defined in mergecraft.cli.agent_protocol")
    return str(version)


def _finding_dict() -> dict[str, object]:
    finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="mergecraft-agent",
        rule_id="AGENT-2",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="nit",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="unknown",
    )
    return finding.model_dump()


def _install_agent_review(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        materialization_path = kwargs.get("diff_file")
        diff_path = str(materialization_path) if materialization_path else None
        findings = [_finding_dict()]
        payload = json.dumps({"findings": findings})
        return OfflineReviewResult(
            success=True,
            output="# Review\n\nOK.",
            structured_output=payload,
            diff_path=diff_path,
            outcome=RunOutcome.passed,
        )

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )


def _invoke_agent(tmp_path: Path) -> Any:
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    return runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--agent"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
        catch_exceptions=False,
    )


def _parse_agent_lines(stdout: str) -> list[dict[str, Any]]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_events_carry_protocol_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every emitted event carries an explicit ``protocol_version``."""
    _install_agent_review(monkeypatch)
    result = _invoke_agent(tmp_path)
    events = _parse_agent_lines(result.stdout)
    assert events
    version = _protocol_version()
    for event in events:
        assert event.get("protocol_version") == version


def test_event_sequence_is_run_started_then_phases_then_verdict_then_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Events follow run_started → phase(s) → verdict → run_finished."""
    _install_agent_review(monkeypatch)
    result = _invoke_agent(tmp_path)
    events = _parse_agent_lines(result.stdout)
    kinds = [event.get("event") for event in events]
    assert kinds[0] == "run_started"
    assert kinds[-1] == "run_finished"
    assert "verdict" in kinds
    phase_indices = [idx for idx, kind in enumerate(kinds) if kind == "phase"]
    verdict_index = kinds.index("verdict")
    assert phase_indices, kinds
    assert all(idx < verdict_index for idx in phase_indices)


def test_findings_stream_before_the_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding events appear before the verdict event."""
    _install_agent_review(monkeypatch)
    result = _invoke_agent(tmp_path)
    events = _parse_agent_lines(result.stdout)
    kinds = [event.get("event") for event in events]
    finding_indices = [idx for idx, kind in enumerate(kinds) if kind == "finding"]
    verdict_index = kinds.index("verdict")
    assert finding_indices
    assert all(idx < verdict_index for idx in finding_indices)


def test_protocol_is_parseable_line_by_line_while_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A consumer can parse each stdout line without waiting for the full stream."""
    _install_agent_review(monkeypatch)
    result = _invoke_agent(tmp_path)
    parsed: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        parsed.append(json.loads(line))
    assert parsed
    assert parsed[0]["event"] == "run_started"
    assert parsed[-1]["event"] == "run_finished"


def test_global_format_json_with_agent_does_not_require_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root ``--format json`` must not require ``--output`` when ``--agent`` streams JSONL."""
    _install_agent_review(monkeypatch)
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            "review",
            "--diff",
            str(patch),
            "--cwd",
            str(tmp_path),
            "--agent",
        ],
        env={"NO_COLOR": "1", "TERM": "dumb"},
        catch_exceptions=False,
    )
    combined = _plain(result.stdout + result.stderr)
    assert "--output is required" not in combined.lower()
    events = _parse_agent_lines(result.stdout)
    assert events[0]["event"] == "run_started"
    assert result.exit_code == 10, combined


def test_agent_failure_routes_error_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--agent`` keeps stdout JSONL-only on failure; human errors go to stderr."""

    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        materialization_path = kwargs.get("diff_file")
        diff_path = str(materialization_path) if materialization_path else None
        return OfflineReviewResult(
            success=False,
            error="review failed",
            diff_path=diff_path,
            outcome=RunOutcome.failed,
        )

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )
    result = _invoke_agent(tmp_path)
    assert result.exit_code != 0
    assert result.stdout.strip()
    for line in result.stdout.splitlines():
        if line.strip():
            json.loads(line)
    assert "review failed" in _plain(result.stderr)
    assert "review failed" not in _plain(result.stdout)
