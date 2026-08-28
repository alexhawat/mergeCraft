"""Batch HJ RED — repo-native analyzer binaries #427.

Pins D8: after ``make setup``, ``find_repo_binary`` resolves ``vulture``,
``typos``, ``markdownlint``, and ``jscpd`` pinned to catalog versions.
``knip`` and ``tsc`` remain intentionally skipped (vendor JS / no first-party
``tsconfig``). Implementation lands in W20.
"""

from __future__ import annotations

import json
import os
import re
import shutil
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


def _engine_version_for_binary(repo_root: Path, binary: str) -> str | None:
    """Return the nested npm engine version when the catalog pin tracks the library."""
    if binary != "markdownlint":
        return None
    for prefix in _repo_tooling_prefixes(repo_root):
        package_json = prefix.parent / "markdownlint" / "package.json"
        if not package_json.is_file():
            continue
        payload = json.loads(package_json.read_text(encoding="utf-8"))
        version = payload.get("version")
        return version if isinstance(version, str) else None
    return None


def _resolved_version(repo_root: Path, binary: str, manifest: AnalyzerManifest) -> str | None:
    resolution = find_repo_binary(repo_root, binary)
    if resolution is None:
        return None
    engine = _engine_version_for_binary(repo_root, binary)
    if engine is not None:
        return engine
    return resolution.version


def _repo_tooling_prefixes(repo_root: Path) -> tuple[Path, ...]:
    repo_root = repo_root.resolve()
    prefixes: list[Path] = [
        repo_root / ".venv-dev" / "bin",
        repo_root / ".venv" / "bin",
        repo_root / "venv" / "bin",
        repo_root / "node_modules" / ".bin",
        repo_root / "node_modules",
    ]
    for package_json in repo_root.glob("packages/*/package.json"):
        prefixes.append(package_json.parent / "node_modules" / ".bin")
        prefixes.append(package_json.parent / "node_modules")
    for package_json in repo_root.glob("*/package.json"):
        if package_json.parent == repo_root:
            continue
        prefixes.append(package_json.parent / "node_modules" / ".bin")
        prefixes.append(package_json.parent / "node_modules")
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


# --- #427 install contract ---------------------------------------------------


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
        f"{binary} must resolve from .venv-dev/bin, .venv/bin, or */node_modules/.bin, not arbitrary PATH"
    )
    reported = _resolved_version(_REPO_ROOT, binary, manifest)
    assert _catalog_version_matches(reported, manifest.version), (
        f"{binary} version {reported!r} must match catalog {manifest.version!r}"
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
def test_missing_binaries_skip_with_named_reason_today(
    tool_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Consumer repos without the tool must still skip with the standard reason."""
    monkeypatch.setenv("PATH", "")
    manifest = _manifest(tool_id)
    binary = _command_binary(manifest)
    resolution, skip = resolve_repo_tool(
        tool_id,
        repo_root=tmp_path,
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


@pytest.mark.parametrize("binary", ["markdownlint", "jscpd", "tsc", "knip", "vulture", "typos"])
def test_an_ambient_path_binary_is_refused_for_repo_local_tools(
    binary: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#427 — a PATH hit is not a substitute for the repo's pinned tool.

    These six are installed *into the checkout* (``node_modules/.bin`` /
    ``.venv/bin``). Before this, ``find_repo_binary`` fell back to
    ``shutil.which``, so a system copy — Homebrew's ``markdownlint``, the GitHub
    runner's ``/usr/local/bin/tsc`` — resolved and ran against the consumer's
    code at an unpinned version of unverified provenance. The repo providing
    nothing must mean skip, not "use whatever is on PATH".
    """
    fake_bin = tmp_path / "sysbin"
    fake_bin.mkdir()
    planted = fake_bin / binary
    planted.write_text("#!/bin/sh\necho 1.0.0\n", encoding="utf-8")
    planted.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    # A repo root that provides no tooling of its own.
    empty_repo = tmp_path / "repo"
    empty_repo.mkdir()

    assert shutil.which(binary) == str(planted), "planted binary must be on PATH"
    assert find_repo_binary(empty_repo, binary) is None


def test_a_toolchain_binary_still_resolves_from_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule is scoped: ``cargo`` (clippy) and ``go`` (govulncheck) have no
    repo-local install convention, so they must keep resolving from PATH or
    those analyzers would skip everywhere instead of being hardened.
    """
    fake_bin = tmp_path / "sysbin"
    fake_bin.mkdir()
    planted = fake_bin / "cargo"
    planted.write_text("#!/bin/sh\necho cargo 1.99.0\n", encoding="utf-8")
    planted.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))

    empty_repo = tmp_path / "repo"
    empty_repo.mkdir()

    resolution = find_repo_binary(empty_repo, "cargo")
    assert resolution is not None
    assert resolution.path == str(planted)


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
