"""C4 — ``mergecraft review --with-coverage --with-mutation`` (C-D1, C-D7, C-D8)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

import pytest
from tests.ci.support_crap import (
    DEFAULT_MAX_MUTANTS,
    DEFAULT_TIMEOUT_SECONDS,
    SKIP_EXECUTION_FAILED,
    SKIP_NO_SANDBOX_BACKEND,
    SKIP_TOOLCHAIN_ABSENT,
    SKIP_UNTRUSTED_TIER,
    import_ci,
    load_band_coverage,
    load_diff,
    load_mutation,
    load_source,
)
from typer.testing import CliRunner

from mergecraft.analyzers.trust import ReviewSource, derive_source_trust_tier
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE
from mergecraft.offline_review import OfflineReviewResult

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _fork_checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "init")
    _git(repo, "remote", "add", "origin", "https://github.com/owner/repo.git")
    _git(repo, "remote", "add", "contributor", "https://github.com/contributor/repo.git")
    _git(repo, "checkout", "-b", "fork-pr")
    _git(repo, "config", "branch.fork-pr.remote", "contributor")
    _git(repo, "config", "branch.fork-pr.merge", "refs/heads/fork-pr")
    return repo


def _same_repo_checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "same"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-m", "init")
    _git(repo, "remote", "add", "origin", "https://github.com/owner/repo.git")
    _git(repo, "config", "branch.main.remote", "origin")
    _git(repo, "config", "branch.main.merge", "refs/heads/main")
    return repo


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _local() -> Any:
    return import_ci("local_evidence")


@pytest.fixture
def captured_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    async def fake_run_offline_diff_review(**kwargs: Any) -> OfflineReviewResult:
        seen.update(kwargs)
        return OfflineReviewResult(success=True, output="ok")

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )
    return seen


@pytest.fixture
def diff_file(tmp_path: Path) -> Path:
    path = tmp_path / "changes.patch"
    path.write_text(load_diff("watch"), encoding="utf-8")
    return path


def test_review_help_documents_coverage_and_mutation_flags() -> None:
    result = runner.invoke(
        app,
        ["review", "--help"],
        env={"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "200"},
    )
    assert result.exit_code == 0
    out = " ".join(_plain(result.stdout).replace("│", " ").split())
    assert "--with-coverage" in out
    assert "--with-mutation" in out
    assert "--shell enabled" in out


def test_review_forwards_with_coverage_and_with_mutation(
    captured_kwargs: dict[str, Any], diff_file: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "review",
            "--diff",
            str(diff_file),
            "--dry-run",
            "--shell",
            "enabled",
            "--with-coverage",
            "--with-mutation",
        ],
    )
    assert result.exit_code == 0
    assert captured_kwargs["with_coverage"] is True
    assert captured_kwargs["with_mutation"] is True
    assert captured_kwargs["shell"] == "enabled"


def test_review_with_coverage_refuses_shell_disabled(
    captured_kwargs: dict[str, Any], diff_file: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "review",
            "--diff",
            str(diff_file),
            "--dry-run",
            "--with-coverage",
        ],
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert captured_kwargs == {}
    assert "require --shell enabled" in _plain(result.stdout + result.stderr)


def test_review_with_coverage_refuses_shell_restricted(
    captured_kwargs: dict[str, Any], diff_file: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "review",
            "--diff",
            str(diff_file),
            "--dry-run",
            "--shell",
            "restricted",
            "--with-coverage",
        ],
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert captured_kwargs == {}
    assert "require --shell enabled" in _plain(result.stdout + result.stderr)


def test_untrusted_tier_refuses_local_coverage() -> None:
    local = _local()
    with pytest.raises(local.LocalEvidenceRefused) as exc_info:
        local.require_trusted_sandboxed_execution(
            trust_tier="untrusted",
            sandbox_backend="unshare",
        )
    assert exc_info.value.code == SKIP_UNTRUSTED_TIER


def test_no_sandbox_backend_refuses_local_mutation() -> None:
    local = _local()
    with pytest.raises(local.LocalEvidenceRefused) as exc_info:
        local.require_trusted_sandboxed_execution(
            trust_tier="trusted",
            sandbox_backend="none",
        )
    assert exc_info.value.code == SKIP_NO_SANDBOX_BACKEND


def test_unsandboxed_shell_env_does_not_fail_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-D7 / #593: this plan refuses rather than inheriting fail-open."""
    monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
    local = _local()
    with pytest.raises(local.LocalEvidenceRefused) as exc_info:
        local.require_trusted_sandboxed_execution(
            trust_tier="trusted",
            sandbox_backend="none",
        )
    assert exc_info.value.code == SKIP_NO_SANDBOX_BACKEND


