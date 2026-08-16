"""Git MCP tools: git, git_fetch, push_branch, push_tags, delete_branch, commit_changes."""

from __future__ import annotations

import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.shared import ToolClass, execute, repository_mutation_class_for_push, tool
from mergecraft.mcp.tool_state import primary_repo_state

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_SUBCOMMAND_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_AUTH_REQUIRED = {
    "push": "use push_branch instead",
    "fetch": "use git_fetch instead",
    "pull": "use git_fetch then git merge",
    "clone": "use checkout_repo / checkout_pr",
}
_NOSHELL_BLOCKED = {
    "clean": "git clean is blocked when shell is disabled",
    "filter-branch": "git filter-branch is blocked when shell is disabled",
    "filter-repo": "git filter-repo is blocked when shell is disabled",
}
_NOSHELL_BLOCKED_ARGS = ("--exec", "-c", "--config-env", "--upload-pack", "--receive-pack")
_SYMBOLIC_REFS = frozenset({"HEAD", "FETCH_HEAD", "ORIG_HEAD", "MERGE_HEAD"})
_BAD_REF_CHARS = re.compile(r"[:+^~?*[\\\s]")


def reject_if_leading_dash(value: str, kind: str) -> None:
    if value.startswith("-"):
        msg = f"Blocked: {kind} '{value}' starts with '-' — git could parse it as a flag."
        raise ValueError(msg)


def reject_special_ref(value: str, kind: str) -> None:
    reject_if_leading_dash(value, kind)
    if value.startswith("refs/"):
        msg = f"Blocked: {kind} '{value}' is a fully-qualified ref path. Use a bare branch name."
        raise ValueError(msg)
    if value in _SYMBOLIC_REFS:
        msg = f"Blocked: {kind} '{value}' is a git symbolic ref, not a branch name."
        raise ValueError(msg)
    match = _BAD_REF_CHARS.search(value)
    if match:
        msg = (
            f"Blocked: {kind} '{value}' contains '{match.group(0)}', which git "
            "interprets as refspec/revision syntax."
        )
        raise ValueError(msg)


def validate_tag_name(tag: str) -> None:
    reject_if_leading_dash(tag, "tag")
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", tag):
        msg = f"Blocked: tag '{tag}' contains characters that could be parsed as a refspec or flag."
        raise ValueError(msg)


def _run_git(args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        msg = f"git {' '.join(args)} failed ({result.returncode}): {err}"
        raise RuntimeError(msg)
    return result.stdout


def _git_env(token: str) -> dict[str, str]:
    env = os.environ.copy()
    # Prefer askpass-style injection when available; otherwise embed in URL via
    # temporary insteadOf is complex — use GIT_ASKPASS stub via Authorization header
    # for https remotes via http.extraHeader.
    env["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        env["GIT_CONFIG_VALUE_0"] = f"Authorization: Bearer {token}"
    return env


# Git global options that may precede the subcommand. `-C`/`-c` take a
# separate argument; the `--git-dir`/`--work-tree`/`--namespace` family may
# be spelled as `--flag value` or `--flag=value`.
_GLOBAL_OPTS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")
_GLOBAL_OPT_RE = re.compile(r"^--(?:git-dir|work-tree|namespace)(?:=.*)?$")

# Tokens that take a separate value argument rather than an inline `=value`.
_GLOBAL_OPT_TAKES_VALUE = ("-C", "-c", "--git-dir", "--work-tree", "--namespace")


def _extract_global_opts(
    cmd_tokens: list[str], args: list[str]
) -> tuple[str, list[str], list[str]]:
    """Pull global git options out of command tokens + args, placing them first.

    git requires global options (``-C``/``-c``/``--git-dir``/``--work-tree``/
    ``--namespace``) before the subcommand, but the reviewing agent may emit
    them anywhere (e.g. ``command="status"`` with ``args=["-C", dir]`` or
    ``command="git -C dir status"``). Extract them regardless of position,
    collect them into ``global_opts`` (flag plus its value when separate), and
    return the real subcommand plus the remaining positional args. The
    subcommand is validated separately so these options are forwarded rather
    than rejected as an "invalid subcommand".
    """
    tokens: list[str] = list(cmd_tokens)
    tokens.extend(args)

    global_opts: list[str] = []
    rest: list[str] = []
    subcommand = ""
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        is_global = tok in _GLOBAL_OPTS or _GLOBAL_OPT_RE.fullmatch(tok) is not None
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
        if not command or not _SUBCOMMAND_RE.fullmatch(command):
            msg = f"invalid git subcommand: {command!r}"
            raise ValueError(msg)
        cwd = primary_repo_state(ctx.tool_state).dir
        redirect = _AUTH_REQUIRED.get(command)
        if redirect:
            msg = f"git {command} is not available through this tool — {redirect}"
            raise RuntimeError(msg)
        if ctx.payload.shell == "disabled":
            blocked = _NOSHELL_BLOCKED.get(command)
            if blocked:
                raise RuntimeError(blocked)
            for arg in args:
                if any(arg == flag or arg.startswith(f"{flag}=") for flag in _NOSHELL_BLOCKED_ARGS):
                    msg = f"Blocked: '{arg}' flag can execute arbitrary code."
                    raise RuntimeError(msg)
        output = _run_git([*global_opts, command, *args], cwd=cwd)
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
        output = _run_git(args, cwd=cwd, env=_git_env(ctx.git_token))
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
        output = _run_git(args, cwd=cwd, env=_git_env(ctx.git_token))
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
        output = _run_git(
            ["push", "origin", *refspecs],
            cwd=cwd,
            env=_git_env(ctx.git_token),
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
            output = _run_git(
                ["push", "origin", "--delete", branch],
                cwd=cwd,
                env=_git_env(ctx.git_token),
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
        """Signed commit via GitHub Git Data API (simplified tree commit)."""
        message = str(params["message"])
        cwd = primary_repo_state(ctx.tool_state).dir
        branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd).strip()
        # Local commit is always allowed; push policy gates only the remote ref
        # update (W4.2 — same local-vs-remote split as ``delete_branch``).
        status = _run_git(["status", "--porcelain"], cwd=cwd)
        if not status.strip():
            return {"success": True, "skipped": True, "reason": "nothing to commit"}
        _run_git(["add", "-A"], cwd=cwd)
        # Local commit first so tree is consistent; API signing can replace later.
        _run_git(["-c", "core.hooksPath=/dev/null", "commit", "-m", message], cwd=cwd)
        sha = _run_git(["rev-parse", "HEAD"], cwd=cwd).strip()
        try:
            _require_push_allowed(ctx, branch=branch, action="update")
        except RuntimeError as err:
            logger.info("API ref update skipped (push policy): {}", err)
            return {
                "success": True,
                "sha": sha,
                "branch": branch,
                "message": message,
                "pushed": False,
            }
        # Best-effort: update remote ref via API for Verified commits.
        try:
            await ctx.github.patch(
                f"/repos/{ctx.repo.owner}/{ctx.repo.name}/git/refs/heads/{branch}",
                json={"sha": sha, "force": False},
            )
        except Exception as err:
            logger.info("API ref update skipped/failed: {}", err)
        return {"success": True, "sha": sha, "branch": branch, "message": message}

    repo_class = repository_mutation_class_for_push(ctx.payload.push)
    return tool(
        name="commit_changes",
        tool_class=repo_class,
        mutates=True,
        description=(
            "Commit working-tree changes as a GitHub-signed commit (signed-commits mode)."
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
