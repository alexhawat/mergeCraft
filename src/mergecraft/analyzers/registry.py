"""Catalog registry — load manifests and detect enabled analyzers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from loguru import logger

from mergecraft.analyzers.detect import (
    detect_js_linter_intent,
    has_basedpyright_config,
    has_mypy_config,
    has_pyright_config,
    has_ruff_config,
    manifest_config_present,
)
from mergecraft.analyzers.manifest import (
    AnalyzerManifest,
    expand_detect_patterns,
    load_manifest_file,
)
from mergecraft.analyzers.pattern import (
    PATTERN_EXCLUSIVE_GROUP,
    has_astgrep_config,
    pattern_backend_from_settings,
    pattern_tool_enabled,
)

_CATALOG_DIR = Path(__file__).resolve().parent / "catalog"

_PYTHON_LINT_PREFERENCE = ("ruff", "pylint")
_PYTHON_TYPECHECK_PREFERENCE = ("mypy", "basedpyright", "pyright")
_JS_LINTERS = ("eslint", "biome", "oxlint")


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
    return PurePosixPath(path).match(pattern)


def _matches_detect_patterns(changed_file: str, patterns: list[str]) -> bool:
    return any(_glob_match(changed_file, pattern) for pattern in expand_detect_patterns(patterns))


def filter_changed_files_for_manifest(
    manifest: AnalyzerManifest,
    changed_files: list[str],
) -> list[str]:
    """Keep only changed paths that match the manifest's ``detect.files`` globs."""
    patterns = manifest.detect.files
    return [path for path in changed_files if _matches_detect_patterns(path, patterns)]


def _detect_matches(manifest: AnalyzerManifest, changed_files: list[str]) -> bool:
    if not changed_files:
        return False
    patterns = manifest.detect.files
    return any(_matches_detect_patterns(changed, patterns) for changed in changed_files)


def get_manifest(tool_id: str) -> AnalyzerManifest:
    """Return one catalog manifest by id."""
    for manifest in load_catalog():
        if manifest.id == tool_id:
            return manifest
    msg = f"unknown analyzer id: {tool_id!r}"
    raise KeyError(msg)


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
    if manifest.default_enabled is False:
        return False
    return None


def _auto_manifest_enabled(manifest: AnalyzerManifest, repo_root: Path) -> bool:
    if manifest.id == "ruff":
        return has_ruff_config(repo_root)
    if manifest.id == "mypy":
        return has_mypy_config(repo_root)
    if manifest.id == "pyright":
        return has_pyright_config(repo_root)
    if manifest.id == "basedpyright":
        return has_basedpyright_config(repo_root)
    if manifest.id in _JS_LINTERS:
        intent = detect_js_linter_intent(repo_root)
        return intent == manifest.id
    if manifest.id == "ast-grep":
        return has_astgrep_config(repo_root)
    return manifest_config_present(manifest.id, repo_root)


def _explicit_override_winner(
    candidates: list[AnalyzerManifest], explicit: list[str]
) -> AnalyzerManifest | None:
    """Tie-break rule: an operator's explicit ``enabled: true`` override wins outright.

    Ties among multiple explicit overrides in the same exclusive group fall
    through to the alphabetical rule (via ``sorted(...)[0]``), same as the
    final catch-all — an explicit override just narrows the candidate pool
    first.
    """
    explicit_in_group = [m for m in candidates if m.id in explicit]
    if len(explicit_in_group) == 1:
        return explicit_in_group[0]
    if len(explicit_in_group) > 1:
        return sorted(explicit_in_group, key=lambda m: m.id)[0]
    return None


def _preference_order_winner(
    candidates: list[AnalyzerManifest], preference: tuple[str, ...]
) -> AnalyzerManifest | None:
    """Tie-break rule: the first candidate matching an ordered id-preference list."""
    for preferred in preference:
        for manifest in candidates:
            if manifest.id == preferred:
                return manifest
    return None


def _group_preference_order(
    group: str,
    *,
    repo_root: Path,
    settings: dict[str, Any],
) -> tuple[str, ...]:
    """The id-preference order for one exclusive group, or ``()`` if it has none."""
    if group == "python-lint":
        return _PYTHON_LINT_PREFERENCE
    if group == "python-typecheck":
        return _PYTHON_TYPECHECK_PREFERENCE
    if group == "js-lint":
        intent = detect_js_linter_intent(repo_root)
        return (intent,) if intent is not None else ()
    if group == PATTERN_EXCLUSIVE_GROUP:
        backend = pattern_backend_from_settings(repo_root, settings)
        return (backend, "semgrep", "opengrep", "ast-grep")
    return ()


def _alphabetical_winner(candidates: list[AnalyzerManifest]) -> AnalyzerManifest:
    """Tie-break rule: last resort — alphabetically first id, for a deterministic pick."""
    return sorted(candidates, key=lambda m: m.id)[0]


