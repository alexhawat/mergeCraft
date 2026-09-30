"""Layered config loading — committed, local, and ``MERGECRAFT_CONFIG`` (D2 / W4)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from loguru import logger

from mergecraft.config.compat import migrate_config
from mergecraft.config.io import config_path_for_root

if TYPE_CHECKING:
    from collections.abc import Mapping

_LOCAL_CONFIG_REL = Path(".mergecraft") / "config.local.yaml"


def running_in_github_actions() -> bool:
    """Return True when executing inside a GitHub Actions job (D2 / W4)."""
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def local_config_path(root: Path) -> Path:
    """Return ``.mergecraft/config.local.yaml`` under *root*."""
    return (root / _LOCAL_CONFIG_REL).resolve()


def merge_config_dicts(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Deep-merge *overlay* onto *base* (overlay wins on scalar/list conflicts)."""
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = merge_config_dicts(existing, value)
        else:
            merged[key] = value
    return merged


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("failed to parse config overlay {}: {}", path, exc)
        return {}
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"config must be a mapping: {path}"
        raise ValueError(msg)
    return loaded


def load_layered_config_dict(
    *,
    root: Path,
    explicit_path: Path | str | None = None,
    include_local: bool | None = None,
) -> dict[str, Any]:
    """Load config with precedence: committed < local < ``MERGECRAFT_CONFIG`` (D2 / W4)."""
    if explicit_path is not None:
        candidate = Path(explicit_path)
        if not candidate.is_file():
            return {}
        return migrate_config(_read_yaml_mapping(candidate))

    env_path = os.environ.get("MERGECRAFT_CONFIG")
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return migrate_config(_read_yaml_mapping(candidate))

    committed = migrate_config(_read_yaml_mapping(config_path_for_root(root)))
    use_local = include_local if include_local is not None else not running_in_github_actions()
    if not use_local:
        return committed

    local_raw = _read_yaml_mapping(local_config_path(root))
    if not local_raw:
        return committed
    return migrate_config(merge_config_dicts(committed, local_raw))


@dataclass(frozen=True, slots=True)
class ConfigSources:
    """Contributing config files for one read view, lowest precedence first.

    ``files`` are the files that actually exist and contribute, in the order
    they are merged. ``env_config_missing`` records that ``MERGECRAFT_CONFIG``
    named a file that is not there — the caller reports that instead of
    silently diagnosing the committed defaults.
    """

    files: tuple[Path, ...]
    env_config_missing: bool = False


def resolve_config_sources(root: Path) -> ConfigSources:
    """Return the config files a read view contributes, lowest precedence first.

    One resolver for every read view (``doctor``, ``config show/explain`` and
    the layered loader), so none diagnoses a config the review would not run
    with. Precedence matches :func:`load_layered_config_dict`:

    1. an existing ``MERGECRAFT_CONFIG`` file — the sole contributor (a missing
       one sets :attr:`ConfigSources.env_config_missing` and falls through);
    2. the committed ``.mergecraft/config.yaml`` under *root*;
    3. ``.mergecraft/config.local.yaml`` under *root*, off CI only, merged last.

    An explicit path (a ``--config`` flag) is the caller's concern; it wins
    before this resolver is consulted.
    """
    env_path = os.environ.get("MERGECRAFT_CONFIG")
    env_config_missing = False
    if env_path:
        candidate = Path(env_path)
        if candidate.is_file():
            return ConfigSources(files=(candidate.resolve(),))
        env_config_missing = True

    files: list[Path] = []
    committed = config_path_for_root(root)
    if committed.is_file():
        files.append(committed)
    if not running_in_github_actions():
        local = local_config_path(root)
        if local.is_file():
            files.append(local)
    return ConfigSources(files=tuple(files), env_config_missing=env_config_missing)


def resolved_config_path(root: Path) -> Path | None:
    """Return the highest-precedence contributing config file, or ``None``."""
    sources = resolve_config_sources(root)
    return sources.files[-1] if sources.files else None


__all__ = [
    "ConfigSources",
    "load_layered_config_dict",
    "local_config_path",
    "merge_config_dicts",
    "resolve_config_sources",
    "resolved_config_path",
    "running_in_github_actions",
]
