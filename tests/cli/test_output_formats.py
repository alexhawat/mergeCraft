"""CC1 — CLI output formats (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Pins ``--output-format text|json|jsonl|sarif`` and regression on existing ``--json`` findings
schema. Authoring wave: **CC1.1** (RED). Implementation: **CC1.2**.
"""

from __future__ import annotations

import asyncio
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


def _write_findings_file(path: Path, payload: str) -> None:
    path.write_text(payload, encoding="utf-8")


def _install_fake_review(
    monkeypatch: pytest.MonkeyPatch,
    *,
    findings: list[dict[str, object]],
) -> None:
    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        materialization_path = kwargs.get("diff_file")
        diff_path = str(materialization_path) if materialization_path else None
        payload = json.dumps({"findings": findings})
        json_path = kwargs.get("json_path")
        if json_path is not None:
            _write_findings_file(Path(json_path), payload)
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


def test_json_format_requires_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--output-format json`` without ``--output`` or ``--json`` is rejected."""
    _install_fake_review(monkeypatch, findings=[_agent_finding_dict()])
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--output-format", "json"),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 30, combined
    assert "--output is required" in combined.lower() or "output" in combined.lower()


def test_json_format_writes_output_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``--output-format json --output`` writes findings to the requested path."""
    finding = _agent_finding_dict()
    _install_fake_review(monkeypatch, findings=[finding])
    json_out = tmp_path / "report.json"
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--output-format", "json", "--output", str(json_out)),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    assert json_out.is_file(), combined
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["findings"][0]["rule_id"] == finding["rule_id"]


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

    monkeypatch.setattr(offline_mod, "run_offline_agent_review", fake_run_agent_review)
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
    """``--output-format sarif`` exports agent findings, not only analyzer findings."""
    finding = _agent_finding_dict()
    _install_fake_review(monkeypatch, findings=[finding])
    sarif_out = tmp_path / "report.sarif.json"
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--output-format", "sarif", "--output", str(sarif_out)),
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
    """``--output-format jsonl`` writes one JSON object per line."""
    _install_fake_review(monkeypatch, findings=[_agent_finding_dict()])
    jsonl_out = tmp_path / "stream.jsonl"
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--output-format", "jsonl", "--output", str(jsonl_out)),
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


