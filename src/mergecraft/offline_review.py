"""Offline local diff review orchestration (no GitHub PR posting)."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import ValidationError

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.shared import AgentRunContext
from mergecraft.analyzers.finding import Finding
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
    structured_output: str | None = None


def findings_output_schema() -> dict[str, Any]:
    """JSON Schema for structured findings output derived from ``Finding``."""
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": Finding.model_json_schema(),
            }
        },
        "required": ["findings"],
    }


def build_offline_review_prompt(
    *,
    diff_path: Path,
    base_ref: str | None,
    extra: str | None = None,
    json_mode: bool = False,
) -> str:
    """Build the user prompt for an offline Review-mode run."""
    summary = summarize_diff(diff_path.read_text(encoding="utf-8"))
    base_line = f"Base ref: `{base_ref}`\n" if base_ref else "Base ref: (provided diff file)\n"
    extra_block = (
        f"\n## Additional instructions\n\n{extra.strip()}\n" if extra and extra.strip() else ""
    )
    if json_mode:
        step_four = (
            "4. Call `set_output` with structured findings — **required**. Each item must "
            "conform to the schema exposed by the set_output tool. You may also put a "
            "complete markdown review in your final response (preamble + cross-cutting "
            "sections + optional nitpicks).\n"
        )
    else:
        step_four = (
            "4. Produce a complete review body using the Review mode format "
            "(preamble + cross-cutting sections + optional nitpicks). "
            "Put the full markdown review in your final response and, if available, "
            "`set_output` with key `review`.\n"
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
        "   When `run_analyzers` is available, call it with the diff's changed paths and "
        f"`diff_path: {diff_path}` before drafting findings; use `analyzer_findings` for "
        "placement and dispatch `mergecraft-verifier` for Critical/Major analyzer hits.\n"
        f"{step_four}"
        "5. Do not modify files, commit, or push.\n\n"
        f"{base_line}"
        f"Diff path: `{diff_path}`\n\n"
        f"## Diff summary\n\n{summary}\n"
        f"{extra_block}"
    )


def _parse_and_validate_findings(raw: str) -> list[dict[str, Any]]:
    """Parse structured output JSON and validate each finding."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"invalid JSON in set_output: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(data, dict):
        msg = "set_output must be a JSON object with a findings array"
        raise ValueError(msg)
    findings_raw = data.get("findings")
    if not isinstance(findings_raw, list):
        msg = "set_output must contain a findings array"
        raise ValueError(msg)
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(findings_raw):
        try:
            validated.append(Finding.model_validate(item).model_dump())
        except ValidationError as exc:
            msg = f"finding[{index}] does not conform to Finding schema: {exc}"
            raise ValueError(msg) from exc
    return validated


def _write_findings_json(json_path: Path, findings: list[dict[str, Any]]) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"findings": findings}, indent=2, ensure_ascii=False)
    json_path.write_text(f"{payload}\n", encoding="utf-8")


async def run_offline_diff_review(
    *,
    cwd: Path,
    base: str | None = None,
    diff_file: Path | None = None,
    model: str | None = None,
    prompt_extra: str | None = None,
    dry_run: bool = False,
    json_path: Path | None = None,
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

    json_mode = json_path is not None
    prompt = build_offline_review_prompt(
        diff_path=materialization.path,
        base_ref=materialization.base_ref,
        extra=prompt_extra,
        json_mode=json_mode,
    )

    if dry_run:
        return OfflineReviewResult(
            success=True,
            output=prompt,
            diff_path=str(materialization.path),
            empty_diff=False,
        )

    result = await _run_agent_review(
        cwd=cwd,
        materialization=materialization,
        prompt=prompt,
        model=model,
        tmpdir=out_dir,
        json_mode=json_mode,
    )
    if not result.success or json_path is None:
        return result

    structured_raw = result.structured_output or result.output
    if not structured_raw:
        return OfflineReviewResult(
            success=False,
            error=(
                "output_schema was provided but agent did not call set_output — "
                "structured output is required"
            ),
            diff_path=result.diff_path,
        )

    try:
        findings = _parse_and_validate_findings(structured_raw)
    except ValueError as exc:
        return OfflineReviewResult(
            success=False,
            error=str(exc),
            diff_path=result.diff_path,
        )

    try:
        _write_findings_json(json_path, findings)
    except OSError as exc:
        return OfflineReviewResult(
            success=False,
            error=f"failed to write findings JSON: {exc}",
            diff_path=result.diff_path,
        )

    return result


async def _run_agent_review(
    *,
    cwd: Path,
    materialization: DiffMaterialization,
    prompt: str,
    model: str | None,
    tmpdir: Path,
    json_mode: bool = False,
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

        output_schema = findings_output_schema() if json_mode else None
        mcp_url, stop_mcp = start_mcp_http_server(tool_context, output_schema=output_schema)
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
            subagent_denied_tools=subagent_denied_tool_names(tool_context, output_schema),
            instructions=instructions,
            tool_state=tool_state,
            api_token="",
            resolved_model=resolved_model,
        )

        logger.info("» offline diff-review via agent={}", agent.name)
        await agent.install()
        result = await agent.run(run_ctx)
        structured_output = tool_state.output
        markdown_output = result.output
        if json_mode and not structured_output:
            return OfflineReviewResult(
                success=False,
                error=(
                    "output_schema was provided but agent did not call set_output — "
                    "structured output is required"
                ),
                diff_path=str(materialization.path),
            )
        if not result.success:
            return OfflineReviewResult(
                success=False,
                output=markdown_output or structured_output,
                error=result.error or "agent failed",
                diff_path=str(materialization.path),
            )
        if json_mode:
            return OfflineReviewResult(
                success=True,
                output=markdown_output,
                structured_output=structured_output,
                diff_path=str(materialization.path),
            )
        return OfflineReviewResult(
            success=True,
            output=markdown_output or structured_output,
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
