"""Pinned git argv and environment for root-side subprocess invocations (MCB-01 / D2).

Every mergeCraft process that shells out to ``git`` while still privileged must
route through :func:`git_argv` so agent-writable ``.git/config`` cannot execute
hooks, fsmonitor, diff drivers, or other config-driven side effects.

Spawn sites that also control the child environment (the MCP ``git`` tools and
the helpers in this module and :mod:`mergecraft.utils.workspace`) go one step
further through :func:`hardened_git_command` / :func:`run_hardened_git`: the
system and global config files are not read, ambient env-injected config is
dropped, and helper commands config could name are pinned to inert values. That
is the single definition of the fixed configuration those spawns run with.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

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
    # Repository discovery only enters a bare-layout directory when it is named
    # explicitly (``--git-dir`` / ``GIT_DIR``), never by walking into it.
    "-c",
    "safe.bareRepository=explicit",
)

# Extra pins for the hardened tier (:func:`hardened_git_command`). They reset
# config-named helper programs to inert values; they are kept out of
# :data:`GIT_SAFE_CONFIG` because operator CLI runs legitimately rely on a
# keychain credential helper or a personal attributes file.
GIT_HARDENED_CONFIG: Final[tuple[str, ...]] = (
    "-c",
    "credential.helper=",
    "-c",
    "core.attributesFile=/dev/null",
    "-c",
    "core.askPass=",
    "-c",
    "gpg.program=gpg",
    "-c",
    "gpg.ssh.program=ssh-keygen",
    "-c",
    "gpg.x509.program=gpgsm",
)

# Fixed environment overlay for the hardened tier: no system or global config
# file, no system attributes file, no pager, no terminal prompt.
GIT_HARDENED_ENV: Final[Mapping[str, str]] = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
}

# Inherited variables a hardened git child never sees: they select config
# sources, relocate the repository, or name a program git runs.
_HARDENED_ENV_DROP_EXACT: Final[frozenset[str]] = frozenset(
    {
        "GIT_CONFIG",
        "GIT_CONFIG_SYSTEM",
        "GIT_CONFIG_PARAMETERS",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_COMMON_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_NAMESPACE",
        "GIT_CEILING_DIRECTORIES",
        "GIT_EXTERNAL_DIFF",
        "GIT_DIFF_OPTS",
        "GIT_EXEC_PATH",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "GIT_SSH",
        "GIT_SSH_COMMAND",
        "GIT_PROXY_COMMAND",
        "GIT_EDITOR",
        "GIT_SEQUENCE_EDITOR",
    }
)
_HARDENED_ENV_DROP_PREFIXES: Final[tuple[str, ...]] = ("GIT_TRACE",)
# Numbered command-scope config pairs. Ambient ones are dropped; pairs a caller
# builds itself (the brokered auth header) are kept with ``keep_config_pairs``.
_CONFIG_PAIR_NAMES: Final[tuple[str, ...]] = (
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_",
    "GIT_CONFIG_VALUE_",
)

_GLOBAL_OPTS_TAKING_VALUE: Final[frozenset[str]] = frozenset(
    {"-C", "--git-dir", "--work-tree", "--namespace"}
)
_PATCH_SUBCOMMANDS: Final[frozenset[str]] = frozenset(
    {"diff", "show", "range-diff", "format-patch"}
)
_LOG_PATCH_FLAGS: Final[frozenset[str]] = frozenset(
    {
        "-p",
        "-u",
        "--patch",
        "-U",
        "--unified",
        "-W",
        "--function-context",
        "--cc",
        "--patch-with-stat",
        "--patch-with-raw",
    }
)
# Short letters that make ``log``/``stash show`` emit a patch when bundled or
# glued to a value: ``-p``/``-u`` (patch), ``-U<n>`` (context), ``-W`` (function
# context), ``-L`` (line-log, always a patch) and ``-c`` (combined diff). A
# false positive (``-Sfoo`` containing one of these) only adds the safe flags.
_LOG_PATCH_SHORT_LETTERS: Final[frozenset[str]] = frozenset("puUWLc")
_DIFF_HARDENING_FLAGS: Final[tuple[str, ...]] = ("--no-ext-diff", "--no-textconv")
# ``log`` pickaxe searches (``-S`` / ``-G``) compare text-converted blobs.
_LOG_PICKAXE_PREFIXES: Final[tuple[str, ...]] = ("-S", "-G", "--pickaxe")
# Verbs that run textconv by default and accept only ``--no-textconv``.
_TEXTCONV_ONLY_SUBCOMMANDS: Final[frozenset[str]] = frozenset({"blame", "annotate"})


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
        if tok.startswith("--unified="):
            return True
        if (
            tok.startswith("-")
            and not tok.startswith("--")
            and any(letter in _LOG_PATCH_SHORT_LETTERS for letter in tok[1:])
        ):
            return True
    return False


def _has_pickaxe_flags(args: Sequence[str], start: int) -> bool:
    return any(tok.startswith(_LOG_PICKAXE_PREFIXES) for tok in args[start:])


def _diff_hardening_insertion(args: Sequence[str]) -> tuple[int, tuple[str, ...]] | None:
    """Return where in *args* to insert diff-hardening flags, and which flags."""
    sub_idx = _skip_global_opts(args, 0)
    if sub_idx >= len(args):
        return None
    subcommand = args[sub_idx]
    if subcommand in _PATCH_SUBCOMMANDS:
        return sub_idx + 1, _DIFF_HARDENING_FLAGS
    if subcommand in _TEXTCONV_ONLY_SUBCOMMANDS:
        return sub_idx + 1, ("--no-textconv",)
    if subcommand == "log" and (
        _has_patch_flags(args, sub_idx + 1) or _has_pickaxe_flags(args, sub_idx + 1)
    ):
        return sub_idx + 1, _DIFF_HARDENING_FLAGS
    if subcommand == "stash":
        show_idx = sub_idx + 1
        if (
            show_idx < len(args)
            and args[show_idx] == "show"
            and _has_patch_flags(args, show_idx + 1)
        ):
            return show_idx + 1, _DIFF_HARDENING_FLAGS
    return None


def normalize_git_remote_url(url: str) -> str:
    """Return *url* stripped of surrounding whitespace and a trailing slash."""
    return url.strip().rstrip("/")


def git_remote_identity_urls(url: str) -> tuple[str, ...]:
    """Return HTTPS remote URL forms that need identity ``insteadOf`` pins.

    ``actions/checkout`` stores ``remote.origin.url`` without a ``.git`` suffix
    while other call sites may use the suffixed form. Pinning every equivalent
    shape prevents a shorter hostile ``https://github.com/`` prefix from winning
    when the live remote omits ``.git``.
    """
    base = normalize_git_remote_url(url)
    if not base:
        return ()
    variants: set[str] = {base}
    if base.endswith(".git"):
        variants.add(base[: -len(".git")])
    elif base.startswith(("http://", "https://")):
        variants.add(f"{base}.git")
    return tuple(sorted(variants, key=len, reverse=True))


def read_remote_origin_url(cwd: str) -> str:
    """Return ``remote.origin.url`` without ``insteadOf`` expansion.

    ``git remote get-url`` applies checkout-local ``url.*.insteadOf`` rules,
    so a hostile ``.git/config`` can make it return an attacker URL. Reading
    the stored config key avoids that rewrite while still reflecting what the
    checkout declares as origin.
    """
    result = run_hardened_git(
        ["config", "--get", "remote.origin.url"],
        cwd=cwd,
        safe_directories=(cwd,),
        timeout=60,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        msg = f"git config --get remote.origin.url failed ({result.returncode}): {err}"
        raise RuntimeError(msg)
    return result.stdout.strip()


def url_rewrite_guard_config(canonical_url: str) -> tuple[str, ...]:
    """Return ``-c`` pins that outrank hostile ``url.*.insteadOf`` rewrites.

    Git unions ``insteadOf`` rules from every config scope and applies the
    longest matching prefix. A command-line identity rule whose base equals the
    full remote URL beats shorter attacker prefixes. Every equivalent remote
    shape (with and without a ``.git`` suffix) is pinned so the guard matches
    the live ``remote.origin.url`` from ``actions/checkout``.
    """
    pins: list[str] = []
    seen: set[str] = set()
    for variant in git_remote_identity_urls(canonical_url):
        entry = f"url.{variant}.insteadOf={variant}"
        if entry in seen:
            continue
        seen.add(entry)
        pins.extend(("-c", entry))
    return tuple(pins)


def _git_argv_with_prefixes(
    args: Sequence[str],
    *,
    extra_config: Sequence[str] = (),
) -> list[str]:
    argv: list[str] = ["git", *GIT_SAFE_CONFIG, *extra_config]
    insertion = _diff_hardening_insertion(args)
    if insertion is None:
        argv.extend(args)
        return argv
    insert_at, flags = insertion
    argv.extend(args[:insert_at])
    argv.extend(flags)
    argv.extend(args[insert_at:])
    return argv


def git_argv(args: Sequence[str]) -> list[str]:
    """Return ``git`` argv with every safe-config pin prepended before *args*."""
    return _git_argv_with_prefixes(args)


def git_authenticated_argv(args: Sequence[str], *, remote_url: str) -> list[str]:
    """Return hardened argv for authenticated fetch/push against *remote_url*."""
    return _git_argv_with_prefixes(args, extra_config=url_rewrite_guard_config(remote_url))


def _safe_directory_pins(paths: Iterable[str]) -> list[str]:
    """Return ``-c safe.directory=<path>`` pins for each distinct resolved path.

    The global config is not read on the hardened tier, so the ownership
    exemptions :func:`mergecraft.utils.workspace.add_safe_directory` records
    there are restated on the command line, which git also honours.
    """
    pins: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        if not raw:
            continue
        try:
            resolved = str(Path(raw).resolve())
        except OSError:
            resolved = raw
        for value in (raw, resolved):
            if value not in seen:
                seen.add(value)
                pins.extend(("-c", f"safe.directory={value}"))
    return pins


def hardened_git_env(
    base: Mapping[str, str] | None = None, *, keep_config_pairs: bool = False
) -> dict[str, str]:
    """Return the fixed child environment for a hardened git spawn.

    *base* defaults to the process environment. Inherited config sources,
    repository relocation, trace output and program overrides are dropped and
    :data:`GIT_HARDENED_ENV` is applied on top. Numbered ``GIT_CONFIG_*`` pairs
    survive only when *keep_config_pairs* is set, for an environment the caller
    built itself (the brokered auth header).
    """

    def _dropped(name: str) -> bool:
        if name in _HARDENED_ENV_DROP_EXACT or name.startswith(_HARDENED_ENV_DROP_PREFIXES):
            return True
        return not keep_config_pairs and name.startswith(_CONFIG_PAIR_NAMES)

    env = {
        name: value
        for name, value in (os.environ if base is None else base).items()
        if not _dropped(name)
    }
    env.update(GIT_HARDENED_ENV)
    return env


def hardened_git_command(
    args: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    keep_config_pairs: bool = False,
    safe_directories: Iterable[str] = (),
    remote_url: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Return ``(argv, env)`` for a git spawn on the hardened tier.

    The argv carries :data:`GIT_SAFE_CONFIG`, :data:`GIT_HARDENED_CONFIG`, a
    ``safe.directory`` pin per *safe_directories* entry, the ``insteadOf``
    identity pins when *remote_url* is given, and the diff-hardening flags.
    The env is :func:`hardened_git_env` of *env*.
    """
    extra: list[str] = [*GIT_HARDENED_CONFIG, *_safe_directory_pins(safe_directories)]
    if remote_url is not None:
        extra.extend(url_rewrite_guard_config(remote_url))
    argv = _git_argv_with_prefixes(args, extra_config=extra)
    return argv, hardened_git_env(env, keep_config_pairs=keep_config_pairs)


