"""``mergecraft update`` — reinstall the CLI at the latest release via ``uv tool install``.

By default the CLI is reinstalled from the package index at the newest
published release no older than the running one, so a pinned alpha moves to
the next release and never to unreleased ``main``. ``--ref`` installs a git
branch, tag or commit instead. Optional extras that are installed now (for
example ``tracing``) are carried over.

Exports: ``DEFAULT_UPDATE_REF``, ``MERGECRAFT_GIT_ORIGIN``,
``MERGECRAFT_UV_INSTALL_PACKAGE``, ``build_uv_install_argv``,
``installed_extras``, ``release_requirement``, ``run``, ``uv_install_spec``
"""

from __future__ import annotations

import re
import shlex
import subprocess
from importlib import metadata

import typer

import mergecraft
from mergecraft.cli.consoles import err_console
from mergecraft.cli.errors import cli_bail

DEFAULT_UPDATE_REF: str | None = None
"""Default git ref: ``None`` installs the latest published release, not a branch."""
MERGECRAFT_GIT_ORIGIN = "https://github.com/alexhawat/mergeCraft"
MERGECRAFT_UV_INSTALL_PACKAGE = "mergecraft-action"

# Development-only extras are never carried into a tool install.
_SKIPPED_EXTRAS = frozenset({"dev"})
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXTRA_MARKER = re.compile(r"""extra\s*==\s*["']([^"']+)["']""")


def _with_extras(extras: tuple[str, ...]) -> str:
    """Return the distribution name with an ``[extra,...]`` suffix when needed."""
    if not extras:
        return MERGECRAFT_UV_INSTALL_PACKAGE
    return f"{MERGECRAFT_UV_INSTALL_PACKAGE}[{','.join(extras)}]"


def uv_install_spec(ref: str, extras: tuple[str, ...] = ()) -> str:
    """Return the ``uv tool install`` git spec for ``ref`` (branch, tag, or SHA).

    Args:
        ref (str): Git ref to install.
        extras (tuple[str, ...]): Optional extras to keep.

    Returns:
        str: A PEP 508 direct reference.
    """
    return f"{_with_extras(extras)} @ git+{MERGECRAFT_GIT_ORIGIN}@{ref}"


def release_requirement(version: str, extras: tuple[str, ...] = ()) -> str:
    """Return the index requirement for the latest release no older than ``version``.

    A released ``version`` becomes the lower bound, so ``update`` never
    downgrades; because the bound is a pre-release while the project is in
    alpha, the resolver may pick newer pre-releases too. A development or
    local build (``.devN`` / ``+local``) has no published counterpart to
    anchor on and gets no bound: the index's latest release is installed.

    Args:
        version (str): Running package version.
        extras (tuple[str, ...]): Optional extras to keep.

    Returns:
        str: A PEP 508 requirement string.
    """
    name = _with_extras(extras)
    if ".dev" in version or "+" in version:
        return name
    return f"{name}>={version}"


def installed_extras() -> tuple[str, ...]:
    """Return the optional extras whose requirements are all installed now.

    Returns:
        tuple[str, ...]: Sorted extra names, without development-only extras.
    """
    try:
        requires = metadata.requires(MERGECRAFT_UV_INSTALL_PACKAGE) or []
    except metadata.PackageNotFoundError:
        return ()
    by_extra: dict[str, set[str]] = {}
    for requirement in requires:
        marker = _EXTRA_MARKER.search(requirement)
        name = _REQUIREMENT_NAME.match(requirement)
        if marker is None or name is None:
            continue
        by_extra.setdefault(marker.group(1), set()).add(name.group(1))
    present: list[str] = []
    for extra, names in sorted(by_extra.items()):
        if extra in _SKIPPED_EXTRAS:
            continue
        try:
            for dist in names:
                metadata.version(dist)
        except metadata.PackageNotFoundError:
            continue
        present.append(extra)
    return tuple(present)


def build_uv_install_argv(
    ref: str | None = None,
    *,
    extras: tuple[str, ...] = (),
    version: str | None = None,
) -> list[str]:
    """Build argv for ``uv tool install --reinstall``.

    Args:
        ref (str | None): Git ref; ``None`` installs the latest release.
        extras (tuple[str, ...]): Optional extras to keep.
        version (str | None): Running version (defaults to the installed one).

    Returns:
        list[str]: The ``uv`` argv.
    """
    if ref is not None:
        return ["uv", "tool", "install", "--reinstall", uv_install_spec(ref, extras)]
    current = mergecraft.__version__ if version is None else version
    # uv's default pre-release strategy accepts a pre-release when the bound
    # names one or when the package publishes nothing else.
    return [
        "uv",
        "tool",
        "install",
        "--reinstall",
        "--upgrade",
        release_requirement(current, extras),
    ]


def run(
    ref: str | None = typer.Option(
        None,
        "--ref",
        "--branch",
        help=(
            "Install this git branch, tag, or commit SHA instead of the latest release. "
            "Unreleased code: prefer a full commit SHA."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print the uv command without running it.",
    ),
) -> None:
    """Reinstall mergecraft at the latest release, keeping installed extras."""
    extras = installed_extras()
    argv = build_uv_install_argv(ref, extras=extras)
    target = f"git ref {ref}" if ref is not None else "the latest release"
    err_console.print(
        f"Updating mergecraft {mergecraft.__version__} to {target}: {shlex.join(argv)}",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    if dry_run:
        return
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
    "installed_extras",
    "release_requirement",
    "run",
    "uv_install_spec",
]
