"""Offline local diff review orchestration (no GitHub PR posting)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.shared import AgentRunContext
from mergecraft.config import load_repo_settings
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.server import start_mcp_http_server
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.utils.agent_resolve import resolve_model, resolve_runtime_agent
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.instructions import ResolvedInstructions
from mergecraft.utils.offline_diff import DiffMaterialization, materialize_diff, summarize_diff
from mergecraft.utils.skills import install_bundled_skills


@dataclass(slots=True)
class OfflineReviewResult:
    success: bool
    output: str | None = None
    error: str | None = None
    diff_path: str | None = None
    empty_diff: bool = False


def build_offline_review_prompt(
    *,
    diff_path: Path,
    base_ref: str | None,
    extra: str | None = None,
) -> str:
    """Build the user prompt for an offline Review-mode run."""
    summary = summarize_diff(diff_path.read_text(encoding="utf-8"))
    base_line = f"Base ref: `{base_ref}`\n" if base_ref else "Base ref: (provided diff file)\n"
    extra_block = (
        f"\n## Additional instructions\n\n{extra.strip()}\n" if extra and extra.strip() else ""
    )
    return (
        "You are running an **offline** local diff review (mergecraft diff-review).\n"
        "There is no GitHub pull request. Do **not** call `checkout_pr`, "
        "`create_pull_request_review`, `create_pull_request`, `push_branch`, "
        "`commit_changes`, or any other GitHub-mutating / push tool.\n\n"
        "1. Call `select_mode` with mode **Review**.\n"
        "2. Your first substantive action: **read** the authoritative unified diff at "
        f"`{diff_path}` end-to-end (start with any TOC / file headers). "
        "Do not re-derive the diff via `git diff` unless that file is empty/unreadable.\n"
        "3. Investigate the working tree with read-only tools only as needed.\n"
        "4. Produce a complete review body using the Review mode format "
        "(preamble + cross-cutting sections + optional nitpicks). "
        "Put the full markdown review in your final response and, if available, "
        "`set_output` with key `review`.\n"
        "5. Do not modify files, commit, or push.\n\n"
        f"{base_line}"
        f"Diff path: `{diff_path}`\n\n"
        f"## Diff summary\n\n{summary}\n"
        f"{extra_block}"
    )


async def run_offline_diff_review(
    *,
    cwd: Path,
    base: str | None = None,
    diff_file: Path | None = None,
    model: str | None = None,
    prompt_extra: str | None = None,
    dry_run: bool = False,
) -> OfflineReviewResult:
    """Materialize a local diff and optionally run the Review agent against it."""
    cwd = cwd.resolve()
    if not (cwd / ".git").exists() and diff_file is None:
        return OfflineReviewResult(
            success=False,
            error=f"not a git repository: {cwd} (pass --diff for a standalone patch file)",
        )

    out_dir = Path(tempfile.mkdtemp(prefix="mergecraft-diff-review-"))
    try:
        materialization = materialize_diff(cwd=cwd, out_dir=out_dir, base=base, diff_file=diff_file)
    except (OSError, RuntimeError) as exc:
        return OfflineReviewResult(success=False, error=str(exc))

    if materialization.empty:
        return OfflineReviewResult(
            success=True,
            output="no changes to review (empty diff).",
            diff_path=str(materialization.path),
            empty_diff=True,
        )

    prompt = build_offline_review_prompt(
        diff_path=materialization.path,
        base_ref=materialization.base_ref,
        extra=prompt_extra,
    )

    if dry_run:
        return OfflineReviewResult(
            success=True,
            output=prompt,
            diff_path=str(materialization.path),
            empty_diff=False,
        )

    return await _run_agent_review(
        cwd=cwd,
        materialization=materialization,
        prompt=prompt,
        model=model,
        tmpdir=out_dir,
    )


async def _run_agent_review(
    *,
    cwd: Path,
    materialization: DiffMaterialization,
    prompt: str,
    model: str | None,
    tmpdir: Path,
) -> OfflineReviewResult:
    stop_mcp = None
    github: GitHubClient | None = None
    try:
        # Offline: no GitHub token required. MCP GitHub tools will fail if called —
        # the prompt forbids them.
        github = GitHubClient(token="")
        tool_state = init_tool_state(owner="local", name=cwd.name, dir=str(cwd))
        resolved_model = resolve_model(slug=model)
        agent = resolve_runtime_agent(model=resolved_model)
        modes = compute_modes(agent.name, signed_commits=False)

        payload = ResolvedPayload(
            event=PayloadEvent(trigger="unknown", title="offline diff-review"),
            shell="disabled",
            push="disabled",
            model=model,
            cwd=str(cwd),
            prompt=prompt,
            generate_summary=False,
            status_checks=False,
        )
        settings = load_repo_settings(root=cwd, load_learnings_files=False)
        tool_context = ToolContext(
            agent_id=agent.name,
            repo=RepoIdentity(owner="local", name=cwd.name),
            payload=payload,
            github=github,
            github_installation_token="",
            git_token="",
            api_token="",
            modes=modes,
            tool_state=tool_state,
            mcp_server_url="",
            tmpdir=str(tmpdir),
            signed_commits=False,
            pr_approve_enabled=False,
            auto_merge_enabled=False,
            static_checks=[
                StaticCheckConfig(
                    name=check.name,
                    command=check.command,
                    suffixes=tuple(check.suffixes),
                )
                for check in settings.static_checks
            ],
            # Local run, operator's own tree and own config — no PR author in the loop.
            static_checks_enabled=True,
            analyzers_mode="auto",
            trust_tier="trusted",
            analyzers_settings_enabled=settings.analyzers.enabled,
        )

        mcp_url, stop_mcp = start_mcp_http_server(tool_context)
        tool_context.mcp_server_url = mcp_url
        skills_home = str(tmpdir / "home")
        Path(skills_home).mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(install_bundled_skills, home=skills_home)

        instructions = ResolvedInstructions(
            full=prompt,
            system="Offline mergecraft diff-review. Read-only. Do not post GitHub reviews or push.",
            user=prompt,
        )
        run_ctx = AgentRunContext(
            payload=payload,
            mcp_server_url=mcp_url,
            tmpdir=str(tmpdir),
            subagent_denied_tools=subagent_denied_tool_names(tool_context),
            instructions=instructions,
            tool_state=tool_state,
            api_token="",
            resolved_model=resolved_model,
        )

        logger.info("» offline diff-review via agent={}", agent.name)
        await agent.install()
        result = await agent.run(run_ctx)
        output = result.output or tool_state.output
        if not result.success:
            return OfflineReviewResult(
                success=False,
                output=output,
                error=result.error or "agent failed",
                diff_path=str(materialization.path),
            )
        return OfflineReviewResult(
            success=True,
            output=output,
            diff_path=str(materialization.path),
        )
    except Exception as exc:
        logger.exception("offline diff-review failed")
        return OfflineReviewResult(
            success=False,
            error=str(exc),
            diff_path=str(materialization.path),
        )
    finally:
        if stop_mcp is not None:
            stop_mcp()
        if github is not None:
            await github.aclose()
        if not os.environ.get("MERGECRAFT_KEEP_TMP"):
            logger.debug("offline review artifacts retained at {}", tmpdir)
