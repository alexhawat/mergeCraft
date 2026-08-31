"""Config file path helpers and YAML I/O without CLI dependencies."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from mergecraft.config.settings import _DEFAULT_CONFIG_REL


def config_path_for_root(root: Path) -> Path:
    """Return ``.mergecraft/config.yaml`` under *root*."""
    return (root / _DEFAULT_CONFIG_REL).resolve()


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


def config_has_yaml_comments(path: Path) -> bool:
    """Return True when *path* contains YAML comment lines that ``safe_dump`` would erase."""
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return True
    return False


def write_config_dict(path: Path, data: dict[str, Any]) -> None:
    """Replace the config file atomically.

    Writing in place truncates first, so a failure partway through would leave
    the operator with a half-written ``config.yaml``. Serialise into a sibling
    temporary file and rename over the target instead: the rename is atomic, so
    the file is either the old content or the new one.

    When the target already contains ``#`` comment lines, refuse to write —
    ``yaml.safe_dump`` cannot preserve them (lane B W2 / option b).
    """
    if config_has_yaml_comments(path):
        msg = (
            f"refusing to rewrite {path}: the file contains YAML comments that "
            "would be destroyed by the config writer.\n"
            "Edit trust settings by hand in the committed config, for example:\n"
            "  trust:\n"
            '    selfReview: "off"\n'
            '    agentSandbox: "dispatch"'
        )
        raise ValueError(msg)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    mode = path.stat().st_mode & 0o777 if path.is_file() else None
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            tmp_path.chmod(mode)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


__all__ = [
    "config_has_yaml_comments",
    "config_path_for_root",
    "load_config_dict",
    "write_config_dict",
]
