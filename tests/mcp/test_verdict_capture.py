"""Judge-verdict capture is opt-in, redacted, and calibration-shaped.

A saved verifier verdict used to become only a loguru line and a span, so it
could not be reconstructed into a calibration case without hand transcription
(which is indistinguishable from fabrication). Worse, the ``drop`` class is
unobservable after the fact: a dropped finding never publishes.

Capture is **off by default**. It is enabled by ``--capture-verdicts`` on the
offline review path and by ``MERGECRAFT_CAPTURE_VERDICTS=1`` for Action runs.
When on, every ``record_finding_verdict`` call — confirm, downgrade **and**
drop — appends exactly one line to ``<evidence_dir>/judge-verdicts.jsonl``.
Each line is the machine-written half of a ``JudgeCalibrationCase`` (everything
except the human adjudication fields), written through the existing packet
redaction so a secret in a finding body never reaches the artefact.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mergecraft.agents.verifier import JudgeVerdict, judge_pin, record_verifier_verdict
from mergecraft.cli.app import app
from mergecraft.evals.judge_calibration import JudgeCalibrationCase
from mergecraft.evidence.run_packet import resolve_evidence_dir, resolve_packet_path
from mergecraft.evidence.verdict_capture import resolve_capture_dir
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import AnalyzerRunState, AnalyzerStatusRow, init_tool_state
from mergecraft.mcp.verification import record_finding_verdict_tool
from mergecraft.modes import compute_modes
from mergecraft.review_taxonomy import finding_fingerprint
from mergecraft.utils.github import GitHubClient

runner = CliRunner()
_CAPTURE_ENV = "MERGECRAFT_CAPTURE_VERDICTS"
_CANARY = "sk-canary-verdict-capture-do-not-leak-7f3a9b2c1d4e5f6a"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


@pytest.fixture(autouse=True)
def _offline_evidence_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the offline capture location against ambient Action environment.

    The offline coverage below pins where capture writes with **no** Action
    context. A stray ``RUNNER_TEMP`` (present on every GitHub runner) or an
    operator ``MERGECRAFT_EVIDENCE_DIR`` would otherwise relocate the artefact
    out from under ``tmp_path`` and make these tests assert the wrong thing.
    The Action-location pin sets ``RUNNER_TEMP`` itself.
    """
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)


@contextmanager
def _capture_logs(*, level: str = "INFO") -> Iterator[list[str]]:
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda message: captured.append(str(message)), level=level)
    try:
        yield captured
    finally:
        loguru_logger.remove(sink_id)


def _ctx(tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.analyzer_run = AnalyzerRunState(
        ran=True,
        analyzers=[AnalyzerStatusRow(id="ruff", status="completed", finding_count=1)],
    )
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )


def _seed_finding(
    ctx: ToolContext,
    *,
    path: str = "src/app.py",
    body: str = "this token is logged in plaintext",
    severity: str = "Critical",
) -> str:
    fingerprint = finding_fingerprint(path=path, body=body)
    ctx.tool_state.agent_findings = [
        {
            "path": path,
            "line": 12,
            "severity": severity,
            "body": body,
            "fingerprint": fingerprint,
        }
    ]
    return fingerprint


async def _verdict(ctx: ToolContext, **params: Any) -> dict[str, Any]:
    result = await record_finding_verdict_tool(ctx).execute(params)
    assert result.is_error is False, result.content[0]["text"]
    return json.loads(result.content[0]["text"])


def _capture_files(tmp_path: Path) -> list[Path]:
    return sorted(tmp_path.rglob("judge-verdicts.jsonl"))


