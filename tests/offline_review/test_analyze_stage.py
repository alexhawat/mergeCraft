"""CLI offline analyze stage must call the real analyzer pipeline."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import mergecraft.offline_review as offline_mod
from mergecraft.agents.shared import AgentResult
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.config.settings import AnalyzersSettings, RepoSettings
from mergecraft.mcp.tool_state import AnalyzerRunState
from mergecraft.offline_review import (
    OfflineReviewResult,
    findings_from_analyzer_run,
    merge_analyzer_findings_into_result,
    parse_offline_review_findings,
)
from mergecraft.review.offline_agent import run_offline_agent_review
from mergecraft.review.offline_stages import run_offline_analyze
from mergecraft.review_taxonomy import FindingSource
from mergecraft.run_outcome import CLI_BLOCKED_EXIT_CODE, RunOutcome, cli_exit_code_for_review
from mergecraft.utils.offline_diff import DiffMaterialization
from mergecraft.utils.run_bounds import resolve_run_bounds
from mergecraft.utils.source_resolve import ResolvedWorkspace, SourceResolverSpec

_PATCH = "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"


def _real_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def _nonempty_materialization(out_dir: Path) -> DiffMaterialization:
    diff_path = out_dir / "change.diff"
    diff_path.write_text(_PATCH, encoding="utf-8")
    return DiffMaterialization(
        path=diff_path,
        base_ref="HEAD",
        line_count=_PATCH.count("\n"),
        empty=False,
    )


def _patch_harness(
    monkeypatch: pytest.MonkeyPatch, *, analyzers_enabled: bool
) -> list[dict[str, Any]]:
    settings = RepoSettings.model_construct(analyzers=AnalyzersSettings(enabled=analyzers_enabled))
    monkeypatch.setattr(
        "mergecraft.config.load_repo_settings",
        lambda root, load_learnings_files=False: settings,
    )
    monkeypatch.setattr(
        offline_mod, "load_repo_settings", lambda root, load_learnings_files=False: settings
    )
    monkeypatch.setattr(offline_mod, "resolve_offline_review_trust_tier", lambda **_: "trusted")
    monkeypatch.setattr(offline_mod, "apply_cli_trust_tier_env", lambda _: {})
    monkeypatch.setattr(offline_mod, "_apply_tracing_cli_overrides", lambda _: {})
    monkeypatch.setattr(
        "mergecraft.evidence.run_manifest.apply_local_telemetry_defaults",
        lambda **_: {},
    )
    monkeypatch.setattr(
        offline_mod,
        "apply_diff_line_budget",
        lambda text, *, max_lines: (text, None),
    )
    calls: list[dict[str, Any]] = []

    def _pipeline(**kwargs: object) -> object:
        calls.append(dict(kwargs))
        return type("State", (), {"ran": True, "reason": None})()

    monkeypatch.setattr("mergecraft.review.offline_stages.run_analyzer_pipeline", _pipeline)
    return calls


@pytest.mark.asyncio
async def test_offline_analyze_invokes_pipeline_when_analyzers_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: nonempty dry-run analyze calls ``run_analyzer_pipeline`` with trust + files."""
    calls = _patch_harness(monkeypatch, analyzers_enabled=True)
    repo = _real_git_repo(tmp_path)

    def _materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        return _nonempty_materialization(out_dir)

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)
    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)
    result = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        dry_run=True,
    )
    assert result.success is True
    assert result.outcome is RunOutcome.passed
    assert calls, "enabled analyzers must invoke run_analyzer_pipeline"
    call = calls[0]
    assert call["repo_root"] == repo
    changed = call["changed_files"]
    assert "demo.py" in list(changed)
    assert call["tier"] == "trusted"


