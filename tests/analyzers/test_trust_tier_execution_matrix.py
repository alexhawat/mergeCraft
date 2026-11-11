"""Analyzer execution per trust tier, built through the real trust resolver.

Every row resolves the run's tier with :func:`resolve_trust_policy` from an event
payload and a ``trust.selfReview`` setting, exactly as a review run does, and then
drives the real analyzer path (``run_analyzer_pipeline`` -> ``run_adapter`` ->
``plan_sandbox`` -> ``run_plan``). Only the host boundary is replaced: the
capability probe (so namespace argv is built on any host), managed-binary
provisioning (so nothing is downloaded), and the final process spawn, which is
recorded instead of executed. Assertions are on what would have been spawned.
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers import adapters, pipeline
from mergecraft.analyzers import run as run_mod
from mergecraft.analyzers import sandbox as sandbox_mod
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import run_plan
from mergecraft.analyzers.sandbox import (
    SandboxCapabilities,
    analyzer_run_root,
    fresh_analyzer_scratch_dir,
    plan_sandbox,
)
from mergecraft.config.trust_policy import resolve_trust_policy
from tests.analyzers.support import FORK_PULL_REQUEST_EVENT, SAME_REPO_PULL_REQUEST_EVENT

if TYPE_CHECKING:
    from collections.abc import Callable

_REPOSITORY = {"full_name": "alexhawat/mergeCraft", "fork": False, "owner": {"login": "alexhawat"}}

_PUSH_EVENT: dict[str, Any] = {"ref": "refs/heads/main", "repository": _REPOSITORY}
_DISPATCH_EVENT: dict[str, Any] = {
    "inputs": {},
    "ref": "refs/heads/main",
    "repository": _REPOSITORY,
}
_MEMBER_COMMENT_EVENT: dict[str, Any] = {
    "action": "created",
    "issue": {"number": 1},
    "comment": {"author_association": "MEMBER", "body": "/review"},
    "repository": _REPOSITORY,
}

_SECRET_NAME = "ANTHROPIC_API_KEY"
_SECRET_VALUE = "matrix-canary-not-a-real-key"


@dataclass(frozen=True)
class Row:
    """One trust-tier x event combination and its expected outcome."""

    name: str
    event_name: str
    event: dict[str, Any]
    self_review: str
    tier: str
    # Allowlisted analyzer (osv-scanner): is filtered egress applied?
    filtered_egress: bool


ROWS: tuple[Row, ...] = (
    Row("pr-same-repo", "pull_request", SAME_REPO_PULL_REQUEST_EVENT, "off", "trusted", False),
    Row("pr-fork", "pull_request", FORK_PULL_REQUEST_EVENT, "off", "untrusted", True),
    Row(
        "prt-same-repo",
        "pull_request_target",
        SAME_REPO_PULL_REQUEST_EVENT,
        "off",
        "untrusted",
        True,
    ),
    Row(
        "prt-same-repo-selfreview",
        "pull_request_target",
        SAME_REPO_PULL_REQUEST_EVENT,
        "analyzers",
        "trusted",
        True,
    ),
    Row(
        "prt-fork-selfreview",
        "pull_request_target",
        FORK_PULL_REQUEST_EVENT,
        "analyzers",
        "untrusted",
        True,
    ),
    Row("workflow-dispatch", "workflow_dispatch", _DISPATCH_EVENT, "off", "trusted", False),
    Row("push", "push", _PUSH_EVENT, "off", "untrusted", False),
    Row("issue-comment-member", "issue_comment", _MEMBER_COMMENT_EVENT, "off", "trusted", True),
)


@dataclass
class Spawn:
    argv: list[str]
    cwd: Path | None
    env: dict[str, str]
    preexec_fn: Any


class _FakeEgressSession:
    def __init__(self) -> None:
        self.closed = False

    def start(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def wrap_argv(self, argv: list[str]) -> list[str]:
        return ["fake-filtered-egress", *argv]


@pytest.fixture
def spawns(monkeypatch: pytest.MonkeyPatch) -> list[Spawn]:
    """Pin the host boundary; record every analyzer-path spawn instead of running it."""
    caps = SandboxCapabilities(
        pid_namespace=True,
        network_namespace=True,
        read_only_bind=True,
        tmpfs=True,
        cgroup_memory=True,
        rlimit_nproc=True,
        pid_namespace_method="unshare",
        unavailable_reasons=[],
    )
    monkeypatch.setattr(sandbox_mod, "probe_capabilities", lambda: caps)
    monkeypatch.setattr("mergecraft.mcp.shell.detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr("mergecraft.analyzers.egress.filtered_egress_available", lambda: True)
    monkeypatch.setattr(
        "mergecraft.analyzers.egress.start_filtered_egress_session",
        lambda _allowlist: _FakeEgressSession(),
    )
    # Identity handling is covered by its own suites; keep it host-independent here.
    monkeypatch.setattr(sandbox_mod, "build_privilege_drop_argv", lambda **_: [])
    monkeypatch.setattr(sandbox_mod, "resolve_drop_target_uid", lambda: None)
    monkeypatch.setattr(sandbox_mod, "resolve_drop_target_gid", lambda: None)
    monkeypatch.setattr(sandbox_mod, "process_limit_for_drop", lambda limit, **_: (limit, limit))
    monkeypatch.setenv(_SECRET_NAME, _SECRET_VALUE)

    recorded: list[Spawn] = []

    def _record(
        run_argv: list[str],
        *,
        cwd: Path | None,
        timeout_s: int,
        env: dict[str, str],
        pass_fds: tuple[int, ...],
        preexec_fn: Callable[[], None] | None,
    ) -> subprocess.CompletedProcess[str]:
        _ = timeout_s, pass_fds
        recorded.append(Spawn(list(run_argv), cwd, dict(env), preexec_fn))
        return subprocess.CompletedProcess(run_argv, 0, "[]", "")

    monkeypatch.setattr(run_mod, "_run_in_own_session", _record)
    return recorded


def _policy(tmp_path: Path, row: Row) -> Any:
    config_root = tmp_path / "base-config"
    (config_root / ".mergecraft").mkdir(parents=True)
    (config_root / ".mergecraft" / "config.yaml").write_text(
        f"trust:\n  selfReview: '{row.self_review}'\n", encoding="utf-8"
    )
    return resolve_trust_policy(
        event=dict(row.event), config_root=config_root, event_name=row.event_name
    )


def _repo_with_planted_tool(tmp_path: Path, tool: str) -> tuple[Path, Path, Path]:
    """A reviewed tree whose ``.venv/bin/<tool>`` leaves a marker if it is ever run."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "script.sh").write_text("#!/bin/sh\necho $1\n", encoding="utf-8")
    marker = tmp_path / "planted-tool-ran"
    bin_dir = repo / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    planted = bin_dir / tool
    planted.write_text(f"#!/bin/sh\ntouch '{marker}'\necho 9.9.9\n", encoding="utf-8")
    planted.chmod(planted.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return repo, planted.resolve(), marker


def _stub_managed_provisioning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    managed = tmp_path / "managed-cache" / "shellcheck"
    managed.parent.mkdir(parents=True)

    def _provision(plan: AnalyzerPlan, **_: Any) -> AnalyzerPlan:
        return AnalyzerPlan(
            manifest_id=plan.manifest_id,
            mode=plan.mode,
            argv=(str(managed), *plan.argv[1:]),
            cwd=plan.cwd,
            env=plan.env,
            timeout_s=plan.timeout_s,
            version_note=plan.version_note,
        )

    monkeypatch.setattr(adapters, "provision_managed_argv", _provision)
    return managed


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_resolver_tier_matches_the_expected_matrix(tmp_path: Path, row: Row) -> None:
    assert _policy(tmp_path, row).execution_trust == row.tier


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_analyzer_binary_source_and_isolation_follow_the_resolved_tier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spawns: list[Spawn],
    row: Row,
) -> None:
    """Untrusted: managed binary only, nothing from the tree spawned, namespaced.

    Trusted: the repo's own tool may be used, but its version probe goes through
    the analyzer spawn with the scrubbed environment, never the parent's.
    """
    policy = _policy(tmp_path, row)
    repo, planted, marker = _repo_with_planted_tool(tmp_path, "shellcheck")
    managed = _stub_managed_provisioning(monkeypatch, tmp_path)
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [get_manifest("shellcheck")])

    state = pipeline.run_analyzer_pipeline(
        repo_root=repo,
        changed_files=["script.sh"],
        tier=policy.execution_trust,
        shell="restricted",
        event_name=row.event_name,
        event=dict(row.event),
        self_review_level=policy.level,
    )

    assert not marker.exists(), "a binary from the reviewed tree was executed"
    assert spawns, f"nothing was spawned: {state.analyzers}"
    for spawn in spawns:
        assert _SECRET_VALUE not in spawn.env.values()
    analyzer = spawns[-1]
    if row.tier == "untrusted":
        assert len(spawns) == 1, "the untrusted tier must spawn only the analyzer itself"
        joined = " ".join(analyzer.argv)
        assert str(planted) not in joined
        assert str(managed) in joined
        assert analyzer.argv[0] == "unshare"
        assert "--net" in analyzer.argv
        assert isinstance(analyzer.preexec_fn, run_mod._SandboxPreexec)
    else:
        probe, run = spawns[0], spawns[-1]
        assert probe.argv == [str(planted), "--version"]
        assert probe.cwd is not None
        assert repo not in probe.cwd.parents
        assert run.argv[0] == str(planted)
        assert "unshare" not in run.argv
    # Orchestrator-side files never land in the reviewed tree.
    assert not (repo / ".mergecraft").exists()


