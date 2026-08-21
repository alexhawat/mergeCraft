"""W2 DA RED — #378 first-finding stream, cache, resume, reusable goldens.

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md``
Authoring wave: **W2**. Implementation: **W4**.

Pins the gap: findings are dumped only after the review returns (see
``_emit_agent_protocol`` in ``src/mergecraft/cli/diff_review_cmd.py``). W4 must
stream the first useful finding before the full verdict, add resume +
cancellation cleanup, and land reusable CLI goldens under ``tests/cli/goldens/``
(file 8 RV5 extends those fixtures). D11: do not invent a second stdout/stderr
split — goldens are JSONL / named-exit CLI output.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from typer.testing import CliRunner

from mergecraft.cli.agent_protocol import AgentProtocolStream
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.offline_review import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    import pytest

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

_CLI_DIR = Path(__file__).resolve().parent
_GOLDENS_DIR = _CLI_DIR / "goldens"
_FIRST_FINDING_GOLDEN = _GOLDENS_DIR / "review_first_finding.jsonl"

_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _finding_dict() -> dict[str, object]:
    return {
        "tool": "mergecraft-agent",
        "rule_id": "AGENT-378",
        "category": "Maintainability & Code Quality",
        "severity": "Minor",
        "confidence": "likely",
        "message": "first useful finding",
        "path": "demo.py",
        "start_line": 1,
        "end_line": 1,
        "source": "agent",
        "introduced_by_pr": "unknown",
    }


def _install_agent_review(
    monkeypatch: pytest.MonkeyPatch,
    *,
    on_enter: Any | None = None,
    on_exit: Any | None = None,
) -> None:
    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        if on_enter is not None:
            on_enter()
        try:
            materialization_path = kwargs.get("diff_file")
            diff_path = str(materialization_path) if materialization_path else None
            finding = _finding_dict()
            callback = kwargs.get("on_finding")
            if callable(callback):
                callback(finding)
            payload = json.dumps({"findings": [finding]})
            return OfflineReviewResult(
                success=True,
                output="# Review\n\nOK.",
                structured_output=payload,
                diff_path=diff_path,
                outcome=RunOutcome.passed,
            )
        finally:
            if on_exit is not None:
                on_exit()

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
        env=_DUMB_ENV,
        catch_exceptions=False,
    )


def test_first_finding_emits_while_review_is_still_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: the first useful finding is streamed before ``run_offline_diff_review`` returns."""
    review_active = {"value": False}
    finding_during_review = {"value": False}
    original_finding = AgentProtocolStream.finding

    def wrapped_finding(
        self: AgentProtocolStream,
        finding: dict[str, Any],
        **payload: Any,
    ) -> None:
        if review_active["value"]:
            finding_during_review["value"] = True
        original_finding(self, finding, **payload)

    monkeypatch.setattr(AgentProtocolStream, "finding", wrapped_finding)
    _install_agent_review(
        monkeypatch,
        on_enter=lambda: review_active.__setitem__("value", True),
        on_exit=lambda: review_active.__setitem__("value", False),
    )
    _invoke_agent(tmp_path)
    assert finding_during_review["value"] is True


def test_review_help_documents_resume() -> None:
    """Happy: ``mergecraft review --resume`` is part of the documented review path."""
    result = runner.invoke(app, ["review", "--help"], env=_DUMB_ENV)
    help_text = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "--resume" in help_text


def test_review_help_documents_result_cache_beyond_cache_typer() -> None:
    """Happy: review has a result cache distinct from the ``mergecraft cache`` typer (CC4)."""
    result = runner.invoke(app, ["review", "--help"], env=_DUMB_ENV)
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "--use-cache" in help_text or "result-cache" in help_text or "result cache" in help_text


def test_diff_review_cmd_exposes_cancellation_subprocess_cleanup() -> None:
    """Error/edge: cancelling a review cleans up child subprocesses (no leak)."""
    from mergecraft.cli import diff_review_cmd

    cleanup = getattr(diff_review_cmd, "cleanup_review_subprocesses", None)
    assert callable(cleanup)


def test_reusable_cli_golden_for_first_finding_exists() -> None:
    """Functional: reusable CLI golden under ``tests/cli/goldens/`` (file 8 RV5 extends it).

    D11 — the golden is JSONL agent/CLI output, not a second stdout/stderr split.
    """
    assert _GOLDENS_DIR.is_dir()
    assert _FIRST_FINDING_GOLDEN.is_file()
    lines = [
        line
        for line in _FIRST_FINDING_GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert lines, "golden must contain at least one JSONL event"
    events = [json.loads(line) for line in lines]
    kinds = [event.get("event") for event in events]
    assert "finding" in kinds
    finding_index = kinds.index("finding")
    if "verdict" in kinds:
        assert finding_index < kinds.index("verdict")
    first_finding = events[finding_index]
    assert "stdout_stream" not in first_finding
    assert "stderr_stream" not in first_finding