def test_run_local_coverage_does_not_execute_on_untrusted_tier(tmp_path: Path) -> None:
    local = _local()
    result = local.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="untrusted",
        sandbox_backend="unshare",
    )
    assert result.executed is False
    assert result.skip_reason == SKIP_UNTRUSTED_TIER
    assert result.findings == []


def test_run_local_mutation_does_not_execute_without_sandbox(tmp_path: Path) -> None:
    local = _local()
    result = local.run_local_mutation(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="none",
    )
    assert result.executed is False
    assert result.skip_reason == SKIP_NO_SANDBOX_BACKEND
    assert result.findings == []


def test_review_with_coverage_refuses_untrusted_cli(
    captured_kwargs: dict[str, Any], diff_file: Path
) -> None:
    result = runner.invoke(
        app,
        [
            "review",
            "--diff",
            str(diff_file),
            "--dry-run",
            "--shell",
            "enabled",
            "--trust",
            "untrusted",
            "--with-coverage",
        ],
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert captured_kwargs == {}


def test_empty_path_allowlist_uses_changed_paths_only() -> None:
    local = _local()
    planned = local.plan_local_mutation_paths(
        changed_paths=["src/a.py", "src/b.py"],
        repo_paths=["src/a.py", "src/b.py", "src/c.py", "tests/test_a.py"],
        path_allowlist=[],
    )
    assert set(planned) == {"src/a.py", "src/b.py"}
    assert "src/c.py" not in planned
    assert "tests/test_a.py" not in planned


def test_path_allowlist_intersects_changed_paths() -> None:
    local = _local()
    planned = local.plan_local_mutation_paths(
        changed_paths=["src/a.py", "src/b.py"],
        repo_paths=["src/a.py", "src/b.py", "src/c.py"],
        path_allowlist=["src/a.py", "src/c.py"],
    )
    assert planned == ["src/a.py"] or set(planned) == {"src/a.py"}


def test_max_mutants_bound_is_enforced() -> None:
    local = _local()
    bounded = local.bound_mutants(list(range(200)), max_mutants=DEFAULT_MAX_MUTANTS)
    assert len(bounded) <= DEFAULT_MAX_MUTANTS
    assert DEFAULT_MAX_MUTANTS == 50


def test_parse_discovered_mutmut_keys_tolerates_progress_noise() -> None:
    local = _local()
    stdout = '\n⠋ Running stats\n    done\n["mypkg.a.x_a__mutmut_1", "mypkg.a.x_a__mutmut_2"]\n'
    assert local._parse_discovered_mutmut_keys(stdout) == [
        "mypkg.a.x_a__mutmut_1",
        "mypkg.a.x_a__mutmut_2",
    ]


def test_mutmut_python_executable_uses_tool_shebang(tmp_path: Path) -> None:
    local = _local()
    python = tmp_path / "python"
    mutmut = tmp_path / "mutmut"
    python.write_text("", encoding="utf-8")
    mutmut.write_text(f"#!{python}\n", encoding="utf-8")
    assert local._mutmut_python_executable(str(mutmut)) == str(python)


def test_ephemeral_mutmut_config_preserves_existing_sections(tmp_path: Path) -> None:
    local = _local()
    setup_cfg = tmp_path / "setup.cfg"
    setup_cfg.write_text(
        "[pytest]\naddopts = -q\n\n[mutmut]\nrunner = pytest\n",
        encoding="utf-8",
    )
    with local._ephemeral_mutmut_config(
        tmp_path,
        only_mutate=["src/a.py"],
        source_paths=["src"],
    ):
        merged = setup_cfg.read_text(encoding="utf-8")
    assert "[pytest]" in merged
    assert "addopts = -q" in merged
    assert "only_mutate" in merged
    assert "src/a.py" in merged
    restored = setup_cfg.read_text(encoding="utf-8")
    assert restored == "[pytest]\naddopts = -q\n\n[mutmut]\nrunner = pytest\n"


def test_execute_mutation_bounds_discovered_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    seen: dict[str, Any] = {}

    def fake_which(name: str) -> str | None:
        return "/usr/bin/mutmut" if name == "mutmut" else None

    def fake_wrap(argv: list[str], *, repo_root: Path) -> list[str]:
        return ["unshare", *argv]

    def fake_discover(
        repo_root: Path,
        patterns: Sequence[str],
        *,
        mutmut_executable: str,
        timeout_seconds: int,
    ) -> list[str]:
        seen["patterns"] = list(patterns)
        seen["mutmut_executable"] = mutmut_executable
        return [f"mod.x_fn__mutmut_{index}" for index in range(120)]

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        if cmd and cmd[0] == "unshare" and cmd[1] == "/usr/bin/mutmut":
            seen["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def fake_export(repo_root: Path) -> Path:
        dest = repo_root / "mutmut-results.json"
        dest.write_text('{"schema_version":1,"mutants":[]}', encoding="utf-8")
        return dest

    monkeypatch.setattr(local, "checkout_is_fork_pr", lambda _root: False)
    monkeypatch.setattr(local, "_sandboxed_argv", fake_wrap)
    monkeypatch.setattr(local, "_discover_mutmut_keys", fake_discover)
    monkeypatch.setattr(local, "_export_mutmut_json", fake_export)
    monkeypatch.setattr(local.shutil, "which", fake_which)
    monkeypatch.setattr(local.subprocess, "run", fake_run)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    artifact = local._execute_mutation(
        tmp_path,
        timeout_seconds=120,
        paths=["src/a.py"],
        diff=(
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n+++ b/src/a.py\n"
            "@@ -1,2 +1,2 @@\n def a():\n-    return 1\n+    return 0\n"
        ),
        max_mutants=12,
    )
    assert artifact is not None
    cmd = seen["cmd"]
    assert cmd[2] == "run"
    assert len(cmd) == 3 + 12
    assert "mod.x_fn__mutmut_0" in cmd
    assert "mod.x_fn__mutmut_11" in cmd
    assert "mod.x_fn__mutmut_12" not in cmd


def test_timeout_seconds_default_is_300() -> None:
    from mergecraft.config.settings import default_settings

    settings = default_settings()
    assert settings.mutation.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert settings.coverage.timeout_seconds == DEFAULT_TIMEOUT_SECONDS


def test_local_coverage_findings_are_analyzer_source(tmp_path: Path) -> None:
    local = _local()
    artifact = tmp_path / "coverage.json"
    artifact.write_text(load_band_coverage("watch"), encoding="utf-8")
    result = local.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        source_tree={"src/mod.py": load_source("watch")},
        trust_tier="trusted",
        sandbox_backend="unshare",
        produced_artifact=artifact,
        toolchain_available=True,
    )
    assert result.findings
    assert all(item.source == "analyzer" for item in result.findings)


def test_absent_toolchain_is_honest_skip_not_silent_pass(tmp_path: Path) -> None:
    local = _local()
    result = local.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=False,
    )
    assert result.executed is False
    assert result.skip_reason == SKIP_TOOLCHAIN_ABSENT
    assert result.findings == []


