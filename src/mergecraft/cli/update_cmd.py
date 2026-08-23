"""``mergecraft update`` — reinstall the CLI via ``uv tool install --reinstall`` (#473)."""

from __future__ import annotations

import subprocess

import typer

from mergecraft.cli.errors import cli_bail

DEFAULT_UPDATE_REF = "main"
MERGECRAFT_GIT_ORIGIN = "https://github.com/alexhawat/mergeCraft"
MERGECRAFT_UV_INSTALL_PACKAGE = "merge-craft"


def uv_install_spec(ref: str) -> str:
    """Return the ``uv tool install`` git spec for ``ref`` (branch, tag, or SHA)."""
    return f"{MERGECRAFT_UV_INSTALL_PACKAGE} @ git+{MERGECRAFT_GIT_ORIGIN}@{ref}"


def build_uv_install_argv(ref: str) -> list[str]:
    """Build argv for ``uv tool install --reinstall`` at ``ref``."""
    return ["uv", "tool", "install", "--reinstall", uv_install_spec(ref)]


def run(
    branch: str | None = typer.Option(
        None,
        "--branch",
        help="Git ref to install (branch, tag, or commit SHA). Defaults to main.",
    ),
) -> None:
    """Reinstall mergecraft from GitHub using ``uv tool install --reinstall``."""
    ref = branch or DEFAULT_UPDATE_REF
    argv = build_uv_install_argv(ref)
    try:
        subprocess.run(argv, check=True)
    except OSError as exc:
        cli_bail(f"failed to run uv: {exc}")
    except subprocess.CalledProcessError as exc:
        cli_bail(f"uv tool install failed (exit {exc.returncode})")


__all__ = [
    "DEFAULT_UPDATE_REF",
    "MERGECRAFT_GIT_ORIGIN",
    "MERGECRAFT_UV_INSTALL_PACKAGE",
    "build_uv_install_argv",
    "run",
    "uv_install_spec",
]
