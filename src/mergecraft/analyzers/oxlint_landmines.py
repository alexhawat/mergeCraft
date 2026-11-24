"""Optional ``@interfere/landmines`` integration for oxlint (trusted tier only)."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.analyzers.detect import _OXLINT_CONFIG_NAMES

if TYPE_CHECKING:
    from mergecraft.analyzers.resolve import AnalyzerPlan
    from mergecraft.config.settings import AnalyzersSettings

_MIN_OXLINT_VERSION = (1, 81, 0)
_MIN_NODE_VERSION = (22, 18, 0)
_LANDMINES_INJECT_CONFIG_NOTE = (
    "@interfere/landmines configs/recommended — mergeCraft-injected oxlint config"
)
_VERSION_COMPONENT_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def landmines_opt_in(analyzers_settings: AnalyzersSettings | None) -> bool:
    """Return whether ``analyzers.overrides.oxlint.landmines`` is explicitly true."""
    if analyzers_settings is None:
        return False
    override = analyzers_settings.overrides.get("oxlint")
    return override is not None and override.landmines is True


def _parse_semver_prefix(version: str | None) -> tuple[int, int, int] | None:
    if not version:
        return None
    match = _VERSION_COMPONENT_RE.search(version)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _version_at_least(version: str | None, minimum: tuple[int, int, int]) -> bool:
    parsed = _parse_semver_prefix(version)
    return parsed is not None and parsed >= minimum


def node_meets_landmines_requirement() -> bool:
    """Landmines' oxlint jsPlugins path requires Node 22.18+."""
    node = shutil.which("node")
    if node is None:
        return False
    from mergecraft.analyzers.detect import _tool_version

    return _version_at_least(_tool_version(node, "node"), _MIN_NODE_VERSION)


def mergecraft_tooling_root() -> Path:
    """Repository root that carries ``scripts/package.json`` (source checkout or image)."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "scripts" / "package.json").is_file():
            return candidate
    return here.parents[3]


def landmines_toolchain() -> tuple[Path, Path] | None:
    """Return ``(oxlint_binary, recommended_config)`` when the pinned toolchain is present."""
    node_modules = mergecraft_tooling_root() / "scripts" / "node_modules"
    oxlint_bin = node_modules / ".bin" / "oxlint"
    recommended = node_modules / "@interfere" / "landmines" / "configs" / "recommended.json"
    if oxlint_bin.is_file() and recommended.is_file():
        return oxlint_bin.resolve(), recommended.resolve()
    return None


def _repo_oxlint_config_path(repo_root: Path) -> Path | None:
    repo_root = repo_root.resolve()
    for name in _OXLINT_CONFIG_NAMES:
        path = repo_root / name
        if path.is_file():
            return path.resolve()
    return None


def write_landmines_inject_config(
    *,
    scratch_dir: Path,
    repo_root: Path,
    landmines_recommended: Path,
) -> Path:
    """Write a scratch oxlint config that layers landmines ``recommended`` onto the repo.

    The repo's own config comes from the PR head, so its other rules apply but its landmines
    settings must not win. Later ``extends`` entries beat its top-level ``rules``; only a
    top-level override beats its ``overrides``, so the recommended rules are repeated there.
    """
    scratch_dir.mkdir(parents=True, exist_ok=True)
    extends: list[str] = []
    repo_config = _repo_oxlint_config_path(repo_root)
    if repo_config is not None:
        extends.append(str(repo_config))
    extends.append(str(landmines_recommended.resolve()))
    rules = json.loads(landmines_recommended.read_text(encoding="utf-8"))["rules"]
    payload = {"extends": extends, "overrides": [{"files": ["**/*"], "rules": rules}]}
    out = scratch_dir / "oxlint-landmines-inject.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def apply_oxlint_landmines(
    plan: AnalyzerPlan,
    *,
    repo_root: Path,
    scratch_dir: Path,
    analyzers_settings: AnalyzersSettings | None,
) -> AnalyzerPlan:
    """Patch an oxlint plan to run landmines whenever the base config opted in."""
    if plan.manifest_id != "oxlint" or plan.mode == "skip" or not plan.argv:
        return plan
    if not landmines_opt_in(analyzers_settings):
        return plan

    if not node_meets_landmines_requirement():
        return replace(
            plan,
            mode="skip",
            argv=(),
            reason="skipped oxlint: landmines requires Node >= 22.18",
        )

    toolchain = landmines_toolchain()
    if toolchain is None:
        return replace(
            plan,
            mode="skip",
            argv=(),
            reason=(
                "skipped oxlint: landmines toolchain missing "
                "(oxlint 1.81+ and @interfere/landmines in scripts/node_modules)"
            ),
        )

    oxlint_bin, landmines_recommended = toolchain
    from mergecraft.analyzers.detect import _tool_version
    from mergecraft.analyzers.resolve import FILES_TOKEN

    toolchain_version = _tool_version(str(oxlint_bin), "oxlint")
    if not _version_at_least(toolchain_version, _MIN_OXLINT_VERSION):
        return replace(
            plan,
            mode="skip",
            argv=(),
            reason="skipped oxlint: landmines requires oxlint >= 1.81",
        )

    inject_config = write_landmines_inject_config(
        scratch_dir=scratch_dir,
        repo_root=repo_root,
        landmines_recommended=landmines_recommended,
    )

    argv = list(plan.argv)
    if argv:
        argv[0] = str(oxlint_bin)
    config_flag = "-c"
    if config_flag not in argv and "--config" not in argv:
        if FILES_TOKEN in argv:
            index = argv.index(FILES_TOKEN)
            argv[index:index] = [config_flag, str(inject_config)]
        else:
            argv.extend([config_flag, str(inject_config)])

    config_note = plan.config_note
    if config_note:
        if _LANDMINES_INJECT_CONFIG_NOTE not in config_note:
            config_note = f"{config_note}; {_LANDMINES_INJECT_CONFIG_NOTE}"
    else:
        config_note = _LANDMINES_INJECT_CONFIG_NOTE

    version_note = plan.version_note
    if version_note and toolchain_version:
        version_note = f"{version_note}; landmines toolchain oxlint ({toolchain_version})"
    elif toolchain_version:
        version_note = f"ran landmines toolchain oxlint ({toolchain_version})"

    return replace(plan, argv=tuple(argv), config_note=config_note, version_note=version_note)


__all__ = [
    "apply_oxlint_landmines",
    "landmines_opt_in",
    "landmines_toolchain",
    "mergecraft_tooling_root",
    "node_meets_landmines_requirement",
    "write_landmines_inject_config",
]
