"""Shared coverage floor configuration for ratchet and floor gate scripts."""

from __future__ import annotations

import tomllib
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def fail_under_from_pyproject(repo_root_path: Path | None = None) -> float:
    """Return ``[tool.coverage.report] fail_under`` from ``pyproject.toml``."""
    root = repo_root_path or repo_root()
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        msg = f"pyproject.toml missing: {pyproject}"
        raise FileNotFoundError(msg)
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    floor = data.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    if floor is None:
        msg = "pyproject.toml missing [tool.coverage.report] fail_under"
        raise KeyError(msg)
    return float(floor)