def _captured_records(tmp_path: Path) -> list[dict[str, Any]]:
    files = _capture_files(tmp_path)
    assert len(files) == 1, f"expected exactly one capture artefact, found {files!r}"
    return [
        json.loads(line)
        for line in files[0].read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _complete_into_calibration_case(record: dict[str, Any]) -> JudgeCalibrationCase:
    """Add a synthetic human adjudication and validate the captured half strictly.

    The captured record is the machine-written half of a calibration case; a real
    case additionally carries the human reference and adjudication. Completing it
    here proves the machine half is exactly the shape the strict model requires.
    """
    verdict = record["saved_judge_verdict"]
    adjudicated_at = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    payload = {
        "case_id": record["case_id"],
        "finding": record["finding"],
        "deterministic_checks": record["deterministic_checks"],
        "lane": record["lane"],
        "evidence_sha256": record["evidence_sha256"],
        "saved_judge_verdict": verdict,
        "prompt_sha256": record["prompt_sha256"],
        "policy_id": record["policy_id"],
        "policy_parameters": record["policy_parameters"],
        "human_reference": {
            "verdict": verdict["verdict"],
            "new_severity": verdict.get("new_severity"),
        },
        "human_adjudicator_login": "reviewer",
        "human_adjudicated_at": adjudicated_at.isoformat(),
        "provenance": "human",
        "adjudication": {
            "adjudicated_by": "human",
            "independence": "independent",
            "at": adjudicated_at.isoformat(),
        },
    }
    return JudgeCalibrationCase.model_validate(payload)


# ── default off ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_capture_off_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_CAPTURE_ENV, raising=False)
    ctx = _ctx(tmp_path)
    fingerprint = _seed_finding(ctx)

    await _verdict(ctx, fingerprint=fingerprint, verdict="drop", reason="Guarded upstream.")

    assert _capture_files(tmp_path) == [], "capture is off by default and must write nothing"


def test_capture_off_keeps_the_loguru_verdict_line(tmp_path: Path) -> None:
    """``record_verifier_verdict`` keeps its loguru line even with capture off."""
    verdict = JudgeVerdict(
        fingerprint="a" * 24,
        verdict="confirm",
        reason="Confirmed.",
        pin=judge_pin(provider="claude"),
        deterministic_checks=["run_analyzers"],
    )
    with _capture_logs(level="INFO") as messages:
        record_verifier_verdict(verdict, learnings_path=tmp_path / "learnings.md")

    assert any("judge verdict:" in message for message in messages), (
        f"the judge verdict log line disappeared; got {messages!r}"
    )


# ── capture on: one line per verdict, all three classes ──────────────────────


@pytest.mark.asyncio
async def test_capture_on_appends_one_line_per_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_CAPTURE_ENV, "1")
    ctx = _ctx(tmp_path)
    confirm_fp = _seed_finding(ctx, body="confirm me", severity="Critical")
    await _verdict(ctx, fingerprint=confirm_fp, verdict="confirm", reason="Confirmed.")
    downgrade_fp = _seed_finding(ctx, body="downgrade me", severity="Major")
    await _verdict(
        ctx,
        fingerprint=downgrade_fp,
        verdict="downgrade",
        reason="Only minor in practice.",
        new_severity="Minor",
    )
    drop_fp = _seed_finding(ctx, body="drop me", severity="Major")
    await _verdict(ctx, fingerprint=drop_fp, verdict="drop", reason="Guarded upstream.")

    records = _captured_records(tmp_path)

    assert len(records) == 3, "each verdict — including drop — appends exactly one line"
    assert [row["saved_judge_verdict"]["verdict"] for row in records] == [
        "confirm",
        "downgrade",
        "drop",
    ]


@pytest.mark.asyncio
async def test_captured_line_validates_as_the_calibration_case_minus_adjudication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_CAPTURE_ENV, "1")
    ctx = _ctx(tmp_path)
    fingerprint = _seed_finding(ctx)
    await _verdict(ctx, fingerprint=fingerprint, verdict="confirm", reason="Confirmed.")

    record = _captured_records(tmp_path)[0]

    machine_fields = {
        "case_id",
        "finding",
        "deterministic_checks",
        "lane",
        "evidence_sha256",
        "saved_judge_verdict",
        "prompt_sha256",
        "policy_id",
        "policy_parameters",
    }
    human_fields = {
        "human_reference",
        "human_adjudicator_login",
        "human_adjudicated_at",
        "provenance",
        "adjudication",
        "saved_policy_outcome",
    }
    allowed = set(JudgeCalibrationCase.model_fields)
    assert set(record) <= allowed, f"capture carries unknown keys: {set(record) - allowed}"
    assert machine_fields <= set(record), (
        f"capture is missing calibration fields: {machine_fields - set(record)}"
    )
    assert not (human_fields & set(record)), "capture must not fabricate human adjudication"

    # Completing the human half validates the whole record against the strict model.
    case = _complete_into_calibration_case(record)
    assert case.saved_judge_verdict.fingerprint == case.finding.identity()


@pytest.mark.asyncio
async def test_captured_record_carries_the_pinned_judge_and_policy_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_CAPTURE_ENV, "1")
    ctx = _ctx(tmp_path)
    fingerprint = _seed_finding(ctx)
    await _verdict(ctx, fingerprint=fingerprint, verdict="confirm", reason="Confirmed.")

    record = _captured_records(tmp_path)[0]

    pin = record["saved_judge_verdict"]["pin"]
    assert pin["model_pinned"] is True, "capture requires a pinned judge model"
    assert pin["provider"] == "claude"
    assert pin["model"]
    assert _SHA256_RE.fullmatch(record["prompt_sha256"])
    assert _SHA256_RE.fullmatch(record["evidence_sha256"])
    assert record["policy_id"].strip()
    assert record["policy_parameters"], "calibration cases require explicit policy parameters"
    assert record["lane"].strip(), "a calibration case lane must be non-empty"
    assert record["deterministic_checks"], "capture must record the deterministic checks"
    stored = record["deterministic_checks"][0]
    assert stored["name"]
    assert stored["status"]
    assert stored["command"]


