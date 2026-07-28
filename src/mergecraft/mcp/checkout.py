"""checkout_pr tool — fetch PR branch and write formatted diff."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.mcp.git import _git_env, _run_git
from mergecraft.mcp.shared import execute, tool
from mergecraft.mcp.tool_state import StoredPushDest, primary_repo_state

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def ensure_local_base_branch_alias(*, cwd: str, base_ref: str) -> None:
    """Create ``refs/heads/<base_ref>`` pointing at ``origin/<base_ref>``.

    Agents often run ``git show <base_ref>:path`` using the bare PR base branch
    name (e.g. ``pre-0.0.1``). ``checkout_pr`` already fetches
    ``refs/remotes/origin/<base_ref>``; this local alias makes bare-name rev
    syntax work in shallow GHA checkouts too.
    """
    if not base_ref:
        return
    try:
        _run_git(["rev-parse", "--verify", f"{base_ref}^{{commit}}"], cwd=cwd)
        return
    except RuntimeError:
        pass
    _run_git(["branch", "-f", base_ref, f"origin/{base_ref}"], cwd=cwd)


def checkout_pr_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        pull_number = int(params["pull_number"])
        state = primary_repo_state(ctx.tool_state)
        cwd = state.dir

        dirty = _run_git(["status", "--porcelain"], cwd=cwd).strip()
        if dirty:
            msg = (
                f"cannot checkout PR #{pull_number} while the working tree has "
                f"uncommitted changes. dirty paths:\n{dirty}"
            )
            raise RuntimeError(msg)

        pr = await ctx.github.get_pull(ctx.repo.owner, ctx.repo.name, pull_number)
        head = pr.get("head") or {}
        base = pr.get("base") or {}
        head_ref = head.get("ref") or ""
        head_sha = head.get("sha") or ""
        base_ref = base.get("ref") or ""
        is_fork = (head.get("repo") or {}).get("full_name") != (
            (base.get("repo") or {}).get("full_name")
        )
        local_branch = f"pr-{pull_number}"

        # Fetch PR head via GitHub's pull/<n>/head ref
        _run_git(
            ["fetch", "--no-tags", "origin", f"pull/{pull_number}/head:{local_branch}"],
            cwd=cwd,
            env=_git_env(ctx.git_token),
        )
        _run_git(["checkout", local_branch], cwd=cwd)
        # Ensure base is available for merge-base diffs
        try:
            _run_git(
                [
                    "fetch",
                    "--no-tags",
                    "--depth=1000",
                    "origin",
                    f"{base_ref}:refs/remotes/origin/{base_ref}",
                ],
                cwd=cwd,
                env=_git_env(ctx.git_token),
            )
        except Exception as err:
            logger.info("base fetch soft-failed: {}", err)
        if base_ref:
            try:
                ensure_local_base_branch_alias(cwd=cwd, base_ref=base_ref)
            except Exception as err:
                logger.info("base branch alias soft-failed: {}", err)

        state.issue_number = pull_number
        state.checkout_sha = head_sha or _run_git(["rev-parse", "HEAD"], cwd=cwd).strip()
        state.push_dest = StoredPushDest(
            remote_name="origin",
            remote_branch=head_ref,
            local_branch=local_branch,
        )
        if is_fork and head.get("repo"):
            clone_url = (head["repo"].get("clone_url") or "").rstrip("/")
            state.push_url = clone_url if clone_url.endswith(".git") else f"{clone_url}.git"
        else:
            state.push_url = f"https://github.com/{ctx.repo.owner}/{ctx.repo.name}.git"

        # Write a basic diff file for reviewers
        temp = os.environ.get("MERGECRAFT_TEMP_DIR") or ctx.tmpdir
        diff_path = str(Path(temp) / f"pr-{pull_number}.diff")
        try:
            diff = _run_git(
                ["diff", "--merge-base", f"origin/{base_ref}", "HEAD"],
                cwd=cwd,
            )
        except Exception:
            files = await ctx.github.get(
                f"/repos/{ctx.repo.owner}/{ctx.repo.name}/pulls/{pull_number}/files"
            )
            parts: list[str] = []
            for f in files or []:
                parts.append(f"diff --git a/{f.get('filename')} b/{f.get('filename')}\n")
                if f.get("patch"):
                    parts.append(f.get("patch") + "\n")
            diff = "".join(parts)
        Path(diff_path).write_text(diff, encoding="utf-8")

        logger.info("checked out PR #{} -> {}", pull_number, local_branch)
        return {
            "pullNumber": pull_number,
            "localBranch": local_branch,
            "remoteBranch": head_ref,
            "base": base_ref,
            "headSha": state.checkout_sha,
            "isFork": is_fork,
            "diffPath": diff_path,
            "title": pr.get("title"),
            "url": pr.get("html_url"),
        }

    return tool(
        name="checkout_pr",
        mutates=True,
        timeout_ms=600_000,
        description=(
            "Checkout a pull request branch locally. Returns diffPath pointing to the "
            "formatted diff file."
        ),
        input_schema={
            "type": "object",
            "properties": {"pull_number": {"type": "number"}},
            "required": ["pull_number"],
            "additionalProperties": False,
        },
        execute=execute(_run, "checkout_pr"),
    )