def test_local_mutation_findings_are_analyzer_source(tmp_path: Path) -> None:
    local = _local()
    artifact = tmp_path / "mutmut-survivor.json"
    artifact.write_text(load_mutation("mutmut-survivor.json"), encoding="utf-8")
    result = local.run_local_mutation(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        source_tree={"src/mod.py": load_source("watch")},
        trust_tier="trusted",
        sandbox_backend="unshare",
        produced_artifact=artifact,
        toolchain_available=True,
    )
    assert result.findings
    assert all(item.source == "analyzer" for item in result.findings)


def test_coverage_timeout_is_honest_skip_not_silent_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    monkeypatch.setattr(local, "_execute_coverage", lambda *args, **kwargs: None)
    result = local.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
    )
    assert result.executed is False
    assert result.skip_reason == SKIP_EXECUTION_FAILED
    assert result.findings == []


def test_mutation_missing_json_is_honest_skip_not_silent_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    monkeypatch.setattr(local, "_execute_mutation", lambda *args, **kwargs: None)
    result = local.run_local_mutation(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
    )
    assert result.executed is False
    assert result.skip_reason == SKIP_EXECUTION_FAILED
    assert result.findings == []


def test_mutmut_run_uses_supported_selection_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    seen: dict[str, Any] = {}

    def fake_which(name: str) -> str | None:
        return "/usr/bin/mutmut" if name == "mutmut" else None

    def fake_wrap(argv: list[str], *, repo_root: Path) -> list[str]:
        return ["unshare", *argv]

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        if cmd and cmd[0] == "unshare":
            seen["cmd"] = list(cmd)
            cwd = kwargs.get("cwd")
            if cwd is not None:
                seen["setup_cfg"] = (cwd / "setup.cfg").read_text(encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def fake_export(repo_root: Path) -> Path:
        dest = repo_root / "mutmut-results.json"
        dest.write_text('{"schema_version":1,"mutants":[]}', encoding="utf-8")
        return dest

    def fake_discover(
        repo_root: Path,
        patterns: Sequence[str],
        *,
        mutmut_executable: str,
        timeout_seconds: int,
    ) -> list[str]:
        return ["a.x_a__mutmut_1"]

    monkeypatch.setattr(local, "checkout_is_fork_pr", lambda _root: False)
    monkeypatch.setattr(local, "_sandboxed_argv", fake_wrap)
    monkeypatch.setattr(local, "_discover_mutmut_keys", fake_discover)
    monkeypatch.setattr(local, "_export_mutmut_json", fake_export)
    monkeypatch.setattr(local.shutil, "which", fake_which)
    monkeypatch.setattr(local.subprocess, "run", fake_run)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tmp_path / "setup.cfg").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    result = local.run_local_mutation(
        repo_root=tmp_path,
        diff=(
            "diff --git a/src/a.py b/src/a.py\n"
            "--- a/src/a.py\n+++ b/src/a.py\n"
            "@@ -1,2 +1,2 @@\n def a():\n-    return 1\n+    return 0\n"
        ),
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
        max_mutants=50,
        path_allowlist=[],
    )
    cmd = seen["cmd"]
    assert cmd[0] == "unshare"
    assert cmd[1] == "/usr/bin/mutmut"
    assert cmd[2] == "run"
    assert "a.x_a__mutmut_1" in cmd
    assert "--paths-to-mutate" not in cmd
    assert "1-50" not in cmd
    setup_cfg = seen["setup_cfg"]
    assert "only_mutate" in setup_cfg
    assert "src/a.py" in setup_cfg
    assert "[pytest]" in setup_cfg
    assert "addopts = -q" in setup_cfg
    assert result.executed is True


