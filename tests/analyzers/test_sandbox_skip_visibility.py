"""Lane A AP1.2 — skipped untrusted analyzers emit a user-visible finding (MCB-09 / D7)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def _missing_caps() -> object:
    return type(
        "C",
        (),
        {
            "pid_namespace": False,
            "network_namespace": False,
            "read_only_bind": False,
            "tmpfs": False,
            "cgroup_memory": False,
            "rlimit_nproc": True,
            "unavailable_reasons": ["pid namespace unavailable"],
        },
    )()


def test_skipped_untrusted_analyzers_emit_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft.analyzers.manifest import load_manifest_file
    from mergecraft.analyzers.sandbox import plan_sandbox

    manifest = load_manifest_file(Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml"))
    monkeypatch.setattr(
        "mergecraft.analyzers.sandbox.probe_capabilities",
        lambda: _missing_caps(),
    )
    plan = plan_sandbox(
        manifest=manifest,
        tier="untrusted",
        repo_root=Path("/tmp/repo"),
        scratch_dir=Path("/tmp/scratch"),
    )
    assert plan.can_run is False
    assert plan.skip_reason is not None
    finding = getattr(plan, "skip_finding", None) or getattr(plan, "finding", None)
    assert finding is not None, (
        "skipped untrusted tier must emit analyzers.sandbox-unavailable finding"
    )
    rule_id = getattr(finding, "rule_id", None) or (
        finding.get("rule_id") if isinstance(finding, dict) else None
    )
    assert rule_id == "analyzers.sandbox-unavailable"
    assert finding.start_line is None


def test_sandbox_unavailable_finding_survives_diff_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mergecraft.analyzers.manifest import load_manifest_file
    from mergecraft.analyzers.sandbox import plan_sandbox
    from mergecraft.analyzers.scope import scope_findings

    manifest = load_manifest_file(Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml"))
    monkeypatch.setattr(
        "mergecraft.analyzers.sandbox.probe_capabilities",
        lambda: _missing_caps(),
    )
    plan = plan_sandbox(
        manifest=manifest,
        tier="untrusted",
        repo_root=Path("/tmp/repo"),
        scratch_dir=Path("/tmp/scratch"),
    )
    assert plan.skip_finding is not None
    diff = """diff --git a/src/app.py b/src/app.py
@@ -1,3 +1,4 @@
 def run():
+    return 1
     pass
"""
    kept = scope_findings([plan.skip_finding], diff_text=diff)
    assert len(kept) == 1
    assert kept[0].rule_id == "analyzers.sandbox-unavailable"


def test_sandbox_unavailable_finding_survives_pipeline_scoping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mergecraft.analyzers import pipeline
    from mergecraft.analyzers.registry import get_manifest

    settings_mod = __import__("mergecraft.config.settings", fromlist=["AnalyzersSettings"])
    monkeypatch.setattr(
        pipeline,
        "_analyzers_settings",
        lambda _root: settings_mod.AnalyzersSettings(),
    )
    monkeypatch.setattr(
        pipeline,
        "detect_enabled",
        lambda **_: [get_manifest("actionlint")],
    )
    monkeypatch.setattr(
        "mergecraft.analyzers.sandbox.probe_capabilities",
        lambda: _missing_caps(),
    )

    diff = """diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
@@ -1,3 +1,4 @@
 name: ci
+  pull_request:
 jobs: {}
"""
    state = pipeline.run_analyzer_pipeline(
        repo_root=tmp_path,
        changed_files=[".github/workflows/ci.yml"],
        tier="untrusted",
        diff_text=diff,
    )
    rule_ids = [row.get("rule_id") for row in state.findings]
    assert "analyzers.sandbox-unavailable" in rule_ids
    assert state.findings, "sandbox-unavailable finding must appear in review output"