@pytest.mark.asyncio
async def test_offline_analyze_skips_pipeline_when_analyzers_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edge: ``analyzers.enabled=False`` must not call the pipeline."""
    calls = _patch_harness(monkeypatch, analyzers_enabled=False)
    repo = _real_git_repo(tmp_path)

    def _materialize(
        workspace: ResolvedWorkspace,
        *,
        spec: SourceResolverSpec,
        out_dir: Path,
        diff_file: Path | None = None,
    ) -> DiffMaterialization:
        return _nonempty_materialization(out_dir)

    monkeypatch.setattr(offline_mod, "materialize_resolved_diff", _materialize)
    workspace = ResolvedWorkspace(cwd=repo, git_common_dir=repo / ".git", cloned=False)
    spec = SourceResolverSpec(cwd=repo, invocation_root=repo)
    result = await offline_mod._run_offline_diff_review(
        cwd=repo,
        workspace=workspace,
        spec=spec,
        review_root=repo,
        dry_run=True,
    )
    assert result.success is True
    assert calls == []


def _stub_pipeline_state() -> AnalyzerRunState:
    return AnalyzerRunState(ran=True, findings=[{"id": "f1"}])


@pytest.mark.asyncio
async def test_run_offline_analyze_returns_pipeline_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: ``run_offline_analyze`` returns the pipeline ``AnalyzerRunState``."""
    expected = _stub_pipeline_state()

    def _pipeline(**_kwargs: object) -> AnalyzerRunState:
        return expected

    monkeypatch.setattr("mergecraft.review.offline_stages.run_analyzer_pipeline", _pipeline)
    result = await run_offline_analyze(
        cwd=tmp_path,
        materialization=_nonempty_materialization(tmp_path),
        trust_tier="trusted",
        analyzers_enabled=True,
    )
    assert result is expected


@pytest.mark.asyncio
async def test_run_offline_analyze_returns_none_when_analyzers_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edge: ``analyzers_enabled=False`` skips the pipeline and returns ``None``."""
    calls: list[int] = []

    def _pipeline(**_kwargs: object) -> AnalyzerRunState:
        calls.append(1)
        return _stub_pipeline_state()

    monkeypatch.setattr("mergecraft.review.offline_stages.run_analyzer_pipeline", _pipeline)
    result = await run_offline_analyze(
        cwd=tmp_path,
        materialization=_nonempty_materialization(tmp_path),
        trust_tier="trusted",
        analyzers_enabled=False,
    )
    assert result is None
    assert calls == []


@pytest.mark.asyncio
async def test_run_offline_analyze_returns_ran_false_when_pipeline_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Error: unexpected pipeline exceptions become ``AnalyzerRunState(ran=False)``."""

    def _pipeline(**_kwargs: object) -> AnalyzerRunState:
        raise RuntimeError("boom")

    monkeypatch.setattr("mergecraft.review.offline_stages.run_analyzer_pipeline", _pipeline)
    result = await run_offline_analyze(
        cwd=tmp_path,
        materialization=_nonempty_materialization(tmp_path),
        trust_tier="trusted",
        analyzers_enabled=True,
    )
    assert result is not None
    assert result.ran is False
    assert result.reason == "boom"


@pytest.mark.asyncio
async def test_offline_analyze_stage_stores_run_state_on_driver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: ``_OfflineDiffReviewRun.analyze`` stores pipeline state as ``analyzer_run``."""
    expected = _stub_pipeline_state()

    async def _analyze(**_kwargs: object) -> AnalyzerRunState:
        return expected

    monkeypatch.setattr("mergecraft.review.offline_stages.run_offline_analyze", _analyze)
    driver = offline_mod._OfflineDiffReviewRun(
        cwd=tmp_path,
        workspace=ResolvedWorkspace(cwd=tmp_path, git_common_dir=tmp_path / ".git", cloned=False),
        spec=SourceResolverSpec(cwd=tmp_path, invocation_root=tmp_path),
        out_dir=tmp_path,
        diff_file=None,
        trust_tier="trusted",
        run_bounds=resolve_run_bounds(),
        analyzers_enabled=True,
        json_path=None,
        prompt_extra=None,
        dry_run=True,
        model=None,
        evidence_packet_path=None,
        on_finding=None,
        read_cache=False,
    )
    driver.materialization = _nonempty_materialization(tmp_path)
    await driver.analyze()
    assert driver.analyzer_run is expected


class _StubAgent:
    name = "claude"

    async def install(self, token: str | None = None) -> str:
        return "ok"

    async def run(self, _ctx: object) -> AgentResult:
        return AgentResult(success=True, output="ok")


class _FakeGithub:
    def __init__(self, token: str = "", **_: object) -> None:
        del token

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_run_offline_agent_review_stamps_analyzer_run_before_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy: ``analyzer_run`` is on ``tool_state`` before ``_emit_offline_packet``."""
    state = _stub_pipeline_state()
    captured: list[object] = []
    settings = RepoSettings(analyzers=AnalyzersSettings(enabled=True))

    monkeypatch.setattr(
        "mergecraft.review.offline_agent.load_repo_settings",
        lambda root, load_learnings_files=False: settings,
    )
    monkeypatch.setattr("mergecraft.review.offline_agent.GitHubClient", _FakeGithub)
    monkeypatch.setattr(
        "mergecraft.review.offline_agent.resolve_runtime_agent",
        lambda **_: _StubAgent(),
    )
    monkeypatch.setattr(
        "mergecraft.review.offline_agent.start_mcp_http_server",
        lambda ctx, *, output_schema=None: ("http://127.0.0.1:9/mcp", lambda: None),
    )
    monkeypatch.setattr("mergecraft.review.offline_agent.install_bundled_skills", lambda **_: None)
    monkeypatch.setattr(
        "mergecraft.enterprise.runtime.bind_enterprise_after_trust",
        lambda *_a, **_k: None,
    )

    def _emit(tool_context: object, **_kwargs: object) -> None:
        captured.append(tool_context)
        return

    monkeypatch.setattr("mergecraft.review.offline_agent._emit_offline_packet", _emit)

    result = await run_offline_agent_review(
        cwd=tmp_path,
        materialization=_nonempty_materialization(tmp_path),
        prompt="review this",
        model=None,
        tmpdir=tmp_path,
        analyzer_run=state,
    )
    assert result.success is True
    assert captured, "packet emit must run so consumers can see analyzer findings"
    tool_context = captured[0]
    tool_state = tool_context.tool_state
    assert tool_state.analyzer_run is state


