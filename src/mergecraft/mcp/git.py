"""Git MCP tools: git, git_fetch, push_branch, push_tags, delete_branch, commit_changes."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
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
    _split_end_of_options,
    _subcommand_declares_shorts,
    reject_if_leading_dash,
    reject_special_ref,
    validate_tag_name,
)
from mergecraft.mcp.shared import ToolClass, execute, repository_mutation_class_for_push, tool
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.utils.git_hardening import git_argv, git_authenticated_argv, read_remote_origin_url

if TYPE_CHECKING:
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
        raise ValueError(msg) from exc


def _validate_path_confinement(global_opts: list[str], cwd: str) -> None:
    """Confine -C / --git-dir / --work-tree in *global_opts* to an allowed root.

    git applies successive ``-C`` options **cumulatively** and resolves each
    relative to the previous one, so the walk carries the accumulated directory
    forward rather than validating every value against the starting cwd — which
    would accept a pair whose combined effect escapes.
    """
    current = cwd
    idx = 0
    while idx < len(global_opts):
        tok = global_opts[idx]
        if tok == "-C":
            if idx + 1 < len(global_opts):
                current = str(_confine_to_repo_root(global_opts[idx + 1], "-C", current))
            idx += 2
        elif tok in {"--git-dir", "--work-tree"}:
            if idx + 1 < len(global_opts):
                _confine_to_repo_root(global_opts[idx + 1], tok, current)
            idx += 2
        elif tok.startswith(("--git-dir=", "--work-tree=")):
            flag, _, value = tok.partition("=")
            _confine_to_repo_root(value, flag, current)
            idx += 1
        else:
            idx += 1


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
_GIT_SHOW_PREVIEW_LINES = 5


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


def _git_show_cache_key(rev: str, path: str) -> str:
    return f"{rev}\0{path}"


def _git_show_output_path(temp: str, rev: str, path: str) -> str:
    digest = hashlib.sha256(_git_show_cache_key(rev, path).encode()).hexdigest()[:16]
    return str(Path(temp) / f"git-show-{digest}.txt")


def _git_show_preview(output_path: str) -> str:
    text = Path(output_path).read_text(encoding="utf-8")
    lines = text.splitlines()
    preview = "\n".join(lines[:_GIT_SHOW_PREVIEW_LINES])
    if len(lines) > _GIT_SHOW_PREVIEW_LINES:
        preview = f"{preview}\n... [truncated; full body saved to {output_path}] ..."
    return preview


def _is_auth_failure(stderr: str) -> bool:
    """Return whether git's failure output shows a rejected/absent credential."""
    lowered = stderr.lower()
    return any(marker in lowered for marker in _AUTH_FAILURE_MARKERS)


def _run_git(
    args: list[str],
    *,
    cwd: str,
    env: dict[str, str] | None = None,
    remote_url: str | None = None,
) -> str:
    resolved_env = env or os.environ.copy()
    if env is not None and env.get("GIT_CONFIG_COUNT"):
        resolved_remote = remote_url or _origin_remote_url(cwd)
        argv = git_authenticated_argv(args, remote_url=resolved_remote)
    else:
        argv = git_argv(args)
    result = subprocess.run(
        argv,
        cwd=cwd,
        env=resolved_env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        raw_err = (result.stderr or result.stdout or "").strip()
        err = redact_secrets(raw_err)
        msg = f"git {' '.join(args)} failed ({result.returncode}): {err}"
        if _is_auth_failure(raw_err):
            logger.error("git auth failure on `git {}`: {}", " ".join(args), err)
            msg = f"{msg}\n{_AUTH_FAILURE_HINT}"
        raise RuntimeError(msg)
    return result.stdout


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
    command: str, args: list[str], global_opts: list[str], cwd: str, *, tmpdir: str = ""
) -> None:
    """Run every guard a normalized git invocation must pass, in order.

    The order is the contract, which is why it lives in one function rather than
    as a comment over six sequential calls: the config-flag and ``--namespace``
    refusals come first because they apply whatever the verb is, the redirect
    precedes the allowlist so a rejected verb names its dedicated tool instead
    of producing a generic "invalid subcommand", and path confinement runs last
    because it needs the cwd git will actually run in.

    Raises:
        RuntimeError: when the verb has a dedicated tool to redirect to.
        ValueError: for every other refusal.
    """
    # Unconditional: -c / --config-env are alias-execution vectors (#257 / D7).
    # global_opts is scanned with no subcommand — the pre-subcommand slot has no
    # verb to scope short flags against, so the strict reading applies there.
    _reject_config_flags(global_opts)
    _reject_config_flags(args, subcommand=command)
    _reject_no_index(global_opts)
    _reject_no_index(args)
    # Unconditional: --namespace reaches the same pre-subcommand slot and is
    # the one extracted global option no path rule can confine.
    _reject_namespace_flag(global_opts)
    _reject_namespace_flag(args)
    redirect = _REDIRECT_TO_TOOL.get(command)
    if redirect:
        msg = f"git {command} is not available through this tool — {redirect}"
        raise RuntimeError(msg)
    # Read-only allowlist: replace the old format-only _SUBCOMMAND_RE (#257 / D7).
    if not command or command not in _READONLY_SUBCOMMANDS:
        msg = (
            f"invalid git subcommand: {command!r} — not available through this "
            "tool (read-only allowlist)"
        )
        raise ValueError(msg)
    if command == "branch":
        _reject_branch_writes(args)
    if command == "config":
        _reject_config_invocation(args)
    if command == "grep":
        _reject_grep_pager_exec(args)
    # Unconditional: --textconv / --ext-diff execute a git-config content
    # filter on every diff-family verb, not just the one #619 added (#623).
    _reject_content_filter_exec(global_opts)
    _reject_content_filter_exec(args)
    _reject_file_writing_flags(command, args)
    _reject_credential_path_operands(args, cwd=cwd, tmpdir=tmpdir)
    _validate_positional_path_confinement(args, cwd)
    # Confine -C / --git-dir / --work-tree to an allowed workspace root, with
    # relative values resolved against the cwd git will run in (#257 / D7).
    _validate_path_confinement(global_opts, cwd)