def test_jsonl_requests_structured_findings_from_run_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--output-format jsonl`` threads a ``json_path`` to the review so the agent
    produces structured findings — not the empty-file regression.

    mergeCraft review (PR #242, finding ``3f363546e98dad517048b8b9``) noted
    that ``jsonl`` and ``sarif`` writers read from ``run_offline_diff_review``'s
    ``json_path`` parameter; without it the agent returns markdown-only and the
    writers emit empty files. The mock in ``_install_fake_review`` pre-fills
    ``structured_output`` so it does not exercise that path — this test
    asserts the real ``kwargs['json_path']`` was wired.
    """
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> OfflineReviewResult:
        captured["kwargs"] = kwargs
        finding = _agent_finding_dict()
        payload = json.dumps({"findings": [finding]})
        json_path = kwargs.get("json_path")
        if json_path is not None:
            await asyncio.to_thread(Path(str(json_path)).write_text, payload, encoding="utf-8")
        return OfflineReviewResult(
            success=True,
            output="# Review\n\nWith findings.",
            structured_output=payload,
            diff_path=str(kwargs.get("diff_file")) if kwargs.get("diff_file") else None,
        )

    monkeypatch.setattr("mergecraft.cli.diff_review_cmd.run_offline_diff_review", _capture_run)

    jsonl_out = tmp_path / "stream.jsonl"
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--output-format", "jsonl", "--output", str(jsonl_out)),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    assert jsonl_out.is_file(), combined
    sent_json_path = captured["kwargs"].get("json_path")  # type: ignore[union-attr]
    assert sent_json_path is not None, (
        f"--output-format jsonl must request structured findings from the review; got json_path={sent_json_path!r}"
    )


def test_sarif_requests_structured_findings_from_run_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--output-format sarif`` threads a ``json_path`` to the review (PR #242 / 3f363546…)."""
    captured: dict[str, object] = {}

    async def _capture_run(**kwargs: object) -> OfflineReviewResult:
        captured["kwargs"] = kwargs
        finding = _agent_finding_dict()
        payload = json.dumps({"findings": [finding]})
        json_path = kwargs.get("json_path")
        if json_path is not None:
            await asyncio.to_thread(Path(str(json_path)).write_text, payload, encoding="utf-8")
        return OfflineReviewResult(
            success=True,
            output="# Review\n\nWith findings.",
            structured_output=payload,
            diff_path=str(kwargs.get("diff_file")) if kwargs.get("diff_file") else None,
        )

    monkeypatch.setattr("mergecraft.cli.diff_review_cmd.run_offline_diff_review", _capture_run)

    sarif_out = tmp_path / "report.sarif.json"
    result = runner.invoke(
        app,
        _review_argv(tmp_path, "--output-format", "sarif", "--output", str(sarif_out)),
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    assert sarif_out.is_file(), combined
    sent_json_path = captured["kwargs"].get("json_path")  # type: ignore[union-attr]
    assert sent_json_path is not None, (
        f"--output-format sarif must request structured findings from the review; got json_path={sent_json_path!r}"
    )


def test_global_format_json_inherited_by_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root ``--format json`` selects JSON output when ``--output-format`` is omitted."""
    finding = _agent_finding_dict()
    _install_fake_review(monkeypatch, findings=[finding])
    json_out = tmp_path / "report.json"
    result = runner.invoke(
        app,
        ["--format", "json", *_review_argv(tmp_path, "--output", str(json_out))],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    assert json_out.is_file(), combined


def test_explicit_output_format_text_wins_over_global_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit ``--output-format text`` renders human text even with root ``--format json``."""
    _install_fake_review(monkeypatch, findings=[_agent_finding_dict()])
    result = runner.invoke(
        app,
        [
            "--format",
            "json",
            *_review_argv(tmp_path, "--output-format", "text"),
        ],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    assert "review" in combined.lower()


def test_default_text_review_requests_structured_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default ``review`` (no --output-format/--json) requests structured findings so
    exit codes 10/11 reflect findings.

    mergeCraft review (PR #242, finding ``7a3cdf5ef1994610113e8e37``) noted
    that default-text ``review`` can never produce exit 10/11 because
    ``parse_offline_review_findings`` returns ``[]`` without structured output.
    The fix requests structured findings internally; the temp file is
    cleaned up and no structured file is left behind.
    """
    captured: dict[str, object] = {}

    async def _capture_run(*args: object, **kwargs: object) -> OfflineReviewResult:
        captured["kwargs"] = kwargs
        finding = _agent_finding_dict()
        payload = json.dumps({"findings": [finding]})
        json_path = kwargs.get("json_path")
        if json_path is not None:
            await asyncio.to_thread(Path(str(json_path)).write_text, payload, encoding="utf-8")
        return OfflineReviewResult(
            success=True,
            output="# Review\n\nWith findings.",
            structured_output=payload,
            diff_path=str(kwargs.get("diff_file")) if kwargs.get("diff_file") else None,
        )

    monkeypatch.setattr("mergecraft.cli.diff_review_cmd.run_offline_diff_review", _capture_run)

    result = runner.invoke(
        app,
        _review_argv(tmp_path),  # default — text mode, no flags
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code == 10, combined
    sent_json_path = captured["kwargs"].get("json_path")  # type: ignore[union-attr]
    assert sent_json_path is not None, (
        f"default text review must request structured findings for exit-code resolution; got json_path={sent_json_path!r}"
    )
    # No findings.json is left next to the patch — text mode does not write
    # the structured sink, only borrows the schema to populate the exit code.
    findings_files = list(tmp_path.glob("*.findings.json"))
    findings_files += list(tmp_path.glob("findings.json"))
    assert not findings_files, (
        f"default text review must not leave a structured-findings file behind; got {findings_files}"
    )