def _finding(
    *,
    rule_id: str,
    severity: str,
    source: FindingSource,
    fingerprint: str | None = None,
    message: str = "analyzer finding",
) -> Finding:
    return make_finding(
        tool="ruff",
        rule_id=rule_id,
        category=(
            "Security & Privacy"
            if severity in {"Critical", "Major"}
            else "Maintainability & Code Quality"
        ),
        severity=severity,
        confidence="certain",
        message=message,
        path="demo.py",
        start_line=1,
        end_line=1,
        source=source,
        fingerprint=fingerprint,
    )


@pytest.mark.parametrize("severity", ["Critical", "Major"])
def test_merged_blocking_analyzer_finding_blocks_cli_exit(severity: str) -> None:
    """Unit: analyzer Critical/Major folded into a clean agent result blocks the CLI."""
    blocker = _finding(rule_id="SEC-1", severity=severity, source="analyzer")
    result = OfflineReviewResult(
        success=True,
        structured_output='{"findings":[]}',
        outcome=RunOutcome.passed,
    )
    merged = merge_analyzer_findings_into_result(result, [blocker])
    findings = parse_offline_review_findings(merged)
    assert any(row.fingerprint == blocker.fingerprint for row in findings)
    assert cli_exit_code_for_review(RunOutcome.passed, findings) == CLI_BLOCKED_EXIT_CODE


def test_merge_analyzer_findings_dedupes_by_fingerprint() -> None:
    """Unit: cache-hit merge keeps one row per fingerprint."""
    shared = "fp-shared"
    agent = _finding(
        rule_id="AGT-1",
        severity="Minor",
        source="agent",
        fingerprint=shared,
        message="from agent",
    )
    duplicate = _finding(
        rule_id="ANL-1",
        severity="Minor",
        source="analyzer",
        fingerprint=shared,
        message="from analyzer",
    )
    novel = _finding(
        rule_id="ANL-2",
        severity="Minor",
        source="analyzer",
        fingerprint="fp-novel",
        message="new analyzer finding",
    )
    result = OfflineReviewResult(
        success=True,
        structured_output=json.dumps({"findings": [agent.model_dump()]}),
        outcome=RunOutcome.passed,
    )
    merged = merge_analyzer_findings_into_result(result, [duplicate, novel])
    findings = parse_offline_review_findings(merged)
    fingerprints = [row.fingerprint for row in findings]
    assert fingerprints.count(shared) == 1
    assert "fp-novel" in fingerprints
    assert len(findings) == 2


def test_findings_from_analyzer_run_skips_invalid_rows() -> None:
    """Error: invalid analyzer rows are skipped, not raised."""
    valid = _finding(rule_id="OK-1", severity="Minor", source="analyzer")
    state = AnalyzerRunState(ran=True, findings=[{"id": "bad"}, valid.model_dump()])
    findings = findings_from_analyzer_run(state)
    assert [row.fingerprint for row in findings] == [valid.fingerprint]
