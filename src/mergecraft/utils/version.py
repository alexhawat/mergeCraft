"""Installed package version resolution for CLI and MCP metadata."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def package_version() -> str:
    """Return the installed mergeCraft version, cached for the process lifetime."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("merge-craft")
        if installed.strip():
            return installed
    except PackageNotFoundError:
        pass

    from mergecraft import __version__

    if __version__.strip() and __version__ != "0.0.0+unknown":
        return __version__

    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project_version = data.get("project", {}).get("version")
        if isinstance(project_version, str) and project_version.strip():
            return project_version

    return __version__


__all__ = ["package_version"]
