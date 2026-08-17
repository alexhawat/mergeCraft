"""CC1 — CLI output formats (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Pins ``--format text|json|jsonl|sarif`` and regression on existing ``--json`` findings
schema. Authoring wave: **CC1.1** (RED). Implementation: **CC1.2**.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest  # noqa: TC002 — MonkeyPatch annotations on test functions
from tests.analyzers.support import import_module as import_analyzer_module
from typer.testing import CliRunner

from mergecraft.analyzers.sarif import validate_sarif_document
from mergecraft.cli.app import app
from mergecraft.offline_review import OfflineReviewResult

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _agent_finding_dict() -> dict[str, object]:
    finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="mergecraft-agent",
        rule_id="AGENT-1",
        category="Security & Privacy",
        severity="Minor",
        confidence="likely",
        message="agent finding",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="unknown",
    )
    return finding.model_dump()


def _install_fake_review(
    monkeypatch: pytest.MonkeyPatch,
    *,
    findings: list[dict[str, object]],
) -> None:
    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        materialization_path = kwargs.get("diff_file")
        diff_path = str(materialization_path) if materialization_path else None
        payload = json.dumps({"findings": findings})
        return OfflineReviewResult(
            success=True,
            output="# Review\n\nWith findings.",
            structured_output=payload,
            diff_path=diff_path,
        )

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )


def _review_argv(tmp_path: Path, *extra: str) -> list[str]:
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    return ["review", "--diff", str(patch), "--cwd", str(tmp_path), *extra]


def test_text_format_default(tmp_path: Path) -> None:
    """Regression — default stdout is human-readable review text (dry-run pin)."""
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--dry-run"),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, combined
    assert "offline" in combined.lower() or "review" in combined.lower()


def test_json_format_matches_existing_findings_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression — ``--json`` file output schema is unchanged."""
    import mergecraft.offline_review as offline_mod

    finding = _agent_finding_dict()

    async def fake_run_agent_review(**kwargs: object) -> OfflineReviewResult:
        materialization = kwargs["materialization"]
        payload = json.dumps({"findings": [finding]})
        return OfflineReviewResult(
            success=True,
            output="# Review\n\nLooks good.",
            structured_output=payload,
            diff_path=str(materialization.path),
        )

    monkeypatch.setattr(offline_mod, "_run_agent_review", fake_run_agent_review)
    json_out = tmp_path / "findings.json"
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--json", str(json_out)),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    assert json_out.is_file(), combined
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert isinstance(payload.get("findings"), list)
    assert payload["findings"][0]["rule_id"] == finding["rule_id"]


def test_sarif_includes_agent_findings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--format sarif`` exports agent findings, not only analyzer findings."""
    finding = _agent_finding_dict()
    _install_fake_review(monkeypatch, findings=[finding])
    sarif_out = tmp_path / "report.sarif.json"
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--format", "sarif", "--output", str(sarif_out)),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    assert sarif_out.is_file(), combined
    document = json.loads(sarif_out.read_text(encoding="utf-8"))
    validate_sarif_document(document)
    results = document["runs"][0]["results"]
    assert any(row.get("ruleId") == finding["rule_id"] for row in results)


def test_jsonl_is_one_object_per_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--format jsonl`` writes one JSON object per line."""
    _install_fake_review(monkeypatch, findings=[_agent_finding_dict()])
    jsonl_out = tmp_path / "stream.jsonl"
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--format", "jsonl", "--output", str(jsonl_out)),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    assert jsonl_out.is_file(), combined
    lines = [line for line in jsonl_out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines
    for line in lines:
        obj = json.loads(line)
        assert isinstance(obj, dict)
