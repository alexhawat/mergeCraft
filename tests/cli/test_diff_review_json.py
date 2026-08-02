"""RED tests for ``mergecraft diff-review --json`` structured findings (issue #30, Batch A W1)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from tests.analyzers.support import import_module as import_analyzer_module
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.offline_review import OfflineReviewResult, build_offline_review_prompt

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_FINDING_FIELDS = frozenset(
    {
        "tool",
        "rule_id",
        "category",
        "severity",
        "confidence",
        "message",
        "path",
        "start_line",
        "end_line",
        "fingerprint",
        "evidence",
        "remediation",
        "autofix",
        "introduced_by_pr",
        "source",
        "cluster_id",
    }
)

_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _sample_finding_dict() -> dict[str, object]:
    finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="analyzer",
        introduced_by_pr="unknown",
    )
    return finding.model_dump()


def _import_findings_output_schema() -> Callable[[], dict[str, Any]]:
    try:
        from mergecraft.offline_review import findings_output_schema
    except ImportError:
        from mergecraft.utils.payload import findings_output_schema
    return findings_output_schema


def _step_four_block(prompt: str) -> str:
    match = re.search(r"4\. (.+?)\n5\.", prompt, flags=re.DOTALL)
    assert match is not None, "expected numbered step 4 in offline review prompt"
    return match.group(1)


def test_findings_output_schema_is_valid_json_schema() -> None:
    schema_fn = _import_findings_output_schema()
    schema = schema_fn()

    assert schema.get("type") == "object"
    properties = schema.get("properties")
    assert isinstance(properties, dict)
    assert "findings" in properties

    findings_prop = properties["findings"]
    assert findings_prop.get("type") == "array"
    items = findings_prop.get("items")
    assert isinstance(items, dict)

    item_properties = items.get("properties")
    assert isinstance(item_properties, dict)
    assert frozenset(item_properties) >= _FINDING_FIELDS
    assert schema.get("required") == ["findings"]


def test_build_offline_review_prompt_requires_set_output_when_json_mode(
    tmp_path: Path,
) -> None:
    diff_path = tmp_path / "review.diff"
    diff_path.write_text("diff --git a/x b/x\n+1\n", encoding="utf-8")

    prompt = build_offline_review_prompt(
        diff_path=diff_path,
        base_ref="origin/main",
        json_mode=True,
    )
    step_four = _step_four_block(prompt).lower()

    assert "set_output" in step_four
    assert "required" in step_four
    assert "if available" not in step_four


def test_cli_diff_review_json_dry_run_does_not_write_file(tmp_path: Path) -> None:
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    json_out = tmp_path / "structured.json"

    result = runner.invoke(
        app,
        [
            "diff-review",
            "--diff",
            str(patch),
            "--cwd",
            str(tmp_path),
            "--dry-run",
            "--json",
            str(json_out),
        ],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert not json_out.exists()


def _install_fake_agent_review(
    monkeypatch: pytest.MonkeyPatch,
    *,
    findings: list[dict[str, object]],
    success: bool = True,
) -> None:
    import mergecraft.offline_review as offline_mod

    async def fake_run_agent_review(**kwargs: object) -> OfflineReviewResult:
        materialization = kwargs["materialization"]
        payload = json.dumps({"findings": findings})
        if not success:
            return OfflineReviewResult(
                success=False,
                error="agent failed",
                diff_path=str(materialization.path),
            )
        return OfflineReviewResult(
            success=True,
            output=payload,
            diff_path=str(materialization.path),
        )

    monkeypatch.setattr(offline_mod, "_run_agent_review", fake_run_agent_review)


@pytest.mark.parametrize(
    ("findings", "expect_ok"),
    [
        ([_sample_finding_dict()], True),
        ([{"tool": "broken", "severity": "NotReal"}], False),
    ],
    ids=["valid_finding", "invalid_finding"],
)
def test_cli_diff_review_json_validates_findings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    findings: list[dict[str, object]],
    expect_ok: bool,
) -> None:
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    json_out = tmp_path / "findings.json"
    _install_fake_agent_review(monkeypatch, findings=findings)

    result = runner.invoke(
        app,
        [
            "diff-review",
            "--diff",
            str(patch),
            "--cwd",
            str(tmp_path),
            "--json",
            str(json_out),
        ],
        env={"NO_COLOR": "1", "TERM": "dumb"},
    )

    combined = _plain(result.stdout + result.stderr)
    if expect_ok:
        assert result.exit_code == 0, combined
        assert json_out.is_file(), combined
        payload = json.loads(json_out.read_text(encoding="utf-8"))
        assert isinstance(payload.get("findings"), list)
        finding_mod = import_analyzer_module("mergecraft.analyzers.finding")
        for item in payload["findings"]:
            finding_mod.Finding.model_validate(item)
    else:
        assert result.exit_code != 0, combined
        assert not json_out.exists(), combined
        assert any(
            token in combined.lower() for token in ("valid", "finding", "validation", "conform")
        ), combined


def test_cli_diff_review_help_lists_json() -> None:
    result = runner.invoke(app, ["diff-review", "--help"], env={"NO_COLOR": "1", "TERM": "dumb"})
    assert result.exit_code == 0
    assert "--json" in _plain(result.stdout)
