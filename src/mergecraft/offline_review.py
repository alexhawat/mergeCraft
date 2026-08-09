"""Offline local diff review orchestration (no GitHub PR posting)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.agents.shared import AgentRunContext
from mergecraft.analyzers.finding import (
    STRUCTURED_OUTPUT_REQUIRED_MSG,
    Finding,
    findings_output_schema,
    parse_findings_payload,
    write_findings_json,
)
from mergecraft.config import load_repo_settings
from mergecraft.config.settings import RepoInfo
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.server import start_mcp_http_server
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.utils.agent_resolve import resolve_model, resolve_runtime_agent
from mergecraft.utils.fence import Fence, render_untrusted
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.instructions import resolve_instructions
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
    # On-disk path of the run's merge evidence packet (#47 / #96), or None
    # when no packet was produced (dry run, empty diff, emission failure).
    evidence_packet_path: str | None = None


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
        "\n## Additional instructions\n\n" + _render_offline_extra_block(extra) + "\n"
        if extra and extra.strip()
        else ""
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


def _render_offline_extra_block(extra: str) -> str:
    """Wrap the offline ``extra`` block in the per-run fence.

    The block is operator-supplied via the CLI ``--prompt-extra`` flag, but
    a fork PR can route a malicious comment string into it. Treat it as
    untrusted (D8) and fence it; the W4.4 trust tier derivation is the
    upstream caller's responsibility (CLI/Action sets ``author_association``
    to ``NONE`` here so the fence is applied unconditionally).
    """
    fence = Fence()
    return render_untrusted(
        extra.strip(),
        author="operator",
        tier="untrusted",
        label="offline_extra",
        nonce=fence.nonce,
    )


def _finalize_structured_findings(
    result: OfflineReviewResult,
    json_path: Path,
) -> OfflineReviewResult:
    """Validate agent structured output and write findings JSON."""
    if not result.success:
        return result

    structured_raw = result.structured_output
    if not structured_raw:
        return OfflineReviewResult(
            success=False,
            error=STRUCTURED_OUTPUT_REQUIRED_MSG,
            diff_path=result.diff_path,
            evidence_packet_path=result.evidence_packet_path,
        )

    try:
        findings = parse_findings_payload(structured_raw)
    except ValueError as exc:
        return OfflineReviewResult(
            success=False,
            error=str(exc),
            diff_path=result.diff_path,
            evidence_packet_path=result.evidence_packet_path,
        )

    try:
        write_findings_json(json_path, findings)
    except OSError as exc:
        return OfflineReviewResult(
            success=False,
            error=f"failed to write findings JSON: {exc}",
            diff_path=result.diff_path,
            evidence_packet_path=result.evidence_packet_path,
        )

    return result


def _offline_change_id(cwd: Path, materialization: DiffMaterialization) -> str:
    """Return the ``change_id`` an offline review attests to.

    There is no pull request, so the packet addresses the local working tree
    and the base it was diffed against — enough for a human to reconstruct
    what was reviewed.
    """
    base = materialization.base_ref or "patch"
    return f"local/{cwd.name}@{base}"


def _emit_offline_packet(
    tool_context: ToolContext,
    *,
    cwd: Path,
    materialization: DiffMaterialization,
    run_succeeded: bool,
    structured_output: str | None,
    output_path: Path | None,
) -> str | None:
    """Emit the evidence packet for an offline review (#96).

    The offline path holds the agent's findings in typed form (its
    ``set_output`` payload), so they are merged into the packet on top of the
    analyzer findings. A malformed payload is skipped rather than fatal — the
    caller reports that error separately, and a packet with analyzer evidence
    only still beats no packet.
    """
    from mergecraft.evidence.run_packet import emit_run_packet

    extra: list[Finding] = []
    if structured_output:
        try:
            # ``parse_findings_payload`` validates and then dumps back to dicts;
            # the packet dedupes on ``Finding.fingerprint``, so re-type them.
            extra = [
                Finding.model_validate(row) for row in parse_findings_payload(structured_output)
            ]
        except ValueError as exc:
            logger.debug("offline evidence packet: unparsable structured output — {}", exc)

    written = emit_run_packet(
        tool_context,
        run_succeeded=run_succeeded,
        change_id=_offline_change_id(cwd, materialization),
        extra_findings=extra,
        output_path=output_path,
    )
    return str(written) if written else None


async def run_offline_diff_review(
    *,
    cwd: Path,
    base: str | None = None,
    diff_file: Path | None = None,
    model: str | None = None,
    prompt_extra: str | None = None,
    dry_run: bool = False,
    json_path: Path | None = None,
    evidence_packet_path: Path | None = None,
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
        if json_path is not None:
            try:
                write_findings_json(json_path, [])
            except OSError as exc:
                return OfflineReviewResult(
                    success=False,
                    error=f"failed to write findings JSON: {exc}",
                )
        return OfflineReviewResult(
            success=True,
            output="no changes to review (empty diff).",
            diff_path=str(materialization.path),
            empty_diff=True,
        )

    output_schema = findings_output_schema() if json_path is not None else None
    prompt = build_offline_review_prompt(
        diff_path=materialization.path,
        base_ref=materialization.base_ref,
        extra=prompt_extra,
        json_mode=output_schema is not None,
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
        output_schema=output_schema,
        evidence_packet_path=evidence_packet_path,
    )
    if json_path is None:
        return result

    return _finalize_structured_findings(result, json_path)


async def _run_agent_review(
    *,
    cwd: Path,
    materialization: DiffMaterialization,
    prompt: str,
    model: str | None,
    tmpdir: Path,
    output_schema: dict[str, Any] | None = None,
    evidence_packet_path: Path | None = None,
) -> OfflineReviewResult:
    stop_mcp = None
    github: GitHubClient | None = None
    try:
        # Offline: no GitHub token required. MCP GitHub tools will fail if called —
        # the prompt forbids them.
        github = GitHubClient(token="")
        tool_state = init_tool_state(owner="local", name=cwd.name, dir=str(cwd))
        # Point the shared evidence seam at the patch this run reviewed, so the
        # offline packet classifies blast radius from the same diff the agent
        # read — exactly as the Action path does via ``checkout_pr``.
        primary_repo_state(tool_state).diff_path = str(materialization.path)
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
            suggest_eval_add=False,
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
            suggest_eval_add=False,
            # Carried so the evidence packet can attribute findings to the
            # model that actually produced them (#96); previously unset, which
            # left the packet's agent.model reading "(unresolved)".
            resolved_model=resolved_model,
        )

        mcp_url, stop_mcp = start_mcp_http_server(tool_context, output_schema=output_schema)
        tool_context.mcp_server_url = mcp_url
        skills_home = str(tmpdir / "home")
        Path(skills_home).mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(install_bundled_skills, home=skills_home)

        instructions = resolve_instructions(
            payload={
                "event": {"trigger": "unknown", "title": "offline diff-review"},
                "shell": "disabled",
                "push": "disabled",
                "prompt": prompt,
            },
            repo=RepoInfo(owner="local", name=cwd.name),
            modes=modes,
            agent_id=agent.name,
            output_schema=output_schema,
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
        packet_path = await asyncio.to_thread(
            _emit_offline_packet,
            tool_context,
            cwd=cwd,
            materialization=materialization,
            run_succeeded=result.success,
            structured_output=structured_output,
            output_path=evidence_packet_path,
        )
        if not result.success:
            return OfflineReviewResult(
                success=False,
                output=markdown_output,
                structured_output=structured_output,
                error=result.error or "agent failed",
                diff_path=str(materialization.path),
                evidence_packet_path=packet_path,
            )
        return OfflineReviewResult(
            success=True,
            output=markdown_output,
            structured_output=structured_output,
            diff_path=str(materialization.path),
            evidence_packet_path=packet_path,
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
