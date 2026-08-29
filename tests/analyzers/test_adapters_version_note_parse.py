"""Regression tests for the parse surface of a managed analyzer run.

``plan.version_note`` prose is prepended to the human-readable
``AnalyzerOutcome.output`` for every ``managed`` analyzer. It must never reach a
parser: a clean trufflehog scan (empty stdout, JSONL progress logs on stderr)
was being reported as ``skipped … failed to parse analyzer output`` on every
platform, which made a working scan indistinguishable from a broken one.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.adapters import run_adapter
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import AnalyzerOutcome, _outcome_from_completed

if TYPE_CHECKING:
    from pathlib import Path

_VERSION_NOTE = "ran mergeCraft's pinned trufflehog 3.96.0; your repo pins none"

# What trufflehog actually writes on a clean scan: nothing on stdout, structured
# progress logs on stderr.
_CLEAN_STDERR = (
    '{"level":"info-0","ts":"2026-08-22T10:02:00Z","logger":"trufflehog",'
    '"msg":"running source","source_name":"filesystem"}\n'
    '{"level":"info-0","ts":"2026-08-22T10:02:01Z","logger":"trufflehog",'
    '"msg":"finished scanning","chunks":3,"bytes":91}\n'
)


def _manifest(tool_id: str) -> Any:
    from mergecraft.analyzers.registry import load_catalog

    for manifest in load_catalog():
        if manifest.id == tool_id:
            return manifest
    raise AssertionError(f"no manifest for {tool_id}")


def _stub_chain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan: AnalyzerPlan,
    outcome_factory: Any,
) -> None:
    """Stub everything between manifest resolution and ``run_plan``."""
    from mergecraft.analyzers import adapters as adapters_mod

    monkeypatch.setattr(adapters_mod, "get_manifest", _manifest)
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
    monkeypatch.setattr(adapters_mod, "run_plan", outcome_factory)


def _record_parser_inputs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Capture every raw string handed to a parser through ``parse_output_file``."""
    from mergecraft.analyzers import parse as parse_mod

    seen: list[str] = []
    real = parse_mod.parse_output

    def _spy(raw: str, **kwargs: Any) -> Any:
        seen.append(raw)
        return real(raw, **kwargs)

    monkeypatch.setattr(parse_mod, "parse_output", _spy)
    return seen


def _clean_managed_plan(tmp_path: Path) -> AnalyzerPlan:
    return AnalyzerPlan(
        manifest_id="trufflehog",
        mode="managed",
        argv=("trufflehog", "filesystem", "-j"),
        cwd=tmp_path,
        version_note=_VERSION_NOTE,
    )


def _clean_outcome(plan: AnalyzerPlan) -> AnalyzerOutcome:
    """Build the outcome through the real ``run.py`` seam, not a hand-rolled stub."""
    completed = subprocess.CompletedProcess(
        args=list(plan.argv), returncode=0, stdout="", stderr=_CLEAN_STDERR
    )
    return _outcome_from_completed(completed, plan=plan, command="trufflehog filesystem -j")


def test_clean_managed_scan_is_ran_and_clean_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty stdout + JSONL log lines on stderr = zero findings, never a skip."""
    plan = _clean_managed_plan(tmp_path)
    outcome = _clean_outcome(plan)
    assert outcome.ran is True
    assert outcome.output.startswith(_VERSION_NOTE), "display output still carries the note"

    _stub_chain(monkeypatch, plan=plan, outcome_factory=lambda _plan, **_kwargs: outcome)

    result = run_adapter(
        tool_id="trufflehog",
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
    )

    assert result.skipped is False, result.skip_reason
    assert result.skip_reason is None
    assert result.findings == []
    assert result.version_note == _VERSION_NOTE


def test_version_note_never_reaches_a_parser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _clean_managed_plan(tmp_path)
    outcome = _clean_outcome(plan)
    seen = _record_parser_inputs(monkeypatch)
    _stub_chain(monkeypatch, plan=plan, outcome_factory=lambda _plan, **_kwargs: outcome)

    result = run_adapter(
        tool_id="trufflehog",
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
    )

    assert result.skipped is False, result.skip_reason
    assert seen, "the persisted output should have been parsed at least once"
    for raw in seen:
        assert _VERSION_NOTE not in raw
        assert "mergeCraft's pinned" not in raw


def test_persisted_output_excludes_the_version_note(tmp_path: Path) -> None:
    """``run.py`` persists the parse surface, not the display string."""
    from pathlib import Path as _Path

    plan = _clean_managed_plan(tmp_path)
    outcome = _clean_outcome(plan)

    assert outcome.output_path is not None
    persisted = _Path(outcome.output_path).read_text(encoding="utf-8")
    assert _VERSION_NOTE not in persisted
    assert "finished scanning" in persisted


def test_silent_managed_run_persists_nothing_and_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exit-0 run with both streams empty is a clean pass, not prose to parse."""
    plan = _clean_managed_plan(tmp_path)
    completed = subprocess.CompletedProcess(
        args=list(plan.argv), returncode=0, stdout="", stderr=""
    )
    outcome = _outcome_from_completed(completed, plan=plan, command="trufflehog filesystem -j")

    assert outcome.output_path is None, "version-note prose must never be persisted alone"

    _stub_chain(monkeypatch, plan=plan, outcome_factory=lambda _plan, **_kwargs: outcome)
    result = run_adapter(
        tool_id="trufflehog",
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
    )

    assert result.skipped is False, result.skip_reason
    assert result.findings == []


def test_undecodable_output_file_skips_instead_of_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``UnicodeDecodeError`` is a ``ValueError``; the handler must not read unbound ``raw``."""
    out_path = tmp_path / "trufflehog.out"
    out_path.write_bytes(b"\xff\xfe\x00binary garbage")
    plan = _clean_managed_plan(tmp_path)
    outcome = AnalyzerOutcome(
        name="trufflehog",
        command="trufflehog filesystem -j",
        status="passed",
        output=f"{_VERSION_NOTE}\n<binary>",
        exit_code=0,
        output_path=str(out_path),
    )
    _stub_chain(monkeypatch, plan=plan, outcome_factory=lambda _plan, **_kwargs: outcome)

    result = run_adapter(
        tool_id="trufflehog",
        repo_root=tmp_path,
        changed_files=["src/app.py"],
        tier="trusted",
    )

    assert result.skipped is True
    assert "could not read analyzer output" in (result.skip_reason or "")
    assert result.findings == []


@pytest.mark.parametrize("tool_id", ["semgrep", "trufflehog"])
def test_managed_plan_always_sets_a_version_note(tool_id: str, tmp_path: Path) -> None:
    """The defect is generic to ``managed``: every such plan carries the note."""
    from mergecraft.analyzers.resolve import resolve_analyzer

    plan = resolve_analyzer(
        manifest=_manifest(tool_id),
        repo_root=tmp_path,
        managed_available=True,
    )
    if plan.mode != "managed":
        pytest.skip(f"{tool_id} did not resolve to managed in this environment")
    assert plan.version_note
