"""Catalog registry — load manifests and detect enabled analyzers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from loguru import logger

from mergecraft.analyzers.manifest import (
    AnalyzerManifest,
    expand_detect_patterns,
    load_manifest_file,
)

_CATALOG_DIR = Path(__file__).resolve().parent / "catalog"


@lru_cache(maxsize=1)
def load_catalog() -> tuple[AnalyzerManifest, ...]:
    """Load and validate every manifest in the bundled catalog."""
    if not _CATALOG_DIR.is_dir():
        return ()
    manifests: list[AnalyzerManifest] = []
    for path in sorted(_CATALOG_DIR.glob("*.yaml")):
        manifest = load_manifest_file(path, strict_severity_map=False)
        manifests.append(manifest)
    return tuple(manifests)


def _glob_match(path: str, pattern: str) -> bool:
    return PurePosixPath(path).match(pattern, case_sensitive=True)


def _matches_detect_patterns(changed_file: str, patterns: list[str]) -> bool:
    return any(_glob_match(changed_file, pattern) for pattern in expand_detect_patterns(patterns))


def _detect_matches(manifest: AnalyzerManifest, changed_files: list[str]) -> bool:
    if not changed_files:
        return False
    patterns = manifest.detect.files
    return any(_matches_detect_patterns(changed, patterns) for changed in changed_files)


def _settings_enabled(
    manifest: AnalyzerManifest,
    settings: dict[str, Any],
) -> bool | None:
    analyzers = settings.get("analyzers") or {}
    overrides = analyzers.get("overrides") or {}
    override = overrides.get(manifest.id) or {}
    if isinstance(override, dict) and "enabled" in override:
        return bool(override["enabled"])
    if analyzers.get("enabled") is False:
        return False
    if manifest.default_enabled is True:
        return True
    if manifest.default_enabled is False:
        return False
    return None


def detect_enabled(
    *,
    repo_root: Path,
    changed_files: list[str],
    settings_overrides: dict[str, Any] | None = None,
) -> list[AnalyzerManifest]:
    """Return analyzers enabled for this diff, honoring detection and config overrides."""
    _ = repo_root  # reserved for repo-native detection in later waves
    settings = settings_overrides or {}
    candidates: list[AnalyzerManifest] = []

    for manifest in load_catalog():
        enabled = _settings_enabled(manifest, settings)
        if enabled is False:
            continue
        if enabled is None and not _detect_matches(manifest, changed_files):
            continue
        candidates.append(manifest)

    selected: list[AnalyzerManifest] = []
    groups: dict[str, AnalyzerManifest] = {}
    for manifest in candidates:
        group = manifest.exclusive_group
        if not group:
            selected.append(manifest)
            continue
        if group not in groups:
            groups[group] = manifest
            selected.append(manifest)
            continue
        overrides = (settings.get("analyzers") or {}).get("overrides") or {}
        explicit = [
            manifest_id
            for manifest_id, override in overrides.items()
            if isinstance(override, dict) and override.get("enabled") is True
        ]
        if manifest.id in explicit and groups[group].id in explicit:
            selected.append(manifest)
        elif manifest.id in explicit:
            selected = [m for m in selected if m.exclusive_group != group]
            groups[group] = manifest
            selected.append(manifest)

    return selected


def known_analyzer_ids() -> frozenset[str]:
    return frozenset(m.id for m in load_catalog())


def warn_unknown_analyzer_overrides(settings: dict[str, Any]) -> None:
    """Log a warning for override keys that do not match a catalog id."""
    analyzers = settings.get("analyzers") or {}
    overrides = analyzers.get("overrides") or {}
    known = known_analyzer_ids()
    for analyzer_id in overrides:
        if analyzer_id not in known:
            logger.warning("unknown analyzer id in config overrides: {}", analyzer_id)


__all__ = [
    "detect_enabled",
    "known_analyzer_ids",
    "load_catalog",
    "warn_unknown_analyzer_overrides",
]