def git_tool(ctx: ToolContext):
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
        cwd = primary_repo_state(ctx.tool_state).dir
        tmpdir = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
        _validate_git_invocation(command, args, global_opts, cwd, tmpdir=tmpdir)
        show_target = _parse_show_rev_path(args) if command == "show" else None
        if show_target is not None:
            rev, file_path = show_target
            cache_key = _git_show_cache_key(rev, file_path)
            cached_path = ctx.tool_state.git_show_cache.get(cache_key)
            if cached_path and Path(cached_path).is_file():
                return {
                    "output": _git_show_preview(cached_path),
                    "outputPath": cached_path,
                    "cached": True,
                }
        try:
            output = _run_git([*global_opts, command, *args], cwd=cwd)
        except RuntimeError as err:
            raise RuntimeError(redact_secrets(str(err))) from err
        if show_target is not None:
            rev, file_path = show_target
            cache_key = _git_show_cache_key(rev, file_path)
            temp = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
            path = _git_show_output_path(temp, rev, file_path)
            Path(path).write_text(output, encoding="utf-8")
            ctx.tool_state.git_show_cache[cache_key] = path
            return {
                "output": _git_show_preview(path),
                "outputPath": path,
            }
        if len(output) > 50_000:
            temp = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
            path = str(Path(temp) / f"git-{command}-{uuid.uuid4().hex[:8]}.txt")
            Path(path).write_text(output, encoding="utf-8")
            preview = "\n".join(output.splitlines()[:40])
            return {
                "output": (f"{preview}\n\n... [output truncated; full body saved to {path}] ..."),
                "outputPath": path,
            }
        return {"output": output}

    return tool(
        name="git",
        tool_class=ToolClass.REPOSITORY_READ,
        description=(
            "Run a git subcommand. `command` is the subcommand ONLY. "
            "For push/fetch use push_branch / git_fetch."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
                "repo": {"type": "string"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        execute=execute(_run, "git"),
    )


def git_fetch_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        cwd = primary_repo_state(ctx.tool_state).dir
        refspec = params.get("refspec")
        args = ["fetch", "--no-tags"]
        if params.get("depth"):
            args.extend(["--depth", str(params["depth"])])
        if params.get("deepen"):
            args.extend(["--deepen", str(params["deepen"])])
        args.append("origin")
        if refspec:
            reject_special_ref(str(refspec).split(":")[0], "refspec")
            args.append(str(refspec))
        trusted = primary_repo_state(ctx.tool_state).push_url
        output = _run_authenticated_git(
            args, cwd=cwd, token=ctx.git_token, trusted_remote_url=trusted
        )
        return {"success": True, "output": output}

    return tool(
        name="git_fetch",
        tool_class=ToolClass.REPOSITORY_READ,
        description="Fetch from the remote (handles authentication).",
        input_schema={
            "type": "object",
            "properties": {
                "refspec": {"type": "string"},
                "depth": {"type": "number"},
                "deepen": {"type": "number"},
                "repo": {"type": "string"},
            },
            "additionalProperties": False,
        },
        execute=execute(_run, "git_fetch"),
    )


def _require_push_allowed(
    ctx: ToolContext,
    *,
    branch: str | None,
    action: str,
) -> None:
    """Enforce ``push`` disabled / restricted-default-branch policy (W2 / Final)."""
    if ctx.payload.push == "disabled":
        msg = "push is disabled for this run"
        raise RuntimeError(msg)
    state = primary_repo_state(ctx.tool_state)
    if (
        ctx.payload.push == "restricted"
        and branch
        and state.default_branch
        and branch == state.default_branch
    ):
        verb = {
            "push": "push to",
            "delete": "delete",
            "update": "update",
            "tag": "push tags affecting",
        }.get(action, "mutate")
        msg = (
            f"Push blocked: cannot {verb} default branch "
            f"'{state.default_branch}' in restricted mode"
        )
        raise RuntimeError(msg)


def push_branch_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        cwd = primary_repo_state(ctx.tool_state).dir
        branch = params.get("branchName")
        if not branch:
            branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).strip()
        reject_special_ref(str(branch), "branch")
        _require_push_allowed(ctx, branch=str(branch), action="push")
        force = bool(params.get("force", False))
        args = ["push", "origin", str(branch)]
        if force:
            args.insert(1, "--force-with-lease")
        trusted = primary_repo_state(ctx.tool_state).push_url
        output = _run_authenticated_git(
            args, cwd=cwd, token=ctx.git_token, trusted_remote_url=trusted
        )
        logger.info("pushed branch {}", branch)
        return {"success": True, "branch": branch, "output": output}

    repo_class = repository_mutation_class_for_push(ctx.payload.push)
    return tool(
        name="push_branch",
        tool_class=repo_class,
        mutates=True,
        description="Push a branch to the remote (handles authentication).",
        input_schema={
            "type": "object",
            "properties": {
                "branchName": {"type": "string"},
                "force": {"type": "boolean"},
                "repo": {"type": "string"},
            },
            "additionalProperties": False,
        },
        execute=execute(_run, "push_branch"),
    )


def push_tags_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        _require_push_allowed(ctx, branch=None, action="tag")
        cwd = primary_repo_state(ctx.tool_state).dir
        tags = list(params.get("tags") or [])
        if not tags:
            msg = "tags array is required"
            raise ValueError(msg)
        for tag in tags:
            validate_tag_name(str(tag))
        refspecs = [f"refs/tags/{tag}" for tag in tags]
        trusted = primary_repo_state(ctx.tool_state).push_url
        output = _run_authenticated_git(
            ["push", "origin", *refspecs],
            cwd=cwd,
            token=ctx.git_token,
            trusted_remote_url=trusted,
        )
        return {"success": True, "tags": tags, "output": output}

    repo_class = repository_mutation_class_for_push(ctx.payload.push)
    return tool(
        name="push_tags",
        tool_class=repo_class,
        mutates=True,
        description="Push one or more tags to the remote.",
        input_schema={
            "type": "object",
            "properties": {
                "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "repo": {"type": "string"},
            },
            "required": ["tags"],
            "additionalProperties": False,
        },
        execute=execute(_run, "push_tags"),
    )


def delete_branch_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        branch = str(params["branchName"])
        reject_special_ref(branch, "branch")
        cwd = primary_repo_state(ctx.tool_state).dir
        remote = bool(params.get("remote", False))
        if remote:
            _require_push_allowed(ctx, branch=branch, action="delete")
            trusted = primary_repo_state(ctx.tool_state).push_url
            output = _run_authenticated_git(
                ["push", "origin", "--delete", branch],
                cwd=cwd,
                token=ctx.git_token,
                trusted_remote_url=trusted,
            )
        else:
            output = _run_git(["branch", "-D", branch], cwd=cwd)
        return {"success": True, "branch": branch, "remote": remote, "output": output}

    repo_class = repository_mutation_class_for_push(ctx.payload.push)
    return tool(
        name="delete_branch",
        tool_class=repo_class,
        mutates=True,
        description="Delete a local or remote branch.",
        input_schema={
            "type": "object",
            "properties": {
                "branchName": {"type": "string"},
                "remote": {"type": "boolean"},
                "repo": {"type": "string"},
            },
            "required": ["branchName"],
            "additionalProperties": False,
        },
        execute=execute(_run, "delete_branch"),
    )


def commit_changes_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        message = str(params["message"])
        cwd = primary_repo_state(ctx.tool_state).dir
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).strip()
        # Local commit is always allowed; push policy gates only the remote ref
        # update (W4.2 — same local-vs-remote split as ``delete_branch``).
        status = _run_git(["status", "--porcelain"], cwd=cwd)
        if not status.strip():
            return {
                "success": True,
                "skipped": True,
                "pushed": False,
                "reason": "nothing to commit",
            }
        _run_git(["add", "-A"], cwd=cwd)
        _run_git(["commit", "-m", message], cwd=cwd)
        sha = _run_git(["rev-parse", "HEAD"], cwd=cwd).strip()
        # The commit is local either way — the push policy decides nothing about
        # the response, it only records why no remote update was attempted.
        try:
            _require_push_allowed(ctx, branch=branch, action="update")
        except RuntimeError as err:
            logger.info("API ref update skipped (push policy): {}", err)
        return {"success": True, "sha": sha, "branch": branch, "message": message, "pushed": False}

    repo_class = repository_mutation_class_for_push(ctx.payload.push)
    return tool(
        name="commit_changes",
        tool_class=repo_class,
        mutates=True,
        description=(
            "Commit working-tree changes as a local commit (no push, no remote ref update)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "repo": {"type": "string"},
            },
            "required": ["message"],
            "additionalProperties": False,
        },
        execute=execute(_run, "commit_changes"),
    )
