"""Detect markers must not be expanded into command ``{files}`` lint targets."""

from __future__ import annotations

from pathlib import Path

from tests.analyzers.support import import_module

_CASES: tuple[tuple[str, str, str], ...] = (
    ("phpstan", "composer.json", "hello.php"),
    ("golangci-lint", "go.mod", "hello.go"),
    ("sqlfluff", "pyproject.toml", "hello.sql"),
    ("sqlfluff", ".sqlfluff", "hello.sql"),
)


def _registry():
    return import_module("mergecraft.analyzers.registry")


def test_detect_still_matches_enable_markers() -> None:
    registry = _registry()
    for tool_id, marker, _source in _CASES:
        manifest = registry.get_manifest(tool_id)
        assert registry.filter_changed_files_for_manifest(manifest, [marker]) == [marker], (
            f"{tool_id} detect.files must still match enable marker {marker!r}"
        )


def test_lint_targets_exclude_enable_markers() -> None:
    registry = _registry()
    for tool_id, marker, source in _CASES:
        manifest = registry.get_manifest(tool_id)
        assert registry.filter_lint_targets_for_manifest(manifest, [marker]) == []
        assert registry.filter_lint_targets_for_manifest(manifest, [marker, source]) == [source]


def test_finalize_plan_does_not_pass_markers_as_files(tmp_path: Path) -> None:
    registry = _registry()
    execution = import_module("mergecraft.analyzers.execution")
    resolve = import_module("mergecraft.analyzers.resolve")
    for tool_id, marker, source in _CASES:
        (tmp_path / source).write_text("x\n", encoding="utf-8")
        (tmp_path / Path(marker).name).write_text("{}\n", encoding="utf-8")
        manifest = registry.get_manifest(tool_id)
        plan = resolve.AnalyzerPlan(
            manifest_id=tool_id,
            mode="repo-native",
            argv=tuple(manifest.command),
            cwd=tmp_path,
        )
        final = execution.finalize_plan(
            plan,
            manifest=manifest,
            repo_root=tmp_path,
            changed_files=[marker, source],
            tier="trusted",
        )
        argv = [str(arg) for arg in final.argv]
        assert not any(arg.endswith(Path(marker).name) for arg in argv), (
            f"{tool_id} argv must not include enable marker {marker!r}: {argv!r}"
        )
        assert any(arg.endswith(source) for arg in argv), (
            f"{tool_id} argv must still include source {source!r}: {argv!r}"
        )
