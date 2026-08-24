"""CD #453 RED — ``findings`` / ``explain`` / ``replay`` by stored review id (D4).

After a completed review, follow-up commands resolve from persisted artifacts
without re-running the review agent. No ``mergecraft session *`` namespace.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tests.review.support_durable_review import (
    require_callable,
    sample_fingerprint,
    sample_manifest,
    sample_review_id,
    sample_short_finding_id,
    sample_snapshot,
    sample_trace_events,
    seed_completed_review,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE
from mergecraft.offline_review import OfflineReviewResult

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _install_fake_review(monkeypatch: MonkeyPatch) -> None:
    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        materialization_path = kwargs.get("diff_file")
        diff_path = str(materialization_path) if materialization_path else None
        payload = json.dumps(
            {
                "findings": [
                    {
                        "tool": "ruff",
                        "rule_id": "F401",
                        "category": "Maintainability & Code Quality",
                        "severity": "Minor",
                        "confidence": "likely",
                        "message": "unused import os",
                        "path": "demo.py",
                        "start_line": 1,
                        "end_line": 1,
                        "source": "analyzer",
                        "introduced_by_pr": "unknown",
                        "fingerprint": sample_fingerprint(),
                    }
                ]
            }
        )
        json_path = kwargs.get("json_path")
        if json_path is not None:
            await asyncio.to_thread(
                Path(str(json_path)).write_text,
                payload,
                encoding="utf-8",
            )
        return OfflineReviewResult(
            success=True,
            output="# Review\n\nCompleted.",
            structured_output=payload,
            diff_path=diff_path,
        )

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )


def _guard_against_review_rerun(monkeypatch: MonkeyPatch) -> None:
    async def boom(**_kwargs: object) -> OfflineReviewResult:
        msg = "review agent must not rerun for durable lookup"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        boom,
    )


def test_review_persists_completed_review_id_on_success(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Happy — a successful ``mergecraft review`` leaves a durable review id behind."""
    review_id = sample_review_id()
    monkeypatch.setenv("MERGECRAFT_REVIEW_ID", review_id)
    _install_fake_review(monkeypatch)
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
        ],
        env={**_DUMB_ENV, "MERGECRAFT_REVIEW_ID": review_id},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    payload = json.loads(result.stdout)
    assert payload.get("review_id") == review_id
    from tests.review.support_durable_review import require_callable

    loaded = require_callable("load_completed_review")(review_id, repo_root=tmp_path)
    assert loaded is not None
    assert loaded.review_id == review_id


