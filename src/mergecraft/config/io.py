"""Config file path helpers and YAML I/O without CLI dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import yaml

from mergecraft.config.compat import migrate_config
from mergecraft.config.settings import _DEFAULT_CONFIG_REL

if TYPE_CHECKING:
    from pathlib import Path


def config_path_for_root(root: Path) -> Path:
    """Return ``.mergecraft/config.yaml`` under *root*."""
    return (root / _DEFAULT_CONFIG_REL).resolve()


def committed_config_path(root: Path) -> Path:
    """Return ``.mergecraft/config.yaml`` under *root*."""
    return config_path_for_root(root)


def load_config_dict(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from *path*; return ``{}`` when the file is absent."""
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"config must be a mapping: {path}"
        raise ValueError(msg)
    return loaded


def load_migrated_config_dict(path: Path) -> dict[str, Any]:
    """Load and migrate a config mapping from *path*."""
    return migrate_config(load_config_dict(path))


__all__ = [
    "committed_config_path",
    "config_path_for_root",
    "load_config_dict",
    "load_migrated_config_dict",
]
