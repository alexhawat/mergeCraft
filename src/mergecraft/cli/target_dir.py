"""Resolve the working directory for CLI commands that take ``--cwd``.

Module: mergecraft.cli.target_dir
Depends: click, mergecraft.utils.workspace

One rule for every command that names a repository with a directory option
(``--cwd``, ``--repo-root``, ``--repo``) defaulting to ``.``:

* an **omitted** option resolves to the git work-tree root that contains the
  process working directory, so a command run from ``src/pkg`` reads and writes
  the same ``.mergecraft/`` and ``.env`` as one run from the root;
* an **explicit** option is taken literally, so ``--cwd sub/dir`` still names
  exactly that directory (#520 / #654);
* outside a git checkout the omitted option stays the process working directory.

Exports:
    Functions:
        target_dir — The directory a command operates on, resolved.
        implicit_repo_root — Git root of the process cwd, or the cwd itself.
        install_implicit_repo_root — Make a command's omitted directory option resolve to the root.
"""

from __future__ import annotations

import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from click.core import ParameterSource

from mergecraft.utils.workspace import git_repo_root

if TYPE_CHECKING:
    from collections.abc import Callable

#: Directory options that name the repository a command acts on.
_REPO_DIR_PARAM_NAMES = frozenset({"cwd", "repo_root", "repo"})
_IMPLICIT_SOURCES = frozenset({ParameterSource.DEFAULT, ParameterSource.DEFAULT_MAP})
#: Commands whose directory options already carry the resolver (install once).
_INSTALLED: weakref.WeakSet[click.Command] = weakref.WeakSet()


def target_dir(cwd: Path) -> Path:
    """The directory this command operates on — ``cwd``, resolved.

    Deliberately not ``git_repo_root``: an explicit ``--cwd`` names whatever
    tree it points at, including one that is not a git checkout. An omitted
    ``--cwd`` has already been resolved to the repository root by
    :func:`install_implicit_repo_root` before the command runs.

    Args:
        cwd (Path): The command's ``--cwd`` value.

    Returns:
        Path: The resolved directory.

    Examples:
        >>> target_dir(Path("/")) == Path("/")
        True
    """
    return cwd.resolve()


def implicit_repo_root() -> Path:
    """Return the git root containing the process cwd, or the cwd outside a checkout.

    Returns:
        Path: Absolute directory an omitted ``--cwd`` stands for.
    """
    start = Path.cwd().resolve()
    return git_repo_root(str(start)) or start


def _is_repo_dir_option(param: click.Parameter) -> bool:
    """True for a ``--cwd``-style option whose default is the current directory.

    Args:
        param (click.Parameter): A command parameter.

    Returns:
        bool: Whether an omitted value should resolve to the repository root.
    """
    if not isinstance(param, click.Option) or param.name not in _REPO_DIR_PARAM_NAMES:
        return False
    default = param.default
    return default == "." or (isinstance(default, Path) and default == Path())


def _root_resolving_callback(
    original: Callable[[click.Context, click.Parameter, Any], Any] | None,
) -> Callable[[click.Context, click.Parameter, Any], Any]:
    """Wrap *original* so an omitted value becomes :func:`implicit_repo_root`.

    Args:
        original (Callable | None): The option's existing callback, if any.

    Returns:
        Callable: A Click option callback.
    """

    def callback(ctx: click.Context, param: click.Parameter, value: Any) -> Any:
        if (
            param.name is not None
            and not ctx.resilient_parsing
            and ctx.get_parameter_source(param.name) in _IMPLICIT_SOURCES
        ):
            value = implicit_repo_root()
        return original(ctx, param, value) if original is not None else value

    return callback


def install_implicit_repo_root(command: click.Command) -> None:
    """Make *command*'s omitted ``--cwd``-style options resolve to the repository root.

    Installed once per command by the CLI group, so every command — and any
    added later — follows the same rule without its own resolver.

    Args:
        command (click.Command): The command about to be invoked.
    """
    if command in _INSTALLED:
        return
    for param in command.params:
        if _is_repo_dir_option(param):
            param.callback = _root_resolving_callback(param.callback)
    _INSTALLED.add(command)


__all__ = ["implicit_repo_root", "install_implicit_repo_root", "target_dir"]
