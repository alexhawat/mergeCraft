"""The ``--shell`` value must reach the analyzer pipeline *and* the MCP payload.

A split brain — pipeline sees ``enabled`` while the resolved payload still says
``disabled`` (or the reverse) — is the bug these tests lock out.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.registry import load_catalog
from mergecraft.analyzers.trust import evaluate_manifest_for_shell
from mergecraft.mcp.tool_state import AnalyzerRunState
from mergecraft.offline_review import _OfflineDiffReviewRun
from mergecraft.review.offline_result import OfflineReviewResult
from mergecraft.review.offline_stages import run_offline_analyze
from mergecraft.utils.offline_diff import DiffMaterialization
from mergecraft.utils.run_bounds import resolve_run_bounds

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

_DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+import os\n"


def _materialization(tmp_path: Path) -> DiffMaterialization:
    path = tmp_path / "changes.patch"
    path.write_text(_DIFF, encoding="utf-8")
    return DiffMaterialization(path=path, base_ref="main", line_count=5, empty=False)


def _capture_pipeline(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def fake_pipeline(**kwargs: Any) -> AnalyzerRunState:
        seen.update(kwargs)
        return AnalyzerRunState(ran=False, reason="stubbed")

    monkeypatch.setattr(
        "mergecraft.review.offline_stages.run_analyzer_pipeline",
        fake_pipeline,
    )
    return seen


@pytest.mark.asyncio
async def test_run_offline_analyze_defaults_to_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _capture_pipeline(monkeypatch)
    await run_offline_analyze(
        cwd=tmp_path,
        materialization=_materialization(tmp_path),
        trust_tier="trusted",
    )
    assert seen["shell"] == "disabled"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["restricted", "enabled"])
async def test_run_offline_analyze_forwards_shell(
    value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _capture_pipeline(monkeypatch)
    await run_offline_analyze(
        cwd=tmp_path,
        materialization=_materialization(tmp_path),
        trust_tier="trusted",
        shell=value,  # type: ignore[arg-type]
    )
    assert seen["shell"] == value


def _driver(tmp_path: Path, shell: str) -> _OfflineDiffReviewRun:
    driver = _OfflineDiffReviewRun(
        cwd=tmp_path,
        workspace=None,  # type: ignore[arg-type]
        spec=None,  # type: ignore[arg-type]
        out_dir=tmp_path,
        diff_file=None,
        trust_tier="trusted",
        shell=shell,  # type: ignore[arg-type]
        run_bounds=resolve_run_bounds(),
        analyzers_enabled=True,
        json_path=None,
        prompt_extra=None,
        dry_run=False,
        model=None,
        evidence_packet_path=None,
        on_finding=None,
        read_cache=False,
    )
    driver.materialization = _materialization(tmp_path)
    return driver


@pytest.mark.asyncio
@pytest.mark.parametrize("shell", ["disabled", "enabled"])
async def test_driver_sends_one_shell_value_to_both_sites(
    shell: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Analyzer pipeline and agent (ResolvedPayload owner) get the same value."""
    analyze_seen: dict[str, Any] = {}
    agent_seen: dict[str, Any] = {}

    async def fake_analyze(**kwargs: Any) -> None:
        analyze_seen.update(kwargs)

    async def fake_agent_review(**kwargs: Any) -> OfflineReviewResult:
        agent_seen.update(kwargs)
        return OfflineReviewResult(success=True, output="ok")

    monkeypatch.setattr(
        "mergecraft.review.offline_stages.run_offline_analyze",
        fake_analyze,
    )
    monkeypatch.setattr(
        "mergecraft.offline_review.run_offline_agent_review",
        fake_agent_review,
    )
    monkeypatch.setattr("mergecraft.offline_review.resolve_model", lambda **_: "test-model")

    driver = _driver(tmp_path, shell)
    await driver.analyze()
    await driver.review()

    assert analyze_seen["shell"] == shell
    assert agent_seen["shell"] == shell


@pytest.mark.asyncio
@pytest.mark.parametrize("shell", ["disabled", "enabled"])
async def test_agent_review_puts_shell_on_resolved_payload(
    shell: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run_offline_agent_review`` stamps the resolved value onto the payload."""
    from mergecraft.mcp.context import ResolvedPayload

    seen: dict[str, Any] = {}

    def capture_payload(**kwargs: Any) -> ResolvedPayload:
        seen.update(kwargs)
        return ResolvedPayload(**kwargs)

    class _FakeAgent:
        name = "claude"

    monkeypatch.setattr("mergecraft.review.offline_agent.ResolvedPayload", capture_payload)
    monkeypatch.setattr(
        "mergecraft.review.offline_agent.resolve_runtime_agent",
        lambda **_: _FakeAgent(),
    )
    monkeypatch.setattr("mergecraft.review.offline_agent.resolve_model", lambda **_: "test-model")

    def _stop_after_payload(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("stop after payload construction")

    monkeypatch.setattr(
        "mergecraft.review.offline_agent.start_mcp_http_server",
        _stop_after_payload,
    )

    from mergecraft.review.offline_agent import run_offline_agent_review

    result = await run_offline_agent_review(
        cwd=tmp_path,
        materialization=_materialization(tmp_path),
        prompt="review this",
        model=None,
        tmpdir=tmp_path,
        shell=shell,  # type: ignore[arg-type]
    )
    assert not result.success
    assert seen["shell"] == shell


def _manifest(analyzer_id: str) -> AnalyzerManifest:
    for manifest in load_catalog():
        if manifest.id == analyzer_id:
            return manifest
    pytest.skip(f"catalog manifest {analyzer_id} not present")


@pytest.mark.parametrize("analyzer_id", ["ruff", "mypy"])
def test_repo_native_manifest_gate_follows_shell(analyzer_id: str) -> None:
    """A repo-native analyzer is withheld at ``disabled`` and eligible above it."""
    manifest = _manifest(analyzer_id)
    assert manifest.runtime == "repo-native"

    withheld = evaluate_manifest_for_shell(manifest=manifest, shell="disabled")
    assert withheld.skipped
    assert "shell: disabled" in (withheld.reason or "")

    for permissive in ("restricted", "enabled"):
        assert not evaluate_manifest_for_shell(manifest=manifest, shell=permissive).skipped