def run_hardened_git(
    args: Sequence[str],
    *,
    cwd: str | None,
    safe_directories: Iterable[str] = (),
    timeout: float = 60,
) -> subprocess.CompletedProcess[str]:
    """Run ``git`` on the hardened tier and return the completed process."""
    argv, env = hardened_git_command(args, safe_directories=safe_directories)
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def absolute_git_dir(path: str, *, safe_directories: Iterable[str] = ()) -> Path | None:
    """Return the resolved git dir git discovers from *path*, or ``None``.

    Runs on the hardened tier, so a bare-layout directory is only entered when
    named explicitly and no config-named program runs during discovery.
    """
    try:
        completed = run_hardened_git(
            ["rev-parse", "--absolute-git-dir"],
            cwd=path,
            safe_directories=(path, *safe_directories),
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):  # fmt: skip
        return None
    out = completed.stdout.strip()
    if completed.returncode != 0 or not out:
        return None
    try:
        return Path(out).resolve()
    except OSError:
        return None


def git_global_config_argv(args: Sequence[str]) -> list[str]:
    """Return ``git config`` argv for global writes (no repo-local safe pins)."""
    return ["git", "config", *args]


__all__ = [
    "GIT_HARDENED_CONFIG",
    "GIT_HARDENED_ENV",
    "GIT_SAFE_CONFIG",
    "absolute_git_dir",
    "git_argv",
    "git_authenticated_argv",
    "git_global_config_argv",
    "git_remote_identity_urls",
    "hardened_git_command",
    "hardened_git_env",
    "normalize_git_remote_url",
    "read_remote_origin_url",
    "run_hardened_git",
    "url_rewrite_guard_config",
]