@pytest.mark.asyncio
async def test_a_canary_in_the_finding_body_is_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_CAPTURE_ENV, "1")
    ctx = _ctx(tmp_path)
    fingerprint = _seed_finding(
        ctx,
        body=f"this token is logged in plaintext ({_CANARY})",
    )

    await _verdict(ctx, fingerprint=fingerprint, verdict="confirm", reason="Confirmed.")

    files = _capture_files(tmp_path)
    assert files, "capture did not write its artefact"
    text = files[0].read_text(encoding="utf-8")
    assert _CANARY not in text, "the packet redaction must run before the line is written"
    assert "plaintext" in text, "the non-secret part of the finding body must survive"


# ── Action runs: the capture must survive the runner ─────────────────────────


@pytest.mark.asyncio
async def test_capture_is_retrievable_from_the_action_evidence_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An Action run must still have the capture file after the runner ends.

    The workflow uploads its evidence from the directory
    ``resolve_packet_path`` names (``$RUNNER_TEMP/mergecraft`` in an Action run,
    where ``MERGECRAFT_EVIDENCE_DIR`` is never set). A capture written under the
    ephemeral run tmpdir is discarded with the runner, so the Action half of the
    control is dead. The capture must resolve through the same destination
    policy the packet uses.
    """
    runner_temp = tmp_path / "runner"
    runner_temp.mkdir()
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv(_CAPTURE_ENV, "1")

    ctx = _ctx(tmp_path / "run")
    fingerprint = _seed_finding(ctx)
    await _verdict(ctx, fingerprint=fingerprint, verdict="confirm", reason="Confirmed.")

    upload_dir = resolve_packet_path(tmpdir=ctx.tmpdir, change_slug="acme-demo-42").parent
    assert (upload_dir / "judge-verdicts.jsonl").is_file(), (
        "the capture artefact is not retrievable after the runner ends: the "
        f"Action uploads its evidence from {upload_dir}, but the file was written "
        f"elsewhere (found {_capture_files(tmp_path)!r})"
    )


# ── offline review flag ──────────────────────────────────────────────────────


def test_offline_review_exposes_the_capture_flag() -> None:
    """The offline review path enables capture with one explicit flag."""
    result = runner.invoke(app, ["review", "--help"])

    assert result.exit_code == 0, result.output
    assert "--capture-verdicts" in result.output


# ── the capture file and the packet share one destination policy ─────────────


@pytest.mark.parametrize(
    ("runner_temp", "override"),
    [
        (None, None),
        ("/runner/temp", None),
        (None, "/custom/evidence"),
    ],
)
def test_capture_dir_and_packet_dir_share_one_resolution_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner_temp: str | None,
    override: str | None,
) -> None:
    """The capture file and the packet must resolve to the same directory.

    The workflow uploads evidence from one directory. If the capture resolver
    drifted from the packet resolver — as it did when it wrote under the
    ephemeral run tmpdir — an Action run with capture on uploads nothing and the
    control is dead. Pin the shared policy across an offline run, an Action run
    (``RUNNER_TEMP`` set) and the explicit operator override.
    """
    if runner_temp is None:
        monkeypatch.delenv("RUNNER_TEMP", raising=False)
    else:
        monkeypatch.setenv("RUNNER_TEMP", runner_temp)
    if override is None:
        monkeypatch.delenv("MERGECRAFT_EVIDENCE_DIR", raising=False)
    else:
        monkeypatch.setenv("MERGECRAFT_EVIDENCE_DIR", override)

    capture_dir = resolve_capture_dir(tmpdir=str(tmp_path))
    packet_dir = resolve_packet_path(tmpdir=str(tmp_path), change_slug="acme-demo-42").parent

    assert capture_dir == packet_dir, (
        "the capture file and the packet resolve to different directories; the "
        "workflow uploads one of them, so the other is discarded"
    )
    assert capture_dir == resolve_evidence_dir(tmpdir=str(tmp_path))
    if override is not None:
        assert capture_dir == Path(override)
    elif runner_temp is not None:
        assert capture_dir == Path(runner_temp) / "mergecraft"
    else:
        assert capture_dir == tmp_path / "evidence"
