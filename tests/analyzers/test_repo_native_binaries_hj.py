"""Batch HJ RED — repo-native analyzer binaries #427.

Pins D8: after ``make setup``, ``find_repo_binary`` resolves ``vulture``,
``typos``, ``markdownlint``, and ``jscpd`` pinned to catalog versions.
``knip`` and ``tsc`` remain intentionally skipped (vendor JS / no first-party
``tsconfig``). Implementation lands in W20.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from mergecraft.analyzers.detect import find_repo_binary, resolve_repo_tool
from mergecraft.analyzers.manifest import AnalyzerManifest
from mergecraft.analyzers.registry import load_catalog

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ANALYZERS_DOC = _REPO_ROOT / "docs" / "dev" / "local-analyzers.md"
_INSTALLED_TOOL_IDS = ("vulture", "typos", "markdownlint", "jscpd")
_DOCUMENTED_SKIP_IDS = ("knip", "tsc")
_ALL_HJ_TOOL_IDS = _INSTALLED_TOOL_IDS + _DOCUMENTED_SKIP_IDS


def _manifest(tool_id: str) -> AnalyzerManifest:
    by_id = {manifest.id: manifest for manifest in load_catalog()}
    assert tool_id in by_id, f"{tool_id} missing from analyzer catalog"
    return by_id[tool_id]


def _command_binary(manifest: AnalyzerManifest) -> str:
    assert manifest.command, f"{manifest.id} must declare a command"
    return manifest.command[0]


def _catalog_version_matches(reported: str | None, catalog_version: str) -> bool:
    if reported is None:
        return False
    normalized = catalog_version.strip().strip('"').strip("'")
    return normalized in reported or reported.startswith(normalized)


def _repo_tooling_prefixes(repo_root: Path) -> tuple[Path, ...]:
    repo_root = repo_root.resolve()
    prefixes: list[Path] = [
        repo_root / ".venv" / "bin",
        repo_root / "venv" / "bin",
        repo_root / "node_modules" / ".bin",
    ]
    for package_json in repo_root.glob("packages/*/package.json"):
        prefixes.append(package_json.parent / "node_modules" / ".bin")
    for package_json in repo_root.glob("*/package.json"):
        if package_json.parent == repo_root:
            continue
        prefixes.append(package_json.parent / "node_modules" / ".bin")
    return tuple(prefixes)


def _is_under_repo_tooling(repo_root: Path, tool_path: str) -> bool:
    resolved = Path(tool_path).resolve()
    for prefix in _repo_tooling_prefixes(repo_root):
        with_prefix = prefix.resolve()
        try:
            resolved.relative_to(with_prefix)
        except ValueError:
            continue
        return True
    return False


# --- #427 install contract (RED until W20) -----------------------------------


@pytest.mark.xfail(
    reason="green after W20: install repo-native binaries via make setup (#427)",
    strict=False,
)
@pytest.mark.parametrize("tool_id", _INSTALLED_TOOL_IDS)
def test_find_repo_binary_resolves_after_make_setup(tool_id: str) -> None:
    """``make setup`` must leave each catalog tool resolvable from the checkout."""
    manifest = _manifest(tool_id)
    binary = _command_binary(manifest)
    resolution = find_repo_binary(_REPO_ROOT, binary)
    assert resolution is not None, f"{binary} not found under repo tooling"
    path = Path(resolution.path)
    assert path.is_file()
    assert os.access(path, os.X_OK)
    assert _is_under_repo_tooling(_REPO_ROOT, resolution.path), (
        f"{binary} must resolve from .venv/bin or */node_modules/.bin, not arbitrary PATH"
    )
    assert _catalog_version_matches(resolution.version, manifest.version), (
        f"{binary} version {resolution.version!r} must match catalog {manifest.version!r}"
    )


@pytest.mark.xfail(
    reason="green after W20: install repo-native binaries via make setup (#427)",
    strict=False,
)
@pytest.mark.parametrize("tool_id", _INSTALLED_TOOL_IDS)
def test_resolve_repo_tool_succeeds_after_make_setup(tool_id: str) -> None:
    """Offline review must not skip the four installed repo-native analyzers."""
    manifest = _manifest(tool_id)
    binary = _command_binary(manifest)
    resolution, skip = resolve_repo_tool(
        tool_id,
        repo_root=_REPO_ROOT,
        command_binary=binary,
    )
    assert skip is None, skip
    assert resolution is not None
    assert Path(resolution.path).is_file()


@pytest.mark.xfail(
    reason="green after W20: document knip/tsc intentional skip (#427)",
    strict=False,
)
def test_knip_and_tsc_skip_documented() -> None:
    """D8 written skip: vendor JS under ``docker/agent-clis``, no first-party ``tsconfig``."""
    assert _LOCAL_ANALYZERS_DOC.is_file(), (
        "docs/dev/local-analyzers.md must document which repo-native tools are installed vs skipped"
    )
    text = _LOCAL_ANALYZERS_DOC.read_text(encoding="utf-8").casefold()
    for term in ("knip", "tsc", "docker/agent-clis", "tsconfig"):
        assert term.casefold() in text, f"missing {term!r} in {_LOCAL_ANALYZERS_DOC}"
    assert "vendor" in text or "vendored" in text


# --- compatibility pins (pass on baseline; guard W20 scope) ------------------


@pytest.mark.parametrize("tool_id", _ALL_HJ_TOOL_IDS)
def test_manifests_stay_repo_native_without_darwin_provenance(tool_id: str) -> None:
    """D8: do not flip ``runtime: repo-native`` or add darwin provenance."""
    manifest = _manifest(tool_id)
    assert manifest.runtime == "repo-native"
    assert manifest.provenance == {}


@pytest.mark.parametrize("tool_id", _INSTALLED_TOOL_IDS)
def test_missing_binaries_skip_with_named_reason_today(tool_id: str) -> None:
    """Consumer repos without the tool must still skip with the standard reason."""
    manifest = _manifest(tool_id)
    binary = _command_binary(manifest)
    resolution, skip = resolve_repo_tool(
        tool_id,
        repo_root=_REPO_ROOT,
        command_binary=binary,
    )
    assert resolution is None
    assert skip is not None
    assert f"skipped {tool_id}:" in skip
    assert "not found in repo PATH or tooling" in skip


@pytest.mark.parametrize("tool_id", _DOCUMENTED_SKIP_IDS)
def test_knip_and_tsc_still_skip_when_binary_absent(tool_id: str) -> None:
    """Until W20 documents the skip, absent binaries use the repo-native miss reason."""
    manifest = _manifest(tool_id)
    binary = _command_binary(manifest)
    resolution, skip = resolve_repo_tool(
        tool_id,
        repo_root=_REPO_ROOT,
        command_binary=binary,
    )
    assert resolution is None
    assert skip is not None
    assert f"skipped {tool_id}:" in skip
    assert "not found in repo PATH or tooling" in skip


def test_catalog_versions_are_pinned_for_installed_tools() -> None:
    """W20 pins must match these catalog ``version:`` fields."""
    expected = {
        "vulture": "2.14",
        "typos": "1.32.0",
        "markdownlint": "0.37.4",
        "jscpd": "4.1.0",
    }
    for tool_id, version in expected.items():
        assert _manifest(tool_id).version == version


def test_knip_and_tsc_catalog_versions_document_skip_targets() -> None:
    """Skip documentation must name the catalog ids W20 leaves uninstalled."""
    assert _manifest("knip").version == "5.42.0"
    assert _manifest("tsc").version == "5.8.3"
    assert re.search(r"\d+\.\d+", _manifest("knip").version)
    assert re.search(r"\d+\.\d+", _manifest("tsc").version)
