"""Shared fixtures for CF #473 ``update`` + commit in ``--version`` RED tests (D7)."""

from __future__ import annotations

from typing import Any

from tests.analyzers.support import import_module

_UPDATE_CMD_MOD = "mergecraft.cli.update_cmd"
_VERSION_MOD = "mergecraft"

# D7 default git ref when ``--branch`` is omitted.
DEFAULT_UPDATE_REF = "main"

# README / AGENTS install spec shape (``uv tool install --reinstall`` target).
MERGECRAFT_UV_INSTALL_PACKAGE = "merge-craft"
MERGECRAFT_GIT_ORIGIN = "https://github.com/alexhawat/mergeCraft"


def update_cmd_module() -> Any:
    """Return the ``mergecraft.cli.update_cmd`` module."""
    return import_module(_UPDATE_CMD_MOD)


def require_update_attr(name: str) -> Any:
    """Return a symbol from ``mergecraft.cli.update_cmd`` or fail the RED test."""
    mod = update_cmd_module()
    value = getattr(mod, name, None)
    assert value is not None, f"{_UPDATE_CMD_MOD}.{name} is not implemented"
    return value


def require_version_attr(name: str) -> Any:
    """Return a symbol from ``mergecraft`` or fail the RED test."""
    mod = import_module(_VERSION_MOD)
    value = getattr(mod, name, None)
    assert value is not None, f"{_VERSION_MOD}.{name} is not implemented"
    return value


def require_version_callable(name: str) -> Any:
    """Return a callable version helper or fail the RED test."""
    value = require_version_attr(name)
    assert callable(value), f"{_VERSION_MOD}.{name} must be callable"
    return value


def uv_install_spec(ref: str) -> str:
    """Build the ``uv tool install`` git spec for ``ref`` (branch, tag, or SHA)."""
    return f"{MERGECRAFT_UV_INSTALL_PACKAGE} @ git+{MERGECRAFT_GIT_ORIGIN}@{ref}"


__all__ = [
    "DEFAULT_UPDATE_REF",
    "MERGECRAFT_GIT_ORIGIN",
    "MERGECRAFT_UV_INSTALL_PACKAGE",
    "require_update_attr",
    "require_version_attr",
    "require_version_callable",
    "update_cmd_module",
    "uv_install_spec",
]