@pytest.mark.skipif(
    shutil.which("mutmut") is None,
    reason="mutmut not installed",
)
def test_mutmut_live_subprocess_exports_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    pkg = tmp_path / "mypkg"
    tests = tmp_path / "tests"
    pkg.mkdir()
    tests.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    (tests / "test_a.py").write_text(
        "from mypkg.a import a\n\n\ndef test_a():\n    assert a() == 1\n",
        encoding="utf-8",
    )

    def fake_wrap(argv: list[str], *, repo_root: Path) -> list[str]:
        return argv

    monkeypatch.setattr(local, "checkout_is_fork_pr", lambda _root: False)
    monkeypatch.setattr(local, "_sandboxed_argv", fake_wrap)
    diff = (
        "diff --git a/mypkg/a.py b/mypkg/a.py\n"
        "--- a/mypkg/a.py\n+++ b/mypkg/a.py\n"
        "@@ -1,2 +1,2 @@\n def a():\n-    return 1\n+    return 0\n"
    )
    artifact = local._execute_mutation(
        tmp_path,
        timeout_seconds=120,
        paths=["mypkg/a.py"],
        diff=diff,
        max_mutants=10,
    )
    assert artifact is not None
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["mutants"]
    assert any(row["status"] == "killed" for row in payload["mutants"])


def test_leftover_mutation_report_is_not_treated_as_live_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    stale = tmp_path / "mutation-report.json"
    stale.write_text('{"files":[]}', encoding="utf-8")

    def fake_which(name: str) -> str | None:
        return "/usr/bin/mutmut" if name == "mutmut" else None

    def fake_wrap(argv: list[str], *, repo_root: Path) -> list[str]:
        return ["unshare", *argv]

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr(local, "checkout_is_fork_pr", lambda _root: False)
    monkeypatch.setattr(local, "_sandboxed_argv", fake_wrap)
    monkeypatch.setattr(local.shutil, "which", fake_which)
    monkeypatch.setattr(local.subprocess, "run", fake_run)
    result = local.run_local_mutation(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
    )
    assert result.executed is False
    assert result.skip_reason == SKIP_EXECUTION_FAILED
    assert result.findings == []