_OSV_ARGV_TAIL = ("scan", "--format", "json", "-L")


def _osv_run(tmp_path: Path, row: Row) -> tuple[Any, Path]:
    policy = _policy(tmp_path, row)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    lockfile = repo / "requirements.txt"
    lockfile.write_text("requests==2.0.0\n", encoding="utf-8")
    manifest = get_manifest("osv-scanner")
    assert manifest.network_allowlist, "fixture needs an allowlist-declaring analyzer"
    decision = plan_sandbox(
        manifest=manifest,
        tier=policy.execution_trust,
        repo_root=repo,
        scratch_dir=fresh_analyzer_scratch_dir("osv-scanner"),
    )
    assert decision.can_run
    plan = AnalyzerPlan(
        manifest_id="osv-scanner",
        mode="managed",
        argv=("/managed/osv-scanner", *_OSV_ARGV_TAIL, str(lockfile)),
        cwd=repo,
    )
    outcome = run_plan(
        plan,
        sandbox_context=decision.context,
        event_name=row.event_name,
        event=dict(row.event),
        self_review_level=policy.level,
        analyzer_id="osv-scanner",
    )
    return outcome, repo


@pytest.mark.parametrize("row", ROWS, ids=[row.name for row in ROWS])
def test_filtered_egress_and_limits_follow_the_egress_decision(
    tmp_path: Path, spawns: list[Spawn], row: Row
) -> None:
    """Whenever the egress policy says ``filtered``, the run is wrapped and limited."""
    outcome, _repo = _osv_run(tmp_path, row)
    assert outcome.ran, outcome.output
    assert len(spawns) == 1
    argv = spawns[0].argv
    if row.filtered_egress:
        assert argv[0] == "fake-filtered-egress", argv
        assert "unshare" in argv
        assert isinstance(spawns[0].preexec_fn, run_mod._SandboxPreexec)
        # The scrubbed payload environment travels by descriptor, not in env.
        assert "MERGECRAFT_PAYLOAD_ENV_FD" in spawns[0].env
    elif row.tier == "untrusted":
        assert argv[0] == "unshare"
    else:
        assert argv[0] == "/managed/osv-scanner"


def test_trusted_self_review_run_fails_closed_when_egress_cannot_be_filtered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spawns: list[Spawn]
) -> None:
    monkeypatch.setattr("mergecraft.analyzers.egress.filtered_egress_available", lambda: False)
    row = next(row for row in ROWS if row.name == "prt-same-repo-selfreview")
    outcome, _repo = _osv_run(tmp_path, row)
    assert outcome.status == "unavailable"
    assert "egress policy" in outcome.output
    assert spawns == []


def test_orchestrator_scratch_is_outside_the_tree_and_fresh_per_run(tmp_path: Path) -> None:
    first = fresh_analyzer_scratch_dir("jscpd")
    (first / "jscpd-report.json").write_text("{}", encoding="utf-8")
    second = fresh_analyzer_scratch_dir("jscpd")
    assert second == first
    assert not (second / "jscpd-report.json").exists()
    assert analyzer_run_root() in second.parents
    assert Path(os.path.realpath(tmp_path)) not in second.parents
