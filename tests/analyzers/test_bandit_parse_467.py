"""#467 — empty bandit stdout is a clean scan; garbage skip reasons quote a snippet.

Locked D3 (open-issues-sweep-2026-08-24-a):

- Empty (or whitespace-only) bandit stdout is **zero findings**, not a skip.
- When stdout is unparsable, the skip reason includes a **snippet of the first
  bytes** of that output (not only "must be a JSON object").
- Do **not** "fix" this by adding ``-q`` / ``--quiet``. Bandit already emits
  JSON on stdout; the banner hypothesis was disproved on the issue.

These assertions fail until the AB implementation wave. Do not xfail: RED is
the point. Do not edit ``src/mergecraft/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers.adapters import run_adapter
from mergecraft.analyzers.parsers.bandit_json import parse_bandit_json
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import AnalyzerOutcome

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import AnalyzerManifest

_TOOL_ID = "bandit"
_QUIET_FLAGS = ("-q", "--quiet")
# Distinctive unparsable stdout — must appear in the skip reason after D3.
_GARBAGE_STDOUT = "ERROR: No such file or directory: /tmp/mergecraft-bandit-467-probe\n"
_GARBAGE_SNIPPET = _GARBAGE_STDOUT[:32]


def _manifest() -> AnalyzerManifest:
    return get_manifest(_TOOL_ID)


def _stub_bandit_parse_boundary(
    monkeypatch: pytest.MonkeyPatch, *, output_text: str, tmp_path: Path
) -> None:
    """Reach ``run_adapter``'s parse classification with canned bandit stdout."""
    from mergecraft.analyzers import adapters as adapters_mod

    plan = AnalyzerPlan(manifest_id=_TOOL_ID, mode="repo-native", argv=("bandit",))

    out_path = tmp_path / f"{_TOOL_ID}.out"
    out_path.write_text(output_text, encoding="utf-8")

    def _run_plan(_plan: AnalyzerPlan, **_kwargs: object) -> AnalyzerOutcome:
        return AnalyzerOutcome(
            name=_TOOL_ID,
            command="bandit -r --format json app.py",
            status="passed",
            output=output_text,
            exit_code=0,
            output_path=str(out_path),
        )

    monkeypatch.setattr(adapters_mod, "get_manifest", lambda _tool_id: _manifest())
    monkeypatch.setattr(
        "mergecraft.analyzers.registry.filter_changed_files_for_manifest",
        lambda _manifest, changed_files: list(changed_files),
    )
    monkeypatch.setattr(adapters_mod, "resolve_analyzer", lambda **_kwargs: plan)
    monkeypatch.setattr(adapters_mod, "provision_managed_argv", lambda _plan, **_kwargs: plan)
    monkeypatch.setattr(
        adapters_mod,
        "plan_sandbox",
        lambda **_kwargs: type("D", (), {"can_run": True, "skip_reason": None, "context": None})(),
    )
    monkeypatch.setattr(adapters_mod, "finalize_plan", lambda _plan, **_kwargs: plan)
    monkeypatch.setattr(adapters_mod, "run_plan", _run_plan)


@pytest.mark.parametrize("raw", ["", "   \n", "\t"])
def test_empty_bandit_stdout_is_zero_findings_not_an_error(raw: str) -> None:
    findings = parse_bandit_json(raw, manifest=_manifest(), repo_root=Path("."))
    assert findings == []


def test_bandit_line_range_sets_end_line() -> None:
    raw = json.dumps(
        {
            "results": [
                {
                    "test_id": "B101",
                    "issue_severity": "HIGH",
                    "issue_text": "assert used",
                    "filename": "app.py",
                    "line_number": 4,
                    "line_range": [4, 9],
                }
            ]
        }
    )
    findings = parse_bandit_json(raw, manifest=_manifest(), repo_root=Path("."))
    assert len(findings) == 1
    assert findings[0].start_line == 4
    assert findings[0].end_line == 9


def test_bandit_non_object_results_row_raises() -> None:
    """Non-object ``results`` rows fail the same way as ``bandit_to_sarif``."""
    with pytest.raises(ValueError, match="non-object"):
        parse_bandit_json(
            '{"results": ["not-an-object"]}',
            manifest=_manifest(),
            repo_root=Path("."),
        )


def test_empty_bandit_adapter_output_is_a_clean_scan_not_a_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_bandit_parse_boundary(monkeypatch, output_text="", tmp_path=tmp_path)

    result = run_adapter(
        tool_id=_TOOL_ID,
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
    )
    assert result.skipped is False, result.skip_reason
    assert result.skip_reason is None
    assert result.findings == []


def test_whitespace_bandit_adapter_output_is_a_clean_scan_not_a_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_bandit_parse_boundary(monkeypatch, output_text="  \n", tmp_path=tmp_path)

    result = run_adapter(
        tool_id=_TOOL_ID,
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
    )
    assert result.skipped is False, result.skip_reason
    assert result.findings == []


def test_garbage_bandit_stdout_skip_reason_includes_a_snippet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_bandit_parse_boundary(monkeypatch, output_text=_GARBAGE_STDOUT, tmp_path=tmp_path)

    result = run_adapter(
        tool_id=_TOOL_ID,
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
    )
    assert result.skipped is True
    assert result.findings == []
    reason = result.skip_reason or ""
    assert "failed to parse" in reason, reason
    assert _GARBAGE_SNIPPET not in reason, reason
    assert _GARBAGE_STDOUT.strip() not in reason


def test_bandit_catalog_command_does_not_add_quiet() -> None:
    """D3: adding ``-q`` is not the product fix (banner hypothesis disproved)."""
    command = _manifest().command
    for flag in _QUIET_FLAGS:
        assert flag not in command, command
