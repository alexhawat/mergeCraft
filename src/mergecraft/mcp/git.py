"""Read-only Git inspection and bounded fetch tools."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.mcp.git_guards import (
    _BAD_REF_CHARS,
    _BRANCH_FLAGS_TAKING_VALUE,
    _BRANCH_READONLY_FLAGS,
    _CONFIG_FLAGS,
    _OUTPUT_FLAG_SPELLINGS,
    _READONLY_SUBCOMMANDS,
    _REDIRECT_TO_TOOL,
    _SUBCOMMAND_OWNS_DASH_C,
    _SUBCOMMAND_SHORT_FLAGS,
    _SYMBOLIC_REFS,
    _is_config_flag,
    _reject_branch_writes,
    _reject_config_flags,
    _reject_config_invocation,
    _reject_content_filter_exec,
    _reject_credential_path_operands,
    _reject_file_writing_flags,
    _reject_grep_pager_exec,
    _reject_namespace_flag,
    _reject_no_index,
    _reject_refused_long_options,
    _split_end_of_options,
    _subcommand_declares_shorts,
    reject_if_leading_dash,
    reject_special_ref,
    resolve_grep_long_option,
    validate_fetch_refspec,
    validate_tag_name,
)
from mergecraft.mcp.shared import (
    ToolClass,
    ToolRefusedError,
    execute,
    tool,
)
from mergecraft.mcp.tool_state import primary_repo_state, require_repo_state
from mergecraft.utils.blocking import run_blocking
from mergecraft.utils.git_hardening import (
    absolute_git_dir,
    hardened_git_command,
    read_remote_origin_url,
)
from mergecraft.utils.git_process import run_git_process
from mergecraft.utils.git_setup import run_export_directory
from mergecraft.utils.path_confinement import (
    checkout_identity_paths,
    is_denied_credential_path,
    resolve_tool_path,
)
from mergecraft.utils.workspace import registered_safe_directories

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Sequence

    from mergecraft.mcp.context import ToolContext

__all__ = [
    "_BAD_REF_CHARS",
    "_BRANCH_FLAGS_TAKING_VALUE",
    "_BRANCH_READONLY_FLAGS",
    "_CONFIG_FLAGS",
    "_OUTPUT_FLAG_SPELLINGS",
    "_READONLY_SUBCOMMANDS",
    "_REDIRECT_TO_TOOL",
    "_SUBCOMMAND_OWNS_DASH_C",
    "_SUBCOMMAND_SHORT_FLAGS",
    "_SYMBOLIC_REFS",
    "_is_config_flag",
    "_reject_branch_writes",
    "_reject_config_flags",
    "_reject_config_invocation",
    "_reject_credential_path_operands",
    "_reject_file_writing_flags",
    "_reject_grep_pager_exec",
    "_reject_namespace_flag",
    "_reject_no_index",
    "_reject_refused_long_options",
    "_split_end_of_options",
    "_subcommand_declares_shorts",
    "reject_if_leading_dash",
    "reject_special_ref",
    "validate_tag_name",
]


def _confine_to_repo_root(value: str, flag: str, base: str) -> Path:
    """Confine *value* to an allowed workspace root, resolved against *base*.

    Delegates to the canonical workspace rule so the git tool, ``upload_file``
    and shell cwd containment cannot drift apart, and so a cross-repo checkout
    registered as a workspace root is reachable (#257 / D7).
    """
    from mergecraft.utils.workspace import WorkspacePathError, confine_to_workspace

    try:
        return confine_to_workspace(value, base=base)
    except WorkspacePathError as exc:
        msg = f"Blocked: '{flag}' '{value}' must be within the repo checkout — {exc}"
        raise ToolRefusedError(msg) from exc


def _checkout_refusal(flag: str, value: str) -> ToolRefusedError:
    return ToolRefusedError(
        f"Blocked: '{flag}' '{value}' must name a registered checkout "
        "(its root or its own git directory)"
    )


def _names_registered_checkout(
    path: Path, *, work_trees: set[Path], git_dirs: set[Path], safe_roots: list[str]
) -> bool:
    """Whether running git in *path* selects one of the registered checkouts.

    A registered root or git dir matches outright. A subdirectory of a
    registered root matches only when git's own discovery from it lands on
    that checkout's git dir, so a nested repository inside the tree does not.
    """
    if path in work_trees or path in git_dirs:
        return True
    if not any(_is_within(path, root) for root in work_trees):
        return False
    discovered = absolute_git_dir(str(path), safe_directories=safe_roots)
    return discovered is not None and discovered in git_dirs


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _validate_path_confinement(
    global_opts: list[str], cwd: str, *, checkout_roots: Sequence[str] = ()
) -> None:
    """Bind -C / --git-dir / --work-tree in *global_opts* to a registered checkout.

    ``-C`` must land in a registered checkout root, or in a directory of it
    from which git discovers that same checkout; ``--git-dir`` must be a
    registered checkout's own git directory and ``--work-tree`` a registered
    checkout root. Being inside the workspace is not enough: the selected
    repository's config is honoured, so it has to be one this run registered.

    git applies successive ``-C`` options **cumulatively** and resolves each
    relative to the previous one, so the walk carries the accumulated directory
    forward rather than validating every value against the starting cwd — which
    would accept a pair whose combined effect escapes.
    """
    if not global_opts:
        return
    roots = [root for root in (*checkout_roots, cwd) if root]
    work_trees, git_dirs = checkout_identity_paths(roots)
    current = cwd
    idx = 0
    while idx < len(global_opts):
        tok = global_opts[idx]
        if tok.startswith(("--git-dir=", "--work-tree=")):
            flag, _, value = tok.partition("=")
            idx += 1
        elif tok in {"-C", "--git-dir", "--work-tree"} and idx + 1 < len(global_opts):
            flag, value = tok, global_opts[idx + 1]
            idx += 2
        else:
            idx += 1
            continue
        if flag == "-C":
            target = _confine_to_repo_root(value, "-C", current)
            if not _names_registered_checkout(
                target, work_trees=work_trees, git_dirs=git_dirs, safe_roots=roots
            ):
                raise _checkout_refusal(flag, value)
            current = str(target)
            continue
        resolved = resolve_tool_path(value, base=current)
        allowed = git_dirs if flag == "--git-dir" else work_trees
        if resolved is None or resolved not in allowed:
            raise _checkout_refusal(flag, value)


# ``ls-remote`` options that take their value as the next token.
_LS_REMOTE_VALUE_OPTIONS = frozenset({"--sort", "-o", "--server-option", "--upload-pack", "--exec"})


def _ls_remote_repository(args: list[str]) -> str | None:
    """Return the repository operand of an ``ls-remote`` invocation, if any."""
    idx = 0
    options_done = False
    while idx < len(args):
        tok = args[idx]
        if not options_done:
            if tok == "--":
                options_done = True
                idx += 1
                continue
            if tok in _LS_REMOTE_VALUE_OPTIONS:
                idx += 2
                continue
            if tok.startswith("-"):
                idx += 1
                continue
        return tok
    return None


def _validate_ls_remote_operand(
    args: list[str], cwd: str, *, tmpdir: str, checkout_roots: Sequence[str] = ()
) -> None:
    """Keep ``ls-remote`` to ``origin`` or a registered checkout.

    No repository operand, ``origin``, or a local path / ``file://`` URL that
    resolves to a registered checkout (root or git dir) is accepted; any other
    remote or path is refused.
    """
    repository = _ls_remote_repository(args)
    if repository is None or repository == "origin":
        return
    value = repository[len("file://") :] if repository.startswith("file://") else repository
    refusal = ToolRefusedError(
        f"Blocked: 'ls-remote {repository}' — only 'origin' or a registered checkout "
        "may be queried through this tool"
    )
    if "://" in value or not value:
        raise refusal
    roots = [root for root in (*checkout_roots, cwd) if root]
    if is_denied_credential_path(value, cwd=cwd, tmpdir=tmpdir, checkout_roots=roots):
        raise refusal
    resolved = resolve_tool_path(value, base=cwd)
    work_trees, git_dirs = checkout_identity_paths(roots)
    if resolved is None or (resolved not in work_trees and resolved not in git_dirs):
        raise refusal


def _validate_positional_path_confinement(args: list[str], cwd: str) -> None:
    """Confine positional path operands to the workspace (plan 13 / D9).

    After ``--``, every operand is a filesystem path and must stay inside an
    allowed root. Before ``--``, only operands that are already absolute paths
    are confined — revision specs such as ``origin/main:file`` are left alone.
    """
    before, after = _split_end_of_options(args)
    for operand in after:
        _confine_to_repo_root(operand, "path", cwd)
    for operand in before:
        if operand.startswith("-"):
            continue
        if Path(operand).is_absolute():
            _confine_to_repo_root(operand, "path", cwd)


def _origin_remote_url(cwd: str) -> str:
    return read_remote_origin_url(cwd)


# Shapes GitHub's git transport returns when the brokered credential is not
# accepted. Surfacing these as a distinct, non-retryable message keeps the
# reviewing agent from re-running the same fetch — a rejected token cannot
# resolve itself across attempts, and the retry loop is what turned a one-line
# auth bug into multi-million-token runs (issue #544).
_AUTH_FAILURE_MARKERS: tuple[str, ...] = (
    "invalid credentials",
    "authentication failed",
    "could not read username",
    "could not read password",
    "terminal prompts disabled",
    # git surfaces an HTTP status curl could not resolve as a challenge in this
    # exact shape: ``fatal: unable to access '<url>': The requested URL
    # returned error: 403``. A 403 is the *permission* failure — a token that
    # authenticated but lacks `contents: read`, an unauthorized SSO grant, a
    # fork — so it is the one most in need of the terminal hint, and matching
    # only ``403 forbidden`` never saw it. A 401 usually arrives here as a
    # prompt failure instead (the server sends WWW-Authenticate, git re-asks,
    # and ``GIT_TERMINAL_PROMPT=0`` kills it), but it takes this shape when the
    # challenge header is absent, so both codes are matched.
    "the requested url returned error: 401",
    "the requested url returned error: 403",
    # GitHub's own bodies for the same class. Neither carries a status code.
    "remote: permission to",
    "write access to repository not granted",
    "duplicate header",
    # Retained: older curl builds append the reason phrase to the message above
    # (``... returned error: 403 Forbidden``), and proxies in front of a remote
    # emit the bare phrase. Cheap to keep, and dropping them would narrow the
    # match on exactly the environments hardest to reproduce.
    "403 forbidden",
    "401 unauthorized",
    # mergecraft's ``_run_git`` wrapper prefixes stderr as
    # ``git <args> failed (<code>): …``; keep these terminal when stderr is terse.
    "failed (403)",
    "failed (401)",
)

_AUTH_FAILURE_HINT = (
    "git rejected the brokered GitHub credential — the token is missing, expired, "
    "or lacks access to this repository. Retrying will not help; the run needs a "
    "valid token (contents: read for fetch, contents: write for push)"
)

_SHOW_REV_PATH_RE = re.compile(r"^([^:]+):(.+)$")
# A historical file is returned as a bounded head plus the path of the saved
# full body. Five lines was too little to act on: run 78b122af spent 162 git
# calls re-querying context the saved file already held (#1474).
_GIT_SHOW_PREVIEW_LINES = 120
_GIT_SHOW_PREVIEW_CHARS = 12_000
_GIT_OUTPUT_PREVIEW_LINES = 40


def _export_dir(ctx: ToolContext) -> Path:
    """Where this run saves git output for the agent's file-read tool (#1474)."""
    return run_export_directory(ctx.tmpdir)


def _parse_show_rev_path(args: list[str]) -> tuple[str, str] | None:
    for raw in args:
        if raw == "--":
            continue
        if raw.startswith("-"):
            continue
        match = _SHOW_REV_PATH_RE.fullmatch(raw)
        if match is not None:
            rev, path = match.group(1), match.group(2)
            if rev and path:
                return rev, path
    return None


def _git_show_cache_identity(
    *, cwd: str, global_opts: list[str], args: list[str]
) -> tuple[str, str] | None:
    """Cache only a single unformatted blob, resolved in the selected repository.

    Resolve symbolic refs on every call and read that exact object afterwards:
    a ref moving between lookup and execution cannot poison its cache entry.
    Multi-object and option-bearing shows retain Git's ordinary semantics.
    """
    if len(args) != 1 or "\n" in args[0] or "\r" in args[0]:
        return None
    identity = (
        _run_git(
            [*global_opts, "cat-file", "--batch-check=%(objectname) %(objecttype)"],
            cwd=cwd,
            input_text=args[0] + "\n",
        )
        .strip()
        .split()
    )
    if len(identity) != 2:
        return None
    object_id, kind = identity
    if kind != "blob" or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", object_id):
        return None
    key = json.dumps([str(Path(cwd).resolve()), global_opts, args, object_id])
    return key, object_id


def _git_show_output_path(export_dir: Path, identity: str) -> str:
    digest = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return str(export_dir / f"git-show-{digest}.txt")


def _bounded_preview(text: str, *, max_lines: int, saved_to: str) -> tuple[str, int, bool]:
    """Head of ``text`` within the line and character bounds, and whether it was cut.

    Only the returned preview is bounded; the file at ``saved_to`` always holds
    the whole text. A cut preview ends by naming that file and the line count,
    so the agent reads the rest with one native read instead of re-querying.
    """
    lines = text.splitlines()
    shown: list[str] = []
    used = 0
    clipped = False
    for line in lines[:max_lines]:
        used += len(line) + 1
        if shown and used > _GIT_SHOW_PREVIEW_CHARS:
            break
        # A single line can exceed the bound on its own (minified JSON/JS).
        clipped = clipped or len(line) > _GIT_SHOW_PREVIEW_CHARS
        shown.append(line[:_GIT_SHOW_PREVIEW_CHARS])
    truncated = clipped or len(shown) < len(lines)
    preview = "\n".join(shown)
    if truncated:
        cut = f", long lines cut at {_GIT_SHOW_PREVIEW_CHARS} characters" if clipped else ""
        preview = (
            f"{preview}\n... [truncated: lines 1-{len(shown)} of {len(lines)} shown{cut}; "
            f"the full body is saved to {saved_to} — read it with your file-read "
            "tool (offset/limit) instead of re-running git] ..."
        )
    return preview, len(lines), truncated


def _git_show_result(output_path: str) -> dict[str, Any]:
    text = Path(output_path).read_text(encoding="utf-8")
    preview, total, truncated = _bounded_preview(
        text, max_lines=_GIT_SHOW_PREVIEW_LINES, saved_to=output_path
    )
    return {
        "output": preview,
        "outputPath": output_path,
        "totalLines": total,
        "truncated": truncated,
    }


# Grep context the tool passes through. Past this, grep is being used to read
# whole function bodies: one timed-out self-review spent ~40 of its 102 git
# calls on `git grep -A 40..70 'def X'` (437 KB of output) and never used a
# line-range read. Larger context is dropped and the match locations returned.
_GREP_MAX_CONTEXT_LINES = 10
_GREP_UNBOUNDED_CONTEXT = 1 << 30
# git's context count: strtoul base 0 after optional C whitespace and "+", then a k/m/g unit.
_GIT_COUNT_RE = re.compile(r"[ \t\n\v\f\r]*\+?(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)([kKmMgG]?)")
_GIT_COUNT_UNITS = {"": 1, "k": 1 << 10, "m": 1 << 20, "g": 1 << 30}
# The bare ``-NUM`` short form is decimal digits only (``-010`` is ten lines).
_GREP_NUM_OPTION_RE = re.compile(r"-([0-9]+)")
_GREP_CONTEXT_LONG = frozenset({"--after-context", "--before-context", "--context"})
# Short letters whose value is the rest of the bundle or, failing that, the next token.
_GREP_SHORT_VALUE_LETTERS = frozenset("ABCefm")
_GREP_LONG_TAKING_VALUE = _GREP_CONTEXT_LONG | {"--max-depth", "--max-count", "--threads"}
_GREP_CONTEXT_NOTE = (
    "Context lines dropped: grep context over "
    f"{_GREP_MAX_CONTEXT_LINES} lines (or -W) returns whole bodies. These are the "
    "match locations (path:line:text). To read a body, open the file with your "
    "file-read tool (read/Read) at offset=<match line> with a limit, not grep context."
)
# Shell readers agents reach for through this tool. Refused like any verb off
# the allowlist, but the refusal names the read that does the job.
_FILE_READER_VERBS = frozenset({"sed", "cat", "head", "tail", "awk"})
_SED_LINE_RANGE_RE = re.compile(r"^(\d+),(\d+)p$")


def _grep_segments(head: list[str]) -> tuple[list[tuple[bool, list[str]]], bool]:
    """Split grep args before ``--`` into ordered option and positional segments.

    An option segment is the option token plus the separate value it consumes,
    if any; a positional segment is one token. The flag reports whether an
    option followed a positional: git grep stops option parsing at the pattern,
    so ``grep 'def x' -A 4`` exits 128.
    """
    segments: list[tuple[bool, list[str]]] = []
    seen_positional = misplaced = False
    idx = 0
    while idx < len(head):
        tok = head[idx]
        if not tok.startswith("-") or tok == "-":
            segments.append((False, [tok]))
            seen_positional = True
            idx += 1
            continue
        misplaced = misplaced or seen_positional
        if tok.startswith("--"):
            takes_value = "=" not in tok and (
                resolve_grep_long_option(tok) in _GREP_LONG_TAKING_VALUE
            )
        else:
            body = tok[1:]
            letter = next((c for c in body if c in _GREP_SHORT_VALUE_LETTERS), "")
            takes_value = (
                _GREP_NUM_OPTION_RE.fullmatch(tok) is None
                and bool(letter)
                and body.index(letter) == len(body) - 1
            )
        width = 2 if takes_value and idx + 1 < len(head) else 1
        segments.append((True, head[idx : idx + width]))
        idx += width
    return segments, misplaced


def _context_value(value: str) -> int:
    """Parse a context count the way git does, or fail closed.

    git reads it with ``strtoul(value, &end, 0)`` plus an optional k/m/g
    suffix: leading whitespace and ``+`` are allowed, ``0x10`` is hex and
    ``010`` octal, and ``1k`` is 1024 lines. Anything else counts as unbounded,
    so the option is dropped rather than forwarded unexamined.
    """
    match = _GIT_COUNT_RE.fullmatch(value)
    if match is None:
        return _GREP_UNBOUNDED_CONTEXT
    digits, unit = match.groups()
    if digits[:2].lower() == "0x":
        base = 16
    elif digits.startswith("0"):
        base = 8
    else:
        base = 10
    return int(digits, base) * _GIT_COUNT_UNITS[unit.lower()]


def _strip_grep_context(group: list[str]) -> tuple[list[str], int]:
    """Return *group* without its context option, and the context lines it asked for.

    Long options are matched by the name git resolves them to, so an
    abbreviation (``--after=60``, ``--func``) counts like its full spelling.
    """
    tok = group[0]
    separate = group[1] if len(group) > 1 else ""
    if tok.startswith("--"):
        name = resolve_grep_long_option(tok)
        if name == "--function-context":
            return [], _GREP_UNBOUNDED_CONTEXT
        if name in _GREP_CONTEXT_LONG:
            _, has_inline, inline = tok.partition("=")
            return [], _context_value(inline if has_inline else separate)
        return group, 0
    body = tok[1:]
    if _GREP_NUM_OPTION_RE.fullmatch(tok) is not None:
        return [], int(body)
    kept: list[str] = []
    lines = 0
    for idx, char in enumerate(body):
        if char == "W":
            lines = _GREP_UNBOUNDED_CONTEXT
            continue
        if char in "ABC":
            lines = max(lines, _context_value(body[idx + 1 :] or separate))
            return ([f"-{''.join(kept)}"] if kept else []), lines
        if char in _GREP_SHORT_VALUE_LETTERS:
            # -e / -f / -m: the rest of the bundle (or the next token) is a value.
            return [f"-{''.join(kept)}{body[idx:]}", *group[1:]], lines
        kept.append(char)
    return ([f"-{''.join(kept)}"] if kept else []), lines


def _shows_line_numbers(groups: list[list[str]]) -> bool:
    for group in groups:
        tok = group[0]
        if tok.startswith("--"):
            if resolve_grep_long_option(tok) == "--line-number":
                return True
            continue
        options = tok[1:]
        for idx, char in enumerate(options):
            if char in _GREP_SHORT_VALUE_LETTERS:
                options = options[:idx]
                break
        if "n" in options:
            return True
    return False


def _normalize_grep_args(args: list[str]) -> tuple[list[str], bool]:
    """Move misplaced grep options before the pattern and drop oversized context.

    Returns the args to run and whether context was dropped (``-n`` is then
    added if missing, so every match carries the line to read from). Args come
    back untouched when every option precedes the pattern and no context
    exceeds ``_GREP_MAX_CONTEXT_LINES``. A ``(``/``)`` boolean expression is
    never reordered, since its operators interleave with ``-e`` patterns, but
    oversized context is still removed from it in place.
    """
    end = args.index("--") if "--" in args else len(args)
    head, tail = args[:end], args[end:]
    segments, misplaced = _grep_segments(head)
    if "(" in head or ")" in head:
        misplaced = False
    stripped = [
        (_strip_grep_context(toks) if is_option else (toks, 0)) for is_option, toks in segments
    ]
    oversized = any(lines > _GREP_MAX_CONTEXT_LINES for _, lines in stripped)
    if not oversized and not misplaced:
        return args, False
    if oversized:
        segments = [
            (is_option, kept)
            for (is_option, _), (kept, _) in zip(segments, stripped, strict=True)
            if kept
        ]
        if not _shows_line_numbers([toks for is_option, toks in segments if is_option]):
            segments.insert(0, (True, ["-n"]))
    if misplaced:
        segments = sorted(segments, key=lambda segment: not segment[0])
    return [*(tok for _, toks in segments for tok in toks), *tail], oversized


def _file_reader_hint(command: str, args: list[str]) -> str:
    """Name the native read that replaces a refused ``sed``/``cat``/... call."""
    for arg in args:
        match = _SED_LINE_RANGE_RE.fullmatch(arg)
        if command == "sed" and match is not None:
            first, last = int(match.group(1)), int(match.group(2))
            return (
                f"To read lines {first}-{last}, use your file-read tool (read/Read) "
                f"with offset={first} limit={last - first + 1}."
            )
    return (
        "To read a file or a line range, use your file-read tool (read/Read) with "
        "an offset and limit, e.g. offset=840 limit=100 for lines 840-939."
    )


def _is_auth_failure(stderr: str) -> bool:
    """Return whether git's failure output shows a rejected/absent credential."""
    lowered = stderr.lower()
    return any(marker in lowered for marker in _AUTH_FAILURE_MARKERS)


class _GitCommandError(RuntimeError):
    """A non-zero git exit, carrying the exit code and stderr beside the message.

    The message is the same redacted, auth-hint-annotated ``git … failed (N)``
    string this tool has always raised; the attributes let an intent-aware
    caller tell an expected non-zero answer (``git grep``'s no-match exit 1,
    #1077) apart from a failure without parsing the message back out.
    """

    def __init__(self, args: list[str], result: subprocess.CompletedProcess[str]) -> None:
        raw_err = (result.stderr or result.stdout or "").strip()
        err = redact_secrets(raw_err)
        message = f"git {' '.join(args)} failed ({result.returncode}): {err}"
        if _is_auth_failure(raw_err):
            logger.error("git auth failure on `git {}`: {}", " ".join(args), err)
            message = f"{message}\n{_AUTH_FAILURE_HINT}"
        super().__init__(message)
        self.returncode = result.returncode
        self.stderr = result.stderr or ""


MAX_GIT_OUTPUT_BYTES = 20 * 1024 * 1024


def _run_git(
    args: list[str],
    *,
    cwd: str,
    env: dict[str, str] | None = None,
    remote_url: str | None = None,
    input_text: str | None = None,
) -> str:
    # Every spawn runs on the hardened tier: no system/global config, inert
    # helper programs, and the registered checkouts restated as safe.directory.
    safe_dirs = (cwd, *registered_safe_directories())
    if env is not None and env.get("GIT_CONFIG_COUNT"):
        resolved_remote = remote_url or _origin_remote_url(cwd)
        argv, child_env = hardened_git_command(
            args,
            env=env,
            keep_config_pairs=True,
            safe_directories=safe_dirs,
            remote_url=resolved_remote,
        )
    else:
        argv, child_env = hardened_git_command(args, env=env, safe_directories=safe_dirs)
    result = run_git_process(
        argv,
        cwd=cwd,
        env=child_env,
        output_limit=MAX_GIT_OUTPUT_BYTES,
        timeout=600,
        input_text=input_text,
    )
    if result.returncode != 0:
        raise _GitCommandError(args, result)
    return result.stdout


def _run_grep(args: list[str], *, cwd: str) -> tuple[str, bool]:
    """Run ``git grep`` and return ``(stdout, matched)``.

    Exit 1 with a clean stderr is grep's "no lines selected" answer — a
    successful no-match, not a failure (#1077; the ``git``-door instance of
    #1027's intent-aware outcome rule). Exit 1 carrying stderr output, and
    every other non-zero exit, stays fail-closed: the ``_run_git`` error
    propagates unchanged.
    """
    try:
        return _run_git(args, cwd=cwd), True
    except _GitCommandError as err:
        if err.returncode != 1 or err.stderr.strip():
            raise
        return "", False


def _run_merge_base(args: list[str], *, cwd: str) -> tuple[str, bool]:
    """Run ``git merge-base`` and return ``(stdout, found)``.

    Exit 1 with clean stderr is a successful negative answer: ``--is-ancestor``
    returns it when the first commit is not an ancestor of the second, and the
    plain form returns it when the commits share no merge base. Both are
    answers, not failures (#1077). Exit 1 carrying stderr output, and every
    other non-zero exit, stays fail-closed.
    """
    try:
        return _run_git(args, cwd=cwd), True
    except _GitCommandError as err:
        if err.returncode != 1 or err.stderr.strip():
            raise
        return "", False


def _run_authenticated_git(
    args: list[str],
    *,
    cwd: str,
    token: str,
    trusted_remote_url: str | None = None,
) -> str:
    live_url = _origin_remote_url(cwd)
    auth_url = trusted_remote_url or live_url
    return _run_git(
        args,
        cwd=cwd,
        env=_git_env(token, remote_url=auth_url),
        remote_url=live_url,
    )


def _git_env(token: str, *, remote_url: str = "") -> dict[str, str]:
    from mergecraft.utils.git_setup import git_env_for_token

    return git_env_for_token(token, remote_url=remote_url)


# Git global options that may precede the subcommand. `-C` takes a separate
# argument; the `--git-dir`/`--work-tree`/`--namespace` family may be spelled
# as `--flag value` or `--flag=value`. `--namespace` is extracted so its value
# is pulled out of the args too, then refused by `_reject_namespace_flag`.
# `-c`/`--config-env` are intentionally excluded: they are rejected
# unconditionally (alias-execution vector).
_GLOBAL_OPTS = ("-C", "--git-dir", "--work-tree", "--namespace")
_GLOBAL_OPT_RE = re.compile(r"^--(?:git-dir|work-tree|namespace)(?:=.*)?$")


def _extract_global_opts(
    cmd_tokens: list[str], args: list[str]
) -> tuple[str, list[str], list[str]]:
    """Pull global git options out of command tokens + args, placing them first.

    git requires global options (``-C``/``--git-dir``/``--work-tree``/
    ``--namespace``) before the subcommand, but the reviewing agent may emit
    them anywhere (e.g. ``command="status"`` with ``args=["-C", dir]`` or
    ``command="git -C dir status"``). Extract them regardless of position,
    collect them into ``global_opts`` (flag plus its value when separate), and
    return the real subcommand plus the remaining positional args. The
    subcommand is validated separately so these options are forwarded rather
    than rejected as an "invalid subcommand".

    ``-c`` / ``--config-env`` are intentionally excluded from extraction —
    they are rejected unconditionally by ``_reject_config_flags`` before
    reaching ``_run_git``.

    ``-C`` *after* a subcommand that defines it is left alone: to ``git diff``
    it is find-copies, and swallowing it as the chdir option also ate the next
    token as its directory, mangling the invocation.
    """
    tokens: list[str] = list(cmd_tokens)
    tokens.extend(args)

    global_opts: list[str] = []
    rest: list[str] = []
    subcommand = ""
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        owns_dash_c = tok == "-C" and subcommand in _SUBCOMMAND_OWNS_DASH_C
        is_global = not owns_dash_c and (
            tok in _GLOBAL_OPTS or _GLOBAL_OPT_RE.fullmatch(tok) is not None
        )
        if not is_global:
            if not subcommand:
                subcommand = tok
            else:
                rest.append(tok)
            idx += 1
            continue
        global_opts.append(tok)
        inline_value = "=" in tok
        if not inline_value and idx + 1 < len(tokens):
            global_opts.append(tokens[idx + 1])
            idx += 2
        else:
            idx += 1

    return subcommand, rest, global_opts


def _validate_git_invocation(
    command: str,
    args: list[str],
    global_opts: list[str],
    cwd: str,
    *,
    tmpdir: str = "",
    checkout_roots: Sequence[str] = (),
) -> None:
    """Run every guard a normalized git invocation must pass, in order.

    The order is the contract, which is why it lives in one function rather than
    as a comment over six sequential calls: the config-flag and ``--namespace``
    refusals come first because they apply whatever the verb is, the redirect
    precedes the allowlist so a rejected verb names its dedicated tool instead
    of producing a generic "invalid subcommand", and path confinement runs last
    because it needs the cwd git will actually run in.

    Raises:
        ToolRefusedError: on every refusal — the verb redirect, the read-only
        allowlist, and each guard's "Blocked:" stop all count (#1073).
    """
    # Unconditional: -c / --config-env are alias-execution vectors (#257 / D7).
    # global_opts is scanned with no subcommand — the pre-subcommand slot has no
    # verb to scope short flags against, so the strict reading applies there.
    _reject_config_flags(global_opts)
    _reject_config_flags(args, subcommand=command)
    _reject_no_index(global_opts)
    _reject_no_index(args, subcommand=command)
    # Unconditional: --namespace reaches the same pre-subcommand slot and is
    # the one extracted global option no path rule can confine.
    _reject_namespace_flag(global_opts)
    _reject_namespace_flag(args)
    redirect = _REDIRECT_TO_TOOL.get(command)
    if redirect:
        msg = f"git {command} is not available through this tool — {redirect}"
        raise ToolRefusedError(msg)
    # Read-only allowlist: replace the old format-only _SUBCOMMAND_RE (#257 / D7).
    if not command or command not in _READONLY_SUBCOMMANDS:
        msg = (
            f"invalid git subcommand: {command!r} — not available through this "
            "tool (read-only allowlist)"
        )
        if command in _FILE_READER_VERBS:
            msg = f"{msg}. {_file_reader_hint(command, args)}"
        raise ToolRefusedError(msg)
    if command == "branch":
        _reject_branch_writes(args)
    if command == "config":
        _reject_config_invocation(args)
    if command == "grep":
        _reject_grep_pager_exec(args)
    # Verbs that resolve long-option abbreviations: refuse every spelling of an
    # option that widens grep to untracked files, reads an unconfined file, or
    # runs a command, not only the full name.
    _reject_refused_long_options(args, subcommand=command)
    # Unconditional: --textconv / --ext-diff execute a git-config content
    # filter on every diff-family verb, not just the one #619 added (#623).
    _reject_content_filter_exec(global_opts)
    _reject_content_filter_exec(args)
    _reject_file_writing_flags(command, args)
    _reject_credential_path_operands(args, cwd=cwd, tmpdir=tmpdir, checkout_roots=checkout_roots)
    if command == "ls-remote":
        _validate_ls_remote_operand(args, cwd, tmpdir=tmpdir, checkout_roots=checkout_roots)
    _validate_positional_path_confinement(args, cwd)
    # Bind -C / --git-dir / --work-tree to a registered checkout, with relative
    # values resolved against the cwd git will run in (#257 / D7).
    _validate_path_confinement(global_opts, cwd, checkout_roots=checkout_roots)


def _repo_dir_for(ctx: ToolContext, repo: object) -> str:
    """Working directory for the optional ``repo`` argument of the read-only ``git`` tool.

    ``repo`` is ``name`` (same owner as the run) or ``owner/name`` and must be a
    checkout already registered in ``tool_state`` (primary, or via
    ``checkout_repo``); omitted means the primary checkout. An unknown repo is an
    error, never a silent fall-back to the primary checkout (#1258).
    """
    if repo is None or repo == "":
        return primary_repo_state(ctx.tool_state).dir
    if not isinstance(repo, str):
        msg = "repo must be a string"
        raise ValueError(msg)
    owner, _, name = repo.strip().rpartition("/")
    state = require_repo_state(ctx.tool_state, owner or ctx.repo.owner, name)
    return state.dir


def git_tool(ctx: ToolContext):
    # Only immutable revision/path resolutions are reusable. Symbolic refs must
    # still be resolved each time because they can move outside this tool.
    immutable_show_ids: dict[str, tuple[str, str]] = {}

    async def _run(params: dict[str, Any]):
        command = str(params["command"]).strip()
        args = list(params.get("args") or [])
        # Deliberate tolerance for agent callers: the reviewing agent is often
        # trained on `git <subcommand>` examples, so it may pass the redundant
        # `git ` prefix in `command` or repeat the subcommand as args[0]. Normalize
        # both instead of erroring, then validate the cleaned subcommand.
        had_git_prefix = command.lower().startswith("git ") or command.lower() == "git"
        if command.lower() == "git":
            command = ""
        elif command.lower().startswith("git "):
            command = command[len("git ") :].strip()
        # Only a command that arrived with a `git ` prefix (a full git
        # invocation string, e.g. `git -C /abs status`) is tokenized for
        # global-option extraction. A bare non-prefix multi-token command like
        # `rm -rf` must still be rejected as an invalid subcommand.
        cmd_tokens = command.split() if had_git_prefix and command else [command] if command else []
        # Pull any global git options (e.g. `-C <dir>`, `-c key=val`) out of
        # command/args and forward them before the subcommand, rather than
        # treating them as the subcommand or rejecting them as an
        # "invalid subcommand".
        subcommand, rest_args, global_opts = _extract_global_opts(cmd_tokens, args)
        command = subcommand
        args = rest_args
        if command and args and args[0].lower() == command.lower():
            # Agent redundantly repeated the subcommand as the first arg; honor
            # the call rather than rejecting it.
            args.pop(0)
        cwd = _repo_dir_for(ctx, params.get("repo"))
        tmpdir = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
        checkout_roots = [state.dir for state in ctx.tool_state.repos.values()]
        await run_blocking(
            _validate_git_invocation,
            command,
            args,
            global_opts,
            cwd,
            tmpdir=tmpdir,
            checkout_roots=checkout_roots,
        )
        show_target = _parse_show_rev_path(args) if command == "show" else None
        cache_key: str | None = None
        run_args = args
        if show_target is not None:
            immutable = (
                len(args) == 1
                and re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", show_target[0]) is not None
            )
            lookup = json.dumps([str(Path(cwd).resolve()), global_opts, args])
            identity = immutable_show_ids.get(lookup) if immutable else None
            if identity is None:
                try:
                    identity = await run_blocking(
                        _git_show_cache_identity, cwd=cwd, global_opts=global_opts, args=args
                    )
                except RuntimeError:
                    # Let git show report its own path/ref diagnostic. A cache
                    # optimization must not replace the command's semantics.
                    identity = None
                if immutable and identity is not None:
                    immutable_show_ids[lookup] = identity
            if identity is not None:
                cache_key, object_id = identity
                run_args = [object_id]
                cached_path = ctx.tool_state.git_show_cache.get(cache_key)
                if cached_path and Path(cached_path).is_file():
                    return {**_git_show_result(cached_path), "cached": True}
        context_dropped = False
        matched = True
        merge_base_found = True
        if command == "grep":
            args, context_dropped = _normalize_grep_args(args)
        try:
            if command == "grep":
                output, matched = await run_blocking(
                    _run_grep, [*global_opts, command, *args], cwd=cwd
                )
            elif command == "merge-base":
                output, merge_base_found = await run_blocking(
                    _run_merge_base, [*global_opts, command, *args], cwd=cwd
                )
            else:
                output = await run_blocking(_run_git, [*global_opts, command, *run_args], cwd=cwd)
        except RuntimeError as err:
            raise RuntimeError(redact_secrets(str(err))) from err
        if show_target is not None:
            path = _git_show_output_path(_export_dir(ctx), cache_key or uuid.uuid4().hex)
            Path(path).write_text(output, encoding="utf-8")
            if cache_key is not None:
                ctx.tool_state.git_show_cache[cache_key] = path
            return _git_show_result(path)
        result: dict[str, Any] = {"output": output}
        if len(output) > 50_000:
            path = str(_export_dir(ctx) / f"git-{command}-{uuid.uuid4().hex[:8]}.txt")
            Path(path).write_text(output, encoding="utf-8")
            preview, total, _ = _bounded_preview(
                output, max_lines=_GIT_OUTPUT_PREVIEW_LINES, saved_to=path
            )
            result = {
                "output": preview,
                "outputPath": path,
                "totalLines": total,
                "truncated": True,
            }
        if context_dropped:
            result["note"] = _GREP_CONTEXT_NOTE
        if not matched:
            # grep's no-match answer, surfaced honestly instead of as a
            # failure (#1077; the ``git``-door instance of #1027).
            result["noMatches"] = True
        if not merge_base_found:
            # merge-base's negative answer, same rule (#1077).
            if "--is-ancestor" in args:
                result["isAncestor"] = False
            else:
                result["noMergeBase"] = True
        return result

    return tool(
        name="git",
        tool_class=ToolClass.REPOSITORY_READ,
        description=(
            "Run a git subcommand. `command` is the subcommand ONLY. "
            "Use git_fetch to read remote refs; repository writes are not available."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
                "repo": {
                    "type": "string",
                    "description": (
                        "Registered checkout to run in: `name` or `owner/name`. "
                        "Defaults to the primary repo."
                    ),
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        execute=execute(_run, "git"),
        timeout_ms=120_000,
    )


def _fetch_count(params: dict[str, Any], key: str) -> int | None:
    """Return ``params[key]`` as a positive integer, or ``None`` when unset.

    Raises:
        ToolRefusedError: When the value is not a whole number of at least 1.
    """
    value = params.get(key)
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = f"Blocked: `{key}` must be a whole number of at least 1, got {value!r}."
        raise ToolRefusedError(msg)
    return value


def _is_shallow_repository(cwd: str) -> bool:
    """Report whether the repository at *cwd* is already a shallow clone."""
    out = _run_git(["rev-parse", "--is-shallow-repository"], cwd=cwd)
    return out.strip() == "true"


def git_fetch_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        cwd = primary_repo_state(ctx.tool_state).dir
        refspec = params.get("refspec")
        args = ["fetch", "--no-tags"]
        depth = _fetch_count(params, "depth")
        deepen = _fetch_count(params, "deepen")
        if depth is not None:
            if not _is_shallow_repository(cwd):
                msg = (
                    "Blocked: `depth` would truncate the history of a full clone; "
                    "it is only accepted on a repository that is already shallow. "
                    "Use `deepen` to fetch more history, or omit `depth`."
                )
                raise ToolRefusedError(msg)
            args.extend(["--depth", str(depth)])
        if deepen is not None:
            args.extend(["--deepen", str(deepen)])
        args.append("origin")
        if refspec:
            args.append(validate_fetch_refspec(str(refspec)))
        trusted = primary_repo_state(ctx.tool_state).push_url
        output = await run_blocking(
            _run_authenticated_git, args, cwd=cwd, token=ctx.git_token, trusted_remote_url=trusted
        )
        return {"success": True, "output": output}

    return tool(
        name="git_fetch",
        tool_class=ToolClass.REPOSITORY_READ,
        description=(
            "Fetch from the remote (handles authentication). `refspec` names one "
            "branch on origin, optionally stored as `<branch>:refs/remotes/origin/<branch>`."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "refspec": {"type": "string"},
                "depth": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Only accepted when the repository is already shallow.",
                },
                "deepen": {"type": "integer", "minimum": 1},
            },
            "additionalProperties": False,
        },
        execute=execute(_run, "git_fetch"),
    )
