"""Cross-repo list_repos / checkout_repo tools."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.git import _git_env, _run_git
from mergecraft.mcp.shared import EMPTY_SCHEMA, ToolClass, execute, tool
from mergecraft.mcp.tool_state import RepoAccess, ensure_repo_state, repo_key
from mergecraft.utils.git_setup import scrub_clone_credentials
from mergecraft.utils.workspace import register_workspace_root

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def _assert_valid_repo_name(name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name.startswith("-") or ".." in name:
        msg = f'invalid repo name "{name}" — expected a bare repo name (no owner, no slashes)'
        raise ValueError(msg)


def _eq_name(a: str, b: str) -> bool:
    return a.lower() == b.lower()


def _access_for(ctx: ToolContext, name: str) -> RepoAccess:
    if _eq_name(name, ctx.repo.name):
        return "primary"
    if ctx.xrepo and any(_eq_name(w, name) for w in ctx.xrepo.write):
        return "write"
    return "read"


def list_repos_tool(ctx: ToolContext):
    async def _run(_params: dict[str, Any]):
        if not ctx.xrepo:
            return {
                "repos": [],
                "note": "this run is single-repo; cross-repo (--xrepo) was not requested.",
            }
        repos = [
            {
                "owner": ctx.repo.owner,
                "name": name,
                "access": _access_for(ctx, name),
                "checkedOut": repo_key(ctx.repo.owner, name) in ctx.tool_state.repos,
            }
            for name in ctx.xrepo.read
        ]
        unavailable = ctx.xrepo.unavailable or []
        result: dict[str, Any] = {"repos": repos, "count": len(repos)}
        if unavailable:
            result["unavailable"] = unavailable
            result["note"] = (
                "requested but not granted (unknown repo, different owner, or you "
                f"lack access): {', '.join(unavailable)}"
            )
        return result

    return tool(
        name="list_repos",
        tool_class=ToolClass.SCOPE,
        annotations={"readOnlyHint": True},
        description=("List repositories available for cross-repo (--xrepo) work in this run."),
        input_schema=EMPTY_SCHEMA,
        execute=execute(_run, "list_repos"),
    )


def checkout_repo_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        if not ctx.xrepo:
            msg = "cross-repo is not enabled for this run (no --xrepo)."
            raise RuntimeError(msg)
        repo = str(params["repo"])
        _assert_valid_repo_name(repo)
        owner = ctx.repo.owner
        if _eq_name(repo, ctx.repo.name):
            from mergecraft.mcp.tool_state import primary_repo_state

            return {
                "path": primary_repo_state(ctx.tool_state).dir,
                "access": "primary",
                "note": "primary repo is already checked out at the working directory.",
            }
        if not any(_eq_name(r, repo) for r in ctx.xrepo.read):
            msg = (
                f'repo "{repo}" is not in this run\'s cross-repo access set. '
                "call list_repos to see what's available."
            )
            raise RuntimeError(msg)
        existing = ctx.tool_state.repos.get(repo_key(owner, repo))
        if existing:
            return {
                "path": existing.dir,
                "access": existing.access,
                "note": "already checked out.",
            }
        access = _access_for(ctx, repo)
        dir_path = Path(ctx.tmpdir) / "xrepo" / repo
        dir_path.mkdir(parents=True, exist_ok=True)
        register_workspace_root(str(dir_path))
        state = ensure_repo_state(
            ctx.tool_state,
            owner=owner,
            name=repo,
            dir=str(dir_path),
            access=access,
        )
        try:
            info = await ctx.scm.get_repo(owner, repo)
            default_branch = info["default_branch"]
            state.default_branch = default_branch
            url = f"https://github.com/{owner}/{repo}.git"
            _run_git(["init", "-q"], cwd=str(dir_path))
            _run_git(["remote", "add", "origin", url], cwd=str(dir_path))
            token = ctx.read_token if access == "read" else ctx.git_token
            _run_git(
                [
                    "-c",
                    "http.followRedirects=false",
                    "fetch",
                    "--depth=1",
                    "--no-tags",
                    "--no-recurse-submodules",
                    "origin",
                    default_branch,
                ],
                cwd=str(dir_path),
                env=_git_env(token or ctx.git_token),
            )
            _run_git(
                ["checkout", "-B", default_branch, "FETCH_HEAD"],
                cwd=str(dir_path),
            )
            scrub_clone_credentials(dir_path)
            state.push_url = url
            logger.info(
                "checked out secondary repo {}/{} ({}) → {}",
                owner,
                repo,
                access,
                dir_path,
            )
            return {
                "path": str(dir_path),
                "access": access,
                "defaultBranch": default_branch,
            }
        except Exception:
            if dir_path.exists():
                scrub_clone_credentials(dir_path)
            ctx.tool_state.repos.pop(repo_key(owner, repo), None)
            shutil.rmtree(dir_path, ignore_errors=True)
            raise

    return tool(
        name="checkout_repo",
        tool_class=ToolClass.SCOPE,
        description=(
            "Clone a secondary repository into a temporary working tree and return "
            "its absolute path."
        ),
        input_schema={
            "type": "object",
            "properties": {"repo": {"type": "string"}},
            "required": ["repo"],
            "additionalProperties": False,
        },
        execute=execute(_run, "checkout_repo"),
    )
