"""Local evidence runs remove their temporary trees (#1566)."""

from __future__ import annotations

import importlib
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.ci import local_evidence
from tests.ci.support_crap import load_band_coverage, load_diff, load_source

if TYPE_CHECKING:
    from collections.abc import Sequence


def _local_trees(root: Path) -> list[str]:
    return sorted(item.name for item in root.iterdir() if item.name.startswith("mergecraft-local-"))


def _passthrough_wrap(argv: Sequence[str], *, repo_root: Path) -> list[str]:
    """Execute without the sandbox; this file is about temporary trees only."""
    _ = repo_root
    return list(argv)


@pytest.fixture(autouse=True)
def _tmp_trees_under_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every ``mkdtemp`` at the test's own directory."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(local_evidence, "checkout_is_fork_pr", lambda _root: False)


@pytest.mark.xfail(reason="green after W3", strict=True)
def test_source_copy_scratch_is_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox = importlib.import_module("mergecraft.analyzers.sandbox")
    seen: dict[str, Path] = {}

    def fake_context(*, repo_root: Path, scratch_dir: Path, **_kwargs: Any) -> SimpleNamespace:
        assert scratch_dir.is_dir(), "the sandbox scratch tree must exist while the run uses it"
        seen["scratch"] = scratch_dir
        return SimpleNamespace(scratch_dir=scratch_dir, repo_root=repo_root)

    def fake_run(argv: Sequence[str], **_kwargs: Any) -> Any:
        _ = argv
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")

    monkeypatch.setattr("mergecraft.mcp.shell.detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(sandbox, "build_sandbox_context", fake_context)
    monkeypatch.setattr(
        sandbox,
        "build_analyzer_sandbox_argv",
        lambda argv, *, context: ["unshare", *argv],
    )
    monkeypatch.setattr(local_evidence.subprocess, "run", fake_run)

    local_evidence.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
    )

    scratch = seen["scratch"]
    assert scratch.name.startswith("mergecraft-local-sbx-")
    assert scratch.parent == tmp_path
    assert not scratch.exists()
    assert _local_trees(tmp_path) == []


@pytest.mark.xfail(reason="green after W3", strict=True)
def test_coverage_workdir_is_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: Sequence[str], **_kwargs: Any) -> Any:
        if "-o" in argv:
            Path(argv[list(argv).index("-o") + 1]).write_text(
                load_band_coverage("watch"), encoding="utf-8"
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(local_evidence, "_sandboxed_argv", _passthrough_wrap)
    monkeypatch.setattr(local_evidence.subprocess, "run", fake_run)

    result = local_evidence.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        source_tree={"src/mod.py": load_source("watch")},
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
    )

    assert result.executed is True
    assert _local_trees(tmp_path) == []


@pytest.mark.xfail(reason="green after W3", strict=True)
def test_mutation_results_dir_is_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mutant_key = "src.mod.x_fn_watch__mutmut_1"
    meta = tmp_path / "mutants" / "src" / "mod.py.meta"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"exit_code_by_key": {mutant_key: 0}}), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text(load_source("watch"), encoding="utf-8")

    monkeypatch.setattr(local_evidence, "_sandboxed_argv", _passthrough_wrap)
    monkeypatch.setattr(
        local_evidence.shutil,
        "which",
        lambda name: "/usr/bin/mutmut" if name == "mutmut" else None,
    )
    monkeypatch.setattr(
        local_evidence,
        "_discover_mutmut_keys",
        lambda *_args, **_kwargs: [mutant_key],
    )
    monkeypatch.setattr(
        local_evidence.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 0, stdout="", stderr=""),
    )

    result = local_evidence.run_local_mutation(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        source_tree={"src/mod.py": load_source("watch")},
        trust_tier="trusted",
        sandbox_backend="unshare",
        toolchain_available=True,
    )

    assert result.executed is True
    assert _local_trees(tmp_path) == []


@pytest.mark.xfail(reason="green after W3", strict=True)
def test_scratch_is_removed_when_the_run_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sandbox = importlib.import_module("mergecraft.analyzers.sandbox")
    seen: dict[str, Path] = {}

    def fake_context(*, repo_root: Path, scratch_dir: Path, **_kwargs: Any) -> SimpleNamespace:
        assert scratch_dir.is_dir()
        seen["scratch"] = scratch_dir
        return SimpleNamespace(scratch_dir=scratch_dir, repo_root=repo_root)

    def interrupt(argv: Sequence[str], **_kwargs: Any) -> Any:
        _ = argv
        raise KeyboardInterrupt

    monkeypatch.setattr("mergecraft.mcp.shell.detect_sandbox_method", lambda: "unshare")
    monkeypatch.setattr(sandbox, "build_sandbox_context", fake_context)
    monkeypatch.setattr(
        sandbox,
        "build_analyzer_sandbox_argv",
        lambda argv, *, context: ["unshare", *argv],
    )
    monkeypatch.setattr(local_evidence.subprocess, "run", interrupt)

    with pytest.raises(KeyboardInterrupt):
        local_evidence.run_local_coverage(
            repo_root=tmp_path,
            diff=load_diff("watch"),
            trust_tier="trusted",
            sandbox_backend="unshare",
            toolchain_available=True,
        )

    assert seen["scratch"].name.startswith("mergecraft-local-sbx-")
    assert not seen["scratch"].exists()
    assert _local_trees(tmp_path) == []


def test_results_are_still_returned(tmp_path: Path) -> None:
    """A caller-supplied artifact is read and left in place."""
    coverage = tmp_path / "coverage.json"
    coverage.write_text(load_band_coverage("watch"), encoding="utf-8")
    mutation = tmp_path / "mutmut-survivor.json"
    mutation.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mutants": [
                    {
                        "id": "1",
                        "filename": "src/mod.py",
                        "line": 3,
                        "status": "survived",
                        "function": "fn_watch",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    coverage_result = local_evidence.run_local_coverage(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        source_tree={"src/mod.py": load_source("watch")},
        trust_tier="trusted",
        sandbox_backend="unshare",
        produced_artifact=coverage,
        toolchain_available=True,
    )
    mutation_result = local_evidence.run_local_mutation(
        repo_root=tmp_path,
        diff=load_diff("watch"),
        source_tree={"src/mod.py": load_source("watch")},
        trust_tier="trusted",
        sandbox_backend="unshare",
        produced_artifact=mutation,
        toolchain_available=True,
    )

    assert coverage_result.executed is True
    assert mutation_result.executed is True
    assert coverage.is_file()
    assert mutation.is_file()
    assert _local_trees(tmp_path) == []