def test_failed_coverage_run_ignores_stale_data_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    calls: list[list[str]] = []

    def fake_wrap(argv: list[str], *, repo_root: Path) -> list[str]:
        return ["unshare", *argv]

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        calls.append(list(cmd))
        if any(part == "run" for part in cmd):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(local, "checkout_is_fork_pr", lambda _root: False)
    monkeypatch.setattr(local, "_sandboxed_argv", fake_wrap)
    monkeypatch.setattr(local.subprocess, "run", fake_run)
    result = local.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
    )
    assert result.executed is False
    assert result.skip_reason == SKIP_EXECUTION_FAILED
    assert any(part == "run" for cmd in calls for part in cmd)
    assert not any(part == "json" for cmd in calls for part in cmd)


def test_live_execution_wraps_via_sandbox_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    wrapped_calls: list[list[str]] = []

    def fake_wrap(argv: list[str], *, repo_root: Path) -> list[str]:
        wrapped_calls.append(list(argv))
        return ["unshare", *argv]

    monkeypatch.setattr(local, "checkout_is_fork_pr", lambda _root: False)
    monkeypatch.setattr(local, "_sandboxed_argv", fake_wrap)

    ran: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        if cmd and cmd[0] == "unshare":
            ran.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="")

    monkeypatch.setattr(local.subprocess, "run", fake_run)
    result = local.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
    )
    assert wrapped_calls
    assert all(cmd[0] == "unshare" for cmd in ran)
    assert result.executed is False
    assert result.skip_reason == SKIP_EXECUTION_FAILED


def test_live_execution_refuses_when_wrap_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
    monkeypatch.setattr(local, "checkout_is_fork_pr", lambda _root: False)
    monkeypatch.setattr("mergecraft.mcp.shell.detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(
        "mergecraft.analyzers.sandbox.build_analyzer_sandbox_argv",
        lambda argv, **kwargs: list(argv),
    )
    ran: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        ran.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(local.subprocess, "run", fake_run)
    result = local.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
    )
    assert result.executed is False
    assert result.skip_reason == SKIP_NO_SANDBOX_BACKEND
    assert not any("coverage" in " ".join(cmd) or "pytest" in " ".join(cmd) for cmd in ran)


def test_live_execution_refuses_when_sandbox_method_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
    monkeypatch.setattr(local, "checkout_is_fork_pr", lambda _root: False)
    monkeypatch.setattr("mergecraft.mcp.shell.detect_sandbox_method", lambda: "none")
    ran: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        ran.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(local.subprocess, "run", fake_run)
    result = local.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
    )
    assert result.executed is False
    assert result.skip_reason == SKIP_NO_SANDBOX_BACKEND
    assert not any("coverage" in " ".join(cmd) or "pytest" in " ".join(cmd) for cmd in ran)


def test_fork_checkout_is_untrusted_for_local_evidence(tmp_path: Path) -> None:
    local = _local()
    repo = _fork_checkout(tmp_path)
    source = ReviewSource(kind="local_cwd", path=repo, invocation_root=repo)
    assert derive_source_trust_tier(source) == "trusted"
    assert local.checkout_is_fork_pr(repo) is True
    result = local.run_local_coverage(
        repo_root=repo,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="unshare",
    )
    assert result.executed is False
    assert result.skip_reason == SKIP_UNTRUSTED_TIER
    assert result.findings == []


def test_same_repo_origin_branch_is_not_a_fork_checkout(tmp_path: Path) -> None:
    local = _local()
    repo = _same_repo_checkout(tmp_path)
    assert local.checkout_is_fork_pr(repo) is False


def test_review_with_coverage_refuses_fork_checkout(
    tmp_path: Path, captured_kwargs: dict[str, Any]
) -> None:
    repo = _fork_checkout(tmp_path)
    diff_file = repo / "changes.patch"
    diff_file.write_text(load_diff("watch"), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "review",
            "--cwd",
            str(repo),
            "--diff",
            str(diff_file),
            "--dry-run",
            "--shell",
            "enabled",
            "--with-coverage",
        ],
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert captured_kwargs == {}
