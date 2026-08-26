"""Lane A AP1.2 — skipped untrusted analyzers emit a user-visible finding (MCB-09 / D7)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def test_skipped_untrusted_analyzers_emit_a_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft.analyzers.manifest import load_manifest_file
    from mergecraft.analyzers.sandbox import plan_sandbox

    manifest = load_manifest_file(Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml"))
    monkeypatch.setattr(
        "mergecraft.analyzers.sandbox.probe_capabilities",
        lambda: type(
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
        )(),
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