def test_findings_by_review_id_markdown_includes_short_id_and_severity(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Happy — stored rows with export-only short ids still render full markdown."""
    from mergecraft.cli.review_output import finding_json_records

    review_id = sample_review_id()
    finding_mod = __import__("mergecraft.analyzers.finding", fromlist=["make_finding"])
    finding = finding_mod.make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import os",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="analyzer",
        introduced_by_pr="unknown",
        fingerprint=sample_fingerprint(),
    )
    completed_cls = require_callable("CompletedReview")
    persist = require_callable("persist_completed_review")
    review = completed_cls(
        review_id=review_id,
        snapshot=sample_snapshot(),
        manifest=sample_manifest(),
        findings=finding_json_records([finding]),
        trace_session_id=review_id,
    )
    persist(review, repo_root=tmp_path, trace_events=sample_trace_events(review_id=review_id))
    _guard_against_review_rerun(monkeypatch)
    result = runner.invoke(
        app,
        ["findings", review_id, "--repo-root", str(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    assert sample_short_finding_id() in combined
    assert "Minor" in combined
    assert "F401" in combined


def test_findings_by_review_id_returns_stored_findings_without_rerun(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Happy — ``mergecraft findings <review-id>`` reads persisted findings only."""
    review_id = sample_review_id()
    seed_completed_review(tmp_path, review_id=review_id)
    _guard_against_review_rerun(monkeypatch)
    result = runner.invoke(
        app,
        ["--format", "json", "findings", review_id, "--repo-root", str(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    payload = json.loads(result.stdout)
    assert payload.get("review_id") == review_id
    findings = payload.get("findings")
    assert isinstance(findings, list)
    assert findings
    assert findings[0]["fingerprint"] == sample_fingerprint()


def test_explain_with_review_id_and_short_finding_id_resolves_packet(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Happy — ``mergecraft explain <review-id> MC-…`` resolves in review context."""
    review_id = sample_review_id()
    short_id = sample_short_finding_id()
    seed_completed_review(tmp_path, review_id=review_id)
    _guard_against_review_rerun(monkeypatch)
    result = runner.invoke(
        app,
        ["explain", review_id, short_id, "--repo-root", str(tmp_path), "--format", "json"],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    payload = json.loads(result.stdout)
    assert payload.get("review_id") == review_id
    assert payload.get("finding_id") == short_id
    packet = payload.get("packet")
    assert isinstance(packet, dict)
    assert packet.get("finding_id") == sample_fingerprint()


def test_explain_short_id_with_review_context_flag_resolves_packet(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Happy — ``mergecraft explain MC-… --review-id`` resolves without rerun."""
    review_id = sample_review_id()
    short_id = sample_short_finding_id()
    seed_completed_review(tmp_path, review_id=review_id)
    _guard_against_review_rerun(monkeypatch)
    result = runner.invoke(
        app,
        [
            "explain",
            short_id,
            "--review-id",
            review_id,
            "--repo-root",
            str(tmp_path),
            "--format",
            "json",
        ],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    payload = json.loads(result.stdout)
    assert payload.get("review_id") == review_id
    assert payload.get("finding_id") == short_id


def test_replay_by_review_id_uses_stored_artifacts_without_rerun(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Happy — ``mergecraft replay <review-id>`` replays stored trace rows."""
    review_id = sample_review_id()
    seed_completed_review(tmp_path, review_id=review_id)
    _guard_against_review_rerun(monkeypatch)
    result = runner.invoke(
        app,
        ["--format", "json", "replay", review_id, "--repo-root", str(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    payload = json.loads(result.stdout)
    assert payload.get("run_id") == review_id
    assert payload.get("replayed") is True
    assert payload.get("event_count", 0) >= 1


def test_unknown_review_id_is_fail_closed_for_findings(tmp_path: Path) -> None:
    """Error — unknown review ids exit non-zero with a readable message."""
    result = runner.invoke(
        app,
        ["findings", "review-missing-453", "--repo-root", str(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined
    assert "unknown review" in combined.casefold()


def test_findings_lookup_does_not_invoke_review_agent(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Functional — durable lookup never schedules ``run_offline_diff_review``."""
    review_id = sample_review_id()
    seed_completed_review(tmp_path, review_id=review_id)
    calls: list[dict[str, Any]] = []

    async def recorder(**kwargs: object) -> OfflineReviewResult:
        calls.append(dict(kwargs))
        msg = "review agent must not rerun for durable lookup"
        raise AssertionError(msg)

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        recorder,
    )
    result = runner.invoke(
        app,
        ["--format", "json", "findings", review_id, "--repo-root", str(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    assert calls == []


def test_explain_with_review_id_fails_closed_when_finding_missing_in_review(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Error — review-scoped explain does not fall back to global evidence."""
    review_id = sample_review_id()
    seed_completed_review(tmp_path, review_id=review_id)
    _guard_against_review_rerun(monkeypatch)
    result = runner.invoke(
        app,
        ["explain", review_id, "MC-deadbeef", "--repo-root", str(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined
    assert "unknown finding id" in combined.casefold()


def test_replay_unknown_review_id_fails_closed_without_global_fallback(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Error — explicit replay ids without co-located traces do not scan global traces."""
    review_id = "review-missing-replay-453"
    _guard_against_review_rerun(monkeypatch)
    trace_calls: list[object] = []

    def _boom(*args: object, **kwargs: object) -> list[dict[str, object]]:
        trace_calls.append((args, kwargs))
        msg = "global trace fallback must not run for explicit review id"
        raise AssertionError(msg)

    monkeypatch.setattr("mergecraft.cli.replay_cmd.load_trace_jsonl_events", _boom)
    result = runner.invoke(
        app,
        ["replay", review_id, "--repo-root", str(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined
    assert "unknown review run" in combined.casefold()
    assert trace_calls == []


def test_explain_single_arg_hex_review_id_steers_to_two_arg_form(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Error — a stored uuid hex review id alone steers to two-arg explain, not unknown finding."""
    review_id = "b1c2d3e4f5a6789012345678abcdef90"
    seed_completed_review(tmp_path, review_id=review_id)
    _guard_against_review_rerun(monkeypatch)
    result = runner.invoke(
        app,
        ["explain", review_id, "--repo-root", str(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined
    assert "stored review id" in combined.casefold()
    assert "explain <review-id> <finding-id>" in combined
    assert "unknown finding id" not in combined.casefold()


def test_replay_review_without_trace_distinguishes_from_unknown_review_id(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Error — replay names a stored review missing trace.jsonl with a distinct message."""
    review_id = sample_review_id()
    seed_completed_review(tmp_path, review_id=review_id, trace_events=[])
    _guard_against_review_rerun(monkeypatch)
    result = runner.invoke(
        app,
        ["replay", review_id, "--repo-root", str(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined
    assert "no stored trace.jsonl" in combined.casefold()
    assert "unknown review run" not in combined.casefold()


def test_findings_subcommand_typo_surfaces_typer_error_not_unknown_review_id(
    tmp_path: Path,
) -> None:
    """Error — subcommand typos like ``expor`` fail as Typer usage, not durable lookup."""
    result = runner.invoke(
        app,
        ["findings", "expor", "--repo-root", str(tmp_path)],
        env=_DUMB_ENV,
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_USAGE_EXIT_CODE, combined
    assert "no such command" in combined.casefold()
    assert "unknown review" not in combined.casefold()


def test_review_with_unsafe_review_id_still_succeeds_and_persists_safely(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Happy — unsafe ``MERGECRAFT_REVIEW_ID`` values do not crash persistence."""
    unsafe_review_id = "../escape"
    _install_fake_review(monkeypatch)
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
        ],
        env={**_DUMB_ENV, "MERGECRAFT_REVIEW_ID": unsafe_review_id},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, combined
    from tests.review.support_durable_review import require_callable

    loaded_ids = require_callable("list_completed_review_ids")(repo_root=tmp_path)
    assert loaded_ids
    assert unsafe_review_id not in loaded_ids
    assert len(loaded_ids) == 1
    persisted_id = loaded_ids[0]
    payload = json.loads(result.stdout)
    assert payload.get("review_id") == persisted_id
    loaded = require_callable("load_completed_review")(persisted_id, repo_root=tmp_path)
    assert loaded is not None
    assert loaded.review_id == persisted_id
