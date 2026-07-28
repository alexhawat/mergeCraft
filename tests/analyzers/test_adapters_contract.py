"""C4 differential contract adapters — RED until catalog C4 lands."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import C4_CONTRACT_TOOLS, import_module

pytestmark = pytest.mark.xfail(reason="green after C4: oasdiff, squawk, buf adapters", strict=False)


def _catalog_ids() -> set[str]:
    registry = import_module("mergecraft.analyzers.registry")
    return {manifest.id for manifest in registry.load_catalog()}


def _run_differential(tool_id: str, repo_root: Path, *, base_ref: str | None):
    contracts = import_module("mergecraft.analyzers.contracts")
    return contracts.run_differential_adapter(
        tool_id=tool_id,
        repo_root=repo_root,
        changed_files=list(C4_CONTRACT_TOOLS.values()),
        base_ref=base_ref,
        tier="trusted",
    )


@pytest.mark.parametrize("tool_id", ["oasdiff", "buf"])
def test_breaking_api_change_reported_once(tool_id: str, adapter_fixture_repo: Path) -> None:
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    result = _run_differential(tool_id, adapter_fixture_repo, base_ref="fixture-base")
    assert not result.skipped, result.skip_reason
    breaking = [
        f
        for f in result.findings
        if "break" in f.message.casefold() or "removed" in f.message.casefold()
    ]
    assert len(breaking) == 1, f"{tool_id} must report exactly one breaking API change"


def test_unsafe_migration_reported_once(adapter_fixture_repo: Path) -> None:
    tool_id = "squawk"
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    result = _run_differential(
        tool_id,
        adapter_fixture_repo,
        base_ref="fixture-base",
    )
    assert not result.skipped, result.skip_reason
    migration_path = C4_CONTRACT_TOOLS[tool_id]
    unsafe = [f for f in result.findings if f.path == migration_path]
    assert len(unsafe) == 1, "Squawk must report the lock-heavy migration exactly once"


@pytest.mark.parametrize("tool_id", list(C4_CONTRACT_TOOLS))
def test_skips_with_reason_when_base_ref_missing(tool_id: str, adapter_fixture_repo: Path) -> None:
    if tool_id not in _catalog_ids():
        pytest.fail(f"{tool_id} manifest missing from catalog")

    result = _run_differential(tool_id, adapter_fixture_repo, base_ref=None)
    assert result.skipped is True
    assert result.skip_reason, f"{tool_id} must skip with a named reason when base ref missing (D6)"
    reason = result.skip_reason.casefold()
    assert "base" in reason or "ref" in reason, (
        f"{tool_id} skip reason must name the missing base ref, not guess: {result.skip_reason!r}"
    )
    assert result.findings == []
