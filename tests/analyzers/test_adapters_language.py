"""C1 repo-native language gates."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.analyzers.support import (
    C1_LANGUAGE_TOOLS,
    C1_TYPE_CHECKERS,
    finding_path_matches,
    import_module,
)


def _catalog_ids() -> set[str]:
    registry = import_module("mergecraft.analyzers.registry")
    return {manifest.id for manifest in registry.load_catalog()}


def _run(tool_id: str, repo_root: Path, changed_files: list[str]):
    adapters = import_module("mergecraft.analyzers.adapters")
    return adapters.run_adapter(
        tool_id=tool_id,
        repo_root=repo_root,
        changed_files=changed_files,
        tier="trusted",
    )


@pytest.mark.parametrize("tool_id", list(C1_LANGUAGE_TOOLS))
def test_language_tool_runs_or_skips_with_named_reason(
    tool_id: str, adapter_fixture_repo: Path
) -> None:
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    path, _line = C1_LANGUAGE_TOOLS[tool_id]
    result = _run(tool_id, adapter_fixture_repo, [path])

    if result.skipped:
        assert result.skip_reason, f"{tool_id} must skip with a named reason"
        assert len(result.skip_reason) > 10
    else:
        assert result.findings, f"{tool_id} must report the planted issue at {path}"


@pytest.mark.parametrize("tool_id", sorted(C1_TYPE_CHECKERS))
def test_type_checker_never_uses_managed_substitute(
    tool_id: str, adapter_fixture_repo: Path
) -> None:
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    resolve = import_module("mergecraft.analyzers.resolve")
    registry = import_module("mergecraft.analyzers.registry")
    manifest = next(m for m in registry.load_catalog() if m.id == tool_id)

    plan = resolve.resolve_analyzer(
        manifest=manifest,
        repo_root=adapter_fixture_repo,
        managed_available=True,
    )
    assert plan.mode != "managed", (
        f"{tool_id} must never use a managed substitute (C3/D5); got mode={plan.mode!r}"
    )
    if plan.reason:
        assert "managed" not in plan.reason.casefold()


@pytest.mark.parametrize("tool_id", list(C1_LANGUAGE_TOOLS))
def test_review_names_tool_version(tool_id: str, adapter_fixture_repo: Path) -> None:
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    path, _line = C1_LANGUAGE_TOOLS[tool_id]
    result = _run(tool_id, adapter_fixture_repo, [path])
    if result.skipped:
        pytest.skip(result.skip_reason or "adapter skipped in this environment")

    pipeline = import_module("mergecraft.analyzers.pipeline")
    review_meta = pipeline.analyzer_run_metadata(tool_id=tool_id, result=result)
    version_note = review_meta.get("version") or review_meta.get("version_note") or ""
    assert version_note, f"{tool_id} review must name the version that ran (D5/C1.5)"
    assert re.search(r"\d+\.\d+", version_note), (
        f"{tool_id} version note must include a semver fragment: {version_note!r}"
    )


@pytest.mark.parametrize(
    ("tool_id", "path", "line"),
    [(tid, loc[0], loc[1]) for tid, loc in C1_LANGUAGE_TOOLS.items()],
)
def test_language_tool_catches_planted_finding(
    tool_id: str, path: str, line: int, adapter_fixture_repo: Path
) -> None:
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    result = _run(tool_id, adapter_fixture_repo, [path])
    assert not result.skipped, result.skip_reason
    matches = [
        f for f in result.findings if finding_path_matches(path, f.path) and f.start_line == line
    ]
    assert matches, f"{tool_id} must catch planted finding at {path}:{line}"
