"""C4 — ``mergecraft review --with-coverage --with-mutation`` (C-D1, C-D7, C-D8)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

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

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE
from mergecraft.offline_review import OfflineReviewResult

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


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
            "--with-coverage",
            "--with-mutation",
        ],
    )
    assert result.exit_code == 0
    assert captured_kwargs["with_coverage"] is True
    assert captured_kwargs["with_mutation"] is True


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
            "--trust",
            "untrusted",
            "--with-coverage",
        ],
    )
    assert result.exit_code == CLI_CONFIGURATION_EXIT_CODE
    assert captured_kwargs.get("with_coverage") in {True, None}


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


def test_mutmut_run_receives_max_mutants_id_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _local()
    seen: dict[str, Any] = {}

    def fake_which(name: str) -> str | None:
        return "/usr/bin/mutmut" if name == "mutmut" else None

    def fake_run(cmd: list[str], **kwargs: Any) -> Any:
        seen["cmd"] = list(cmd)
        return type("Completed", (), {"returncode": 0})()

    monkeypatch.setattr(local.shutil, "which", fake_which)
    monkeypatch.setattr(local.subprocess, "run", fake_run)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
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
    assert "1-50" in seen["cmd"]
    assert result.executed is False
    assert result.skip_reason == SKIP_EXECUTION_FAILED