def _exclusive_group_winner(
    group: str,
    candidates: list[AnalyzerManifest],
    *,
    repo_root: Path,
    settings: dict[str, Any],
) -> AnalyzerManifest:
    """Pick one manifest per exclusive group via an ordered chain of named tie-break rules."""
    overrides = (settings.get("analyzers") or {}).get("overrides") or {}
    explicit = [
        manifest_id
        for manifest_id, override in overrides.items()
        if isinstance(override, dict) and override.get("enabled") is True
    ]
    winner = _explicit_override_winner(candidates, explicit)
    if winner is not None:
        return winner

    preference = _group_preference_order(group, repo_root=repo_root, settings=settings)
    winner = _preference_order_winner(candidates, preference)
    if winner is not None:
        return winner

    return _alphabetical_winner(candidates)


def _manifest_is_candidate(
    manifest: AnalyzerManifest,
    *,
    repo_root: Path,
    changed_files: list[str],
    settings: dict[str, Any],
) -> bool:
    """Per-detector evaluation: does this manifest apply to the current diff/config?

    Four independent gates, all of which must pass: the pattern-backend
    exclusive group's own enablement, the settings override, the
    ``detect.files`` glob match against the diff, and (only when nothing
    else decided it) the ``default_enabled: auto`` repo-config heuristic.
    """
    if manifest.exclusive_group == PATTERN_EXCLUSIVE_GROUP and not pattern_tool_enabled(
        manifest.id, repo_root=repo_root, settings=settings
    ):
        return False
    enabled = _settings_enabled(manifest, settings)
    if enabled is False:
        return False
    if not _detect_matches(manifest, changed_files):
        return False
    return not (
        enabled is None
        and manifest.default_enabled == "auto"
        and not _auto_manifest_enabled(manifest, repo_root)
    )


def _group_candidates(
    candidates: list[AnalyzerManifest],
) -> tuple[list[AnalyzerManifest], dict[str, list[AnalyzerManifest]]]:
    """Split out ungrouped candidates (selected outright) from exclusive-group members."""
    grouped: dict[str, list[AnalyzerManifest]] = {}
    selected: list[AnalyzerManifest] = []
    for manifest in candidates:
        group = manifest.exclusive_group
        if not group:
            selected.append(manifest)
            continue
        grouped.setdefault(group, []).append(manifest)
    return selected, grouped


def _resolve_group_members(
    group: str,
    members: list[AnalyzerManifest],
    *,
    repo_root: Path,
    settings: dict[str, Any],
    explicit: set[str],
) -> list[AnalyzerManifest]:
    """Per-detector evaluation for one exclusive group.

    Multiple explicit operator overrides in the same group all survive
    (sorted for determinism); a single explicit override wins outright;
    otherwise fall back to ``_exclusive_group_winner``'s tie-break chain.
    """
    explicit_members = [m for m in members if m.id in explicit]
    if len(explicit_members) > 1:
        return sorted(explicit_members, key=lambda m: m.id)
    if len(explicit_members) == 1:
        return explicit_members
    return [_exclusive_group_winner(group, members, repo_root=repo_root, settings=settings)]


def detect_enabled(
    *,
    repo_root: Path,
    changed_files: list[str],
    settings_overrides: dict[str, Any] | None = None,
) -> list[AnalyzerManifest]:
    """Return analyzers enabled for this diff, honoring detection and config overrides."""
    repo_root = repo_root.resolve()
    settings = settings_overrides or {}
    candidates = [
        manifest
        for manifest in load_catalog()
        if _manifest_is_candidate(
            manifest, repo_root=repo_root, changed_files=changed_files, settings=settings
        )
    ]

    selected, grouped = _group_candidates(candidates)

    overrides = (settings.get("analyzers") or {}).get("overrides") or {}
    explicit = {
        manifest_id
        for manifest_id, override in overrides.items()
        if isinstance(override, dict) and override.get("enabled") is True
    }

    for group, members in grouped.items():
        selected.extend(
            _resolve_group_members(
                group, members, repo_root=repo_root, settings=settings, explicit=explicit
            )
        )

    return selected


def select_enabled_analyzers(
    *,
    repo_root: Path,
    changed_files: list[str],
    settings: dict[str, object] | None = None,
) -> list[AnalyzerManifest]:
    """Return enabled analyzers for registry tests and tooling."""
    return detect_enabled(
        repo_root=repo_root,
        changed_files=changed_files,
        settings_overrides=settings,
    )


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
    "filter_changed_files_for_manifest",
    "get_manifest",
    "known_analyzer_ids",
    "load_catalog",
    "select_enabled_analyzers",
    "warn_unknown_analyzer_overrides",
]
