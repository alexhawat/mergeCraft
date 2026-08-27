"""Pinned git argv for root-side subprocess invocations (MCB-01 / D2).

Every mergeCraft process that shells out to ``git`` while still privileged must
route through :func:`git_argv` so agent-writable ``.git/config`` cannot execute
hooks, fsmonitor, diff drivers, or other config-driven side effects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

GIT_SAFE_CONFIG: Final[tuple[str, ...]] = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.sshCommand=ssh",
    "-c",
    "protocol.ext.allow=never",
    "-c",
    "core.pager=cat",
)

_GLOBAL_OPTS_TAKING_VALUE: Final[frozenset[str]] = frozenset(
    {"-C", "--git-dir", "--work-tree", "--namespace"}
)
_PATCH_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {"diff", "show", "range-diff", "format-patch"}
)
_LOG_PATCH_FLAGS: Final[frozenset[str]] = frozenset(
    {"-p", "--patch", "-U", "--unified", "-W", "--function-context"}
)
_DIFF_HARDENING_FLAGS: Final[tuple[str, ...]] = ("--no-ext-diff", "--no-textconv")


def _skip_global_opts(args: Sequence[str], start: int) -> int:
    """Return index of the first subcommand token after git global options."""
    idx = start
    while idx < len(args):
        tok = args[idx]
        if tok in _GLOBAL_OPTS_TAKING_VALUE:
            idx += 2
            continue
        if tok.startswith(("--git-dir=", "--work-tree=", "--namespace=")):
            idx += 1
            continue
        if tok.startswith("-"):
            idx += 1
            continue
        return idx
    return idx


def _has_patch_flags(args: Sequence[str], start: int) -> bool:
    for tok in args[start:]:
        if tok in _LOG_PATCH_FLAGS:
            return True
        if tok.startswith("-") and not tok.startswith("--") and "p" in tok[1:]:
            return True
    return False


def _no_ext_diff_insertion_index(args: Sequence[str]) -> int | None:
    """Return index in *args* where ``--no-ext-diff`` should be inserted."""
    sub_idx = _skip_global_opts(args, 0)
    if sub_idx >= len(args):
        return None
    subcommand = args[sub_idx]
    if subcommand in _PATCH_SUBCOMMANDS:
        return sub_idx + 1
    if subcommand == "log" and _has_patch_flags(args, sub_idx + 1):
        return sub_idx + 1
    if subcommand == "stash":
        show_idx = sub_idx + 1
        if (
            show_idx < len(args)
            and args[show_idx] == "show"
            and _has_patch_flags(args, show_idx + 1)
        ):
            return show_idx + 1
    return None


def _needs_no_ext_diff(args: Sequence[str]) -> bool:
    """Return whether *args* invoke git's external diff driver."""
    return _no_ext_diff_insertion_index(args) is not None


def url_rewrite_guard_config(canonical_url: str) -> tuple[str, ...]:
    """Return ``-c`` pins that outrank hostile ``url.*.insteadOf`` rewrites.

    Git unions ``insteadOf`` rules from every config scope and applies the
    longest matching prefix. A command-line identity rule whose base equals the
    full remote URL beats shorter attacker prefixes.
    """
    normalized = canonical_url.strip()
    if not normalized:
        return ()
    return ("-c", f"url.{normalized}.insteadOf={normalized}")


def _git_argv_with_prefixes(
    args: Sequence[str],
    *,
    extra_config: Sequence[str] = (),
) -> list[str]:
    argv: list[str] = ["git", *GIT_SAFE_CONFIG, *extra_config]
    insert_at = _no_ext_diff_insertion_index(args)
    if insert_at is None:
        argv.extend(args)
        return argv
    argv.extend(args[:insert_at])
    argv.extend(_DIFF_HARDENING_FLAGS)
    argv.extend(args[insert_at:])
    return argv


def git_argv(args: Sequence[str]) -> list[str]:
    """Return ``git`` argv with every safe-config pin prepended before *args*."""
    return _git_argv_with_prefixes(args)


def git_authenticated_argv(args: Sequence[str], *, remote_url: str) -> list[str]:
    """Return hardened argv for authenticated fetch/push against *remote_url*."""
    return _git_argv_with_prefixes(args, extra_config=url_rewrite_guard_config(remote_url))


def git_global_config_argv(args: Sequence[str]) -> list[str]:
    """Return ``git config`` argv for global writes (no repo-local safe pins)."""
    return ["git", "config", *args]


__all__ = [
    "GIT_SAFE_CONFIG",
    "git_argv",
    "git_authenticated_argv",
    "git_global_config_argv",
    "url_rewrite_guard_config",
]
