"""W1.7 — evidence packet run_health, step summary, workflow artifact (implementation W7)."""

from __future__ import annotations

import asyncio
import importlib
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION, MergeEvidencePacket
from mergecraft.evidence.run_packet import emit_run_packet, prepare_run_packet
from mergecraft.main import MainResult
from tests.ci.workflow_support import read_text
from tests.evidence.test_run_packet import _make_ctx
from tests.review_record.conftest import make_scoped_finding, require_symbol

_STEP_SUMMARY_CAP = 1_048_576


def _step_summary_module() -> Any:
    return importlib.import_module("mergecraft.utils.step_summary")


def test_packet_run_health_round_trips_and_schema_version_bumps() -> None:
    run_health = {
        "findings": [
            make_scoped_finding(
                scope="run",
                severity="Major",
                rule_id="ignored-tool-error",
                message="bubblewrap unavailable",
            ).model_dump()
        ],
        "conclusion": "advisory",
    }
    payload = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "change_id": "acme/demo#546",
        "agent": {
            "agent_id": "claude",
            "agent_version": "0.0.1",
            "model": "claude-sonnet-4-5",
        },
        "files_changed": [],
        "findings": [],
        "deterministic_checks": [],
        "run_health": run_health,
    }
    packet = MergeEvidencePacket.model_validate(payload)
    assert packet.run_health is not None
    assert packet.run_health.findings
    assert packet.schema_version != "1.10.0"


def test_step_summary_written_on_success_failure_and_no_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    step_summary = _step_summary_module()
    render = require_symbol(step_summary, "render_step_summary")
    append = require_symbol(step_summary, "append_step_summary")
    packet = prepare_run_packet(_make_ctx(tmp_path), run_succeeded=True)
    for label, rejection in [
        ("success", None),
        ("failure", "provider_failure"),
        ("no_verdict", "schema_invalid"),
    ]:
        body = render(packet=packet, outcome_label=label, rejection_reason=rejection)
        append(body)
    text = summary_path.read_text(encoding="utf-8")
    assert "success" in text
    assert "failure" in text
    assert "schema_invalid" in text


def test_step_summary_truncates_findings_not_header(tmp_path: Path) -> None:
    step_summary = _step_summary_module()
    render = require_symbol(step_summary, "render_step_summary")
    findings = [
        make_scoped_finding(
            scope="change",
            severity="Major",
            introduced_by_pr="true",
            message=f"finding-{index}",
            rule_id=f"RULE-{index}",
        )
        for index in range(5000)
    ]
    packet = prepare_run_packet(_make_ctx(tmp_path), run_succeeded=True)
    packet.findings.extend(findings)
    body = render(packet=packet, outcome_label="success", rejection_reason=None)
    assert len(body.encode("utf-8")) <= _STEP_SUMMARY_CAP
    assert body.splitlines()[0].startswith("# mergeCraft")


def test_evidence_packet_output_nonempty_for_pr_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.cli.gha_cmd import _run_main

    output_file = tmp_path / "gh_output"
    output_file.touch()
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    async def _fake_main() -> MainResult:
        ctx = _make_ctx(tmp_path)
        packet = prepare_run_packet(ctx, run_succeeded=True)
        written = emit_run_packet(ctx, packet=packet)
        return MainResult(success=True, result="ok", evidence_packet_path=str(written))

    import mergecraft.main as main_mod

    monkeypatch.setattr(main_mod, "main", _fake_main)
    asyncio.run(_run_main())
    written = output_file.read_text(encoding="utf-8")
    assert "evidence_packet" in written
    assert '"schema_version"' in written


def test_mergecraft_workflow_persists_packet_via_env_not_inline_interpolation() -> None:
    workflow = yaml.safe_load(read_text(".github/workflows/mergecraft.yml"))
    steps = []
    for job in (workflow.get("jobs") or {}).values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            name = str(step.get("name") or "")
            if "Persist evidence packet" in name or "evidence packet" in name.lower():
                steps.append(step)
    assert steps, "expected an always() packet persistence step in mergecraft.yml"
    for step in steps:
        assert step.get("if") == "always()"
        env = step.get("env") or {}
        assert "PACKET" in env
        assert "${{" in str(env["PACKET"])
        run_body = str(step.get("run") or "")
        assert "${{" not in run_body or "$PACKET" in run_body
