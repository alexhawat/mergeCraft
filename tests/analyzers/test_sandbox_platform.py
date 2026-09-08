"""Unsupported platforms refuse untrusted analyzer execution before launch."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from loguru import logger

from mergecraft.analyzers import execution, sandbox
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan


@pytest.fixture(autouse=True)
def clear_probe_cache() -> None:
    sandbox.probe_capabilities.cache_clear()


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_unsupported_platform_never_launches_linux_probe(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setattr(sandbox, "sys", SimpleNamespace(platform=platform))
    monkeypatch.delenv("MERGECRAFT_PROBE_TEST_DOUBLE", raising=False)
    monkeypatch.setattr(
        sandbox.subprocess, "run", lambda *a, **k: pytest.fail("Linux probe launched")
    )
    caps = sandbox.probe_capabilities()
    assert not caps.pid_namespace
    assert not caps.network_namespace
    assert not caps.read_only_bind
    assert not caps.tmpfs
    assert platform in caps.unavailable_reasons[0]
    assert "Action container" not in "; ".join(caps.unavailable_reasons)


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_production_execution_refuses_missing_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str
) -> None:
    monkeypatch.setattr(sandbox, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(sandbox, "_run_isolation_probe", dict)
    plan = AnalyzerPlan(
        manifest_id="actionlint",
        argv=("touch", str(tmp_path / "launched")),
        cwd=tmp_path,
        mode="native",
    )
    monkeypatch.setattr(execution, "resolve_analyzer", lambda **k: plan)
    monkeypatch.setattr(execution, "provision_resolved_plan", lambda p, **k: p)
    monkeypatch.setattr(execution, "finalize_plan", lambda p, **k: p)
    monkeypatch.setattr(
        execution, "run_plan", lambda *a, **k: pytest.fail("Untrusted repository command launched")
    )
    raw, reason, findings = execution.run_argv(
        manifest=get_manifest("actionlint"),
        repo_root=tmp_path,
        argv=plan.argv,
        changed_files=[],
        tier="untrusted",
    )
    assert raw is None
    assert reason is not None
    assert "isolation unavailable" in reason
    assert findings[0].rule_id == "analyzers.sandbox-unavailable"
    assert not (tmp_path / "launched").exists()


def test_trusted_execution_reports_incomplete_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sandbox, "_run_isolation_probe", dict)
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)))
    try:
        plan = sandbox.plan_sandbox(
            repo_root=tmp_path, scratch_dir=tmp_path / "scratch", tier="trusted"
        )
    finally:
        logger.remove(sink)
    assert plan.can_run
    assert any("not a sandbox guarantee" in message for message in messages)
