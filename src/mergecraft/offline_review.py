"""Offline local diff review orchestration (no GitHub PR posting)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
from mergecraft.analyzers.trust import (
    allow_repo_command_overrides,
    build_review_source,
    derive_source_trust_tier,
)
from mergecraft.config import load_repo_settings
from mergecraft.config.settings import (
    CliTrustOverride,
    RepoInfo,
    apply_trust_tier_to_repo_settings,
    build_executable_config_skip_reason,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.server import MCP_ENDPOINT, MCP_REVIEWER_ENDPOINT, start_mcp_http_server
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.agent_resolve import resolve_model, resolve_runtime_agent
from mergecraft.utils.fence import Fence, render_untrusted
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.instructions import resolve_instructions
from mergecraft.utils.offline_diff import DiffMaterialization, summarize_diff
from mergecraft.utils.run_bounds import (
    BudgetExhausted,
    BudgetTracker,
    RunBounds,
    ScopeReduction,
    apply_diff_line_budget,
    budget_exhaustion_outcome,
    outcome_with_scope_reduction,
    record_agent_usage,
    resolve_run_bounds,
)
from mergecraft.utils.skills import install_bundled_skills
from mergecraft.utils.source_resolve import (
    SourceResolverSpec,
    filter_confined_paths,
    materialize_resolved_diff,
    resolve_workspace,
)

if TYPE_CHECKING:
    from mergecraft.tracing.review_context import ReviewContext
    from mergecraft.utils.source_resolve import ResolvedWorkspace


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
    outcome: RunOutcome | None = None
    scope_reduction: object | None = None


def _offline_failure(
    *,
    error: str,
    outcome: RunOutcome,
    diff_path: str | None = None,
    evidence_packet_path: str | None = None,
    output: str | None = None,
    structured_output: str | None = None,
) -> OfflineReviewResult:
    return OfflineReviewResult(
        success=False,
        error=error,
        output=output,
        structured_output=structured_output,
        diff_path=diff_path,
        evidence_packet_path=evidence_packet_path,
        outcome=outcome,
    )


def _offline_error_outcome(exc: BaseException) -> RunOutcome:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, subprocess.TimeoutExpired)):
        return RunOutcome.timed_out
    if isinstance(exc, ValueError):
        return RunOutcome.configuration_error
    return RunOutcome.infra_error


def parse_offline_review_findings(result: OfflineReviewResult) -> list[Finding]:
    """Parse validated findings from an offline review's structured output."""
    if not result.structured_output:
        return []
    try:
        return [
            Finding.model_validate(row) for row in parse_findings_payload(result.structured_output)
        ]
    except ValueError:
        return []


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


def _filter_diff_to_paths(diff_text: str, kept_paths: list[str]) -> str:
    """Keep only diff hunks for paths in ``kept_paths`` (D7 containment)."""
    if not kept_paths:
        return ""
    keep = set(kept_paths)
    blocks: list[str] = []
    current: list[str] = []
    current_path: str | None = None
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current and current_path in keep:
                blocks.append("".join(current))
            parts = line.split()
            current_path = parts[3].removeprefix("b/") if len(parts) >= 4 else None
            current = [line]
            continue
        if current:
            current.append(line)
    if current and current_path in keep:
        blocks.append("".join(current))
    return "".join(blocks)


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
        return _offline_failure(
            error=STRUCTURED_OUTPUT_REQUIRED_MSG,
            outcome=RunOutcome.configuration_error,
            diff_path=result.diff_path,
            evidence_packet_path=result.evidence_packet_path,
        )

    try:
        findings = parse_findings_payload(structured_raw)
    except ValueError as exc:
        return _offline_failure(
            error=str(exc),
            outcome=RunOutcome.configuration_error,
            diff_path=result.diff_path,
            evidence_packet_path=result.evidence_packet_path,
        )

    try:
        write_findings_json(json_path, findings)
    except OSError as exc:
        return _offline_failure(
            error=f"failed to write findings JSON: {exc}",
            outcome=RunOutcome.configuration_error,
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
    from mergecraft.evidence.run_manifest import build_run_manifest

    manifest = build_run_manifest(
        cwd=cwd,
        model=tool_context.resolved_model or tool_context.tool_state.model or "(unresolved)",
        agent_id=tool_context.agent_id,
        prompt_text=materialization.path.read_text(encoding="utf-8"),
    )
    logger.info("» run manifest fingerprints: {}", manifest)
    return str(written) if written else None


def _apply_tracing_cli_overrides(
    tracing_cli: list[str] | None,
) -> dict[str, str | None]:
    """Translate ``diff-review`` tracing flags into ``MERGECRAFT_*`` env overrides.

    The agent stream tracers resolve their sink from ``os.environ`` via
    :func:`mergecraft.tracing.resolve.resolve_active_tracing`, so forwarding the
    CLI flags as env overrides makes them win over any ``.env`` value already
    set (CLI > env precedence). A flag that was not supplied is left untouched,
    preserving the operator's ``.env`` setting. Returns the previous values so
    the caller can restore them after the run.

    Args:
        tracing_cli (list[str] | None): CLI-style tokens from the ``diff-review``
            command (``--tracing``, ``--no-tracing``, ``--tracing-to X``, …).

    Returns:
        dict[str, str | None]: The prior ``os.environ`` values for the keys we
        touched (``None`` when the key was absent), for restoration.
    """
    if not tracing_cli:
        return {}

    overrides: dict[str, str] = {}
    iterator = iter(tracing_cli)
    for token in iterator:
        if token in {"--tracing", "--no-tracing"}:
            overrides["MERGECRAFT_TRACING"] = "true" if token == "--tracing" else "false"
        elif token == "--tracing-to":
            overrides["MERGECRAFT_TRACING_TO"] = next(iterator, "")
        elif token == "--trace-dir":
            overrides["MERGECRAFT_TRACE_DIR"] = str(next(iterator, ""))
        elif token == "--logfire-token":
            overrides["MERGECRAFT_LOGFIRE_TOKEN"] = next(iterator, "")
        elif token == "--otel-endpoint":
            overrides["MERGECRAFT_OTEL_ENDPOINT"] = next(iterator, "")
        elif token.startswith("--tracing-to="):
            overrides["MERGECRAFT_TRACING_TO"] = token.split("=", 1)[1]
        elif token.startswith("--trace-dir="):
            overrides["MERGECRAFT_TRACE_DIR"] = token.split("=", 1)[1]
        elif token.startswith("--logfire-token="):
            overrides["MERGECRAFT_LOGFIRE_TOKEN"] = token.split("=", 1)[1]
        elif token.startswith("--otel-endpoint="):
            overrides["MERGECRAFT_OTEL_ENDPOINT"] = token.split("=", 1)[1]

    previous: dict[str, str | None] = {}
    for key, value in overrides.items():
        previous[key] = os.environ.get(key)
        os.environ[key] = value
    return previous


def resolve_offline_review_trust_tier(
    *,
    cwd: Path,
    invocation_root: Path,
    trust_override: CliTrustOverride | None = None,
    cloned: bool = False,
) -> str:
    """Resolve the trust tier for an offline CLI review from source provenance."""
    source = build_review_source(
        cwd=cwd,
        invocation_root=invocation_root,
        cloned=cloned,
    )
    return derive_source_trust_tier(source, trust_override=trust_override)


def apply_cli_trust_tier_env(tier: str) -> dict[str, str | None]:
    """Set ``MERGECRAFT_TRUST_TIER`` for the duration of a CLI review run."""
    previous = {"MERGECRAFT_TRUST_TIER": os.environ.get("MERGECRAFT_TRUST_TIER")}
    os.environ["MERGECRAFT_TRUST_TIER"] = tier
    return previous


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
    tracing_cli: list[str] | None = None,
    invocation_root: Path | None = None,
    trust_override: CliTrustOverride | None = None,
    cloned: bool = False,
    source_spec: SourceResolverSpec | None = None,
) -> OfflineReviewResult:
    """Materialize a local diff and optionally run the Review agent against it."""
    spec = source_spec or SourceResolverSpec(cwd=cwd, invocation_root=invocation_root or cwd)
    try:
        workspace = resolve_workspace(spec)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        return _offline_failure(error=str(exc), outcome=_offline_error_outcome(exc))

    cwd = workspace.cwd
    cloned = workspace.cloned or cloned
    try:
        from mergecraft.cli.config_surface_cmd import validate_repo_config_or_raise

        validate_repo_config_or_raise(cwd=cwd)
    except ValueError as exc:
        return _offline_failure(error=str(exc), outcome=RunOutcome.configuration_error)

    from mergecraft.tracing.review_context import bind_review_context

    review_root = (invocation_root or cwd).resolve()
    with bind_review_context(
        _offline_review_context(
            cwd=cwd, review_root=review_root, trust_override=trust_override, cloned=cloned
        )
    ):
        return await _run_offline_diff_review(
            cwd=cwd,
            base=base,
            diff_file=diff_file,
            model=model,
            prompt_extra=prompt_extra,
            dry_run=dry_run,
            json_path=json_path,
            evidence_packet_path=evidence_packet_path,
            tracing_cli=tracing_cli,
            workspace=workspace,
            spec=spec,
            review_root=review_root,
            trust_override=trust_override,
            cloned=cloned,
        )


def _offline_review_context(
    *,
    cwd: Path,
    review_root: Path,
    trust_override: CliTrustOverride | None = None,
    cloned: bool = False,
) -> ReviewContext:
    """Build the run's ``ReviewContext`` for a local diff review (OB1/O1).

    A local patch review has no repo/pr/head identity, so the correlation
    key stays empty (D3 — no misleading constant) and the review id resolves
    from ``MERGECRAFT_REVIEW_ID`` (inherited) or a fresh uuid4. The trust
    tier comes from ``resolve_offline_review_trust_tier`` — an explicit
    derivation from source provenance, never an env fallback (the OB2
    security gate: env-controlled tiers would silently neutralize the D7
    content cap).
    """
    from mergecraft.tracing.review_context import ReviewContext, resolve_review_id

    return ReviewContext(
        review_id=resolve_review_id(),
        source="cli",
        mode="review",
        trigger="cli",
        trust_tier=resolve_offline_review_trust_tier(
            cwd=cwd,
            invocation_root=review_root,
            trust_override=trust_override,
            cloned=cloned,
        ),
    )


async def _run_offline_diff_review(
    *,
    cwd: Path,
    base: str | None = None,
    diff_file: Path | None = None,
    model: str | None = None,
    prompt_extra: str | None = None,
    dry_run: bool = False,
    json_path: Path | None = None,
    evidence_packet_path: Path | None = None,
    tracing_cli: list[str] | None = None,
    workspace: ResolvedWorkspace,
    spec: SourceResolverSpec,
    review_root: Path,
    trust_override: CliTrustOverride | None = None,
    cloned: bool = False,
) -> OfflineReviewResult:
    """Body of :func:`run_offline_diff_review`, run under the bound review context."""
    cwd = cwd.resolve()
    if not (cwd / ".git").exists() and diff_file is None:
        return _offline_failure(
            error=f"not a git repository: {cwd} (pass --diff for a standalone patch file)",
            outcome=RunOutcome.configuration_error,
        )

    # Forward the ``diff-review`` tracing flags as ``MERGECRAFT_*`` env
    # overrides so the agent stream tracers (which resolve from
    # ``os.environ``) honor CLI > env precedence. Restored in the ``finally``
    # block so the override never leaks into the caller's environment.
    from mergecraft.evidence.run_manifest import apply_local_telemetry_defaults

    telemetry_env_previous = apply_local_telemetry_defaults(private_repo=True, cwd=cwd)
    tracing_env_previous = _apply_tracing_cli_overrides(tracing_cli)
    trust_tier = resolve_offline_review_trust_tier(
        cwd=cwd,
        invocation_root=review_root,
        trust_override=trust_override,
        cloned=cloned,
    )
    trust_env_previous = apply_cli_trust_tier_env(trust_tier)
    settings = load_repo_settings(root=cwd, load_learnings_files=False)
    run_bounds = resolve_run_bounds(settings=settings)
    scope_reduction: ScopeReduction | None = None

    out_dir = Path(tempfile.mkdtemp(prefix="mergecraft-diff-review-"))
    try:
        materialization = materialize_resolved_diff(
            workspace,
            spec=spec,
            out_dir=out_dir,
            diff_file=diff_file,
        )
        if trust_tier == "untrusted":
            diff_text = materialization.path.read_text(encoding="utf-8")
            paths = [
                line.split()[3].removeprefix("b/")
                for line in diff_text.splitlines()
                if line.startswith("diff --git ") and len(line.split()) >= 4
            ]
            kept = filter_confined_paths(cwd, paths)
            if kept != paths:
                filtered = _filter_diff_to_paths(diff_text, kept)
                materialization.path.write_text(filtered, encoding="utf-8")
                materialization = DiffMaterialization(
                    path=materialization.path,
                    base_ref=materialization.base_ref,
                    line_count=0 if not filtered.strip() else filtered.count("\n"),
                    empty=not filtered.strip(),
                )
        diff_text = materialization.path.read_text(encoding="utf-8")
        reduced_text, scope_reduction = apply_diff_line_budget(
            diff_text,
            max_lines=run_bounds.max_diff_lines,
        )
        if scope_reduction is not None:
            materialization.path.write_text(reduced_text, encoding="utf-8")
            materialization = DiffMaterialization(
                path=materialization.path,
                base_ref=materialization.base_ref,
                line_count=scope_reduction.kept_lines,
                empty=not reduced_text.strip(),
            )
    except BudgetExhausted as exc:
        return _offline_failure(
            error=str(exc),
            outcome=budget_exhaustion_outcome(exc),
        )
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        return _offline_failure(error=str(exc), outcome=_offline_error_outcome(exc))

    try:
        if materialization.empty:
            if json_path is not None:
                try:
                    write_findings_json(json_path, [])
                except OSError as exc:
                    return _offline_failure(
                        error=f"failed to write findings JSON: {exc}",
                        outcome=RunOutcome.configuration_error,
                    )
            return OfflineReviewResult(
                success=True,
                output="no changes to review (empty diff).",
                diff_path=str(materialization.path),
                empty_diff=True,
                outcome=outcome_with_scope_reduction(RunOutcome.passed, scope_reduction),
                scope_reduction=scope_reduction,
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
                outcome=outcome_with_scope_reduction(RunOutcome.passed, scope_reduction),
                scope_reduction=scope_reduction,
            )

        result = await _run_agent_review(
            cwd=cwd,
            materialization=materialization,
            prompt=prompt,
            model=model,
            tmpdir=out_dir,
            output_schema=output_schema,
            evidence_packet_path=evidence_packet_path,
            trust_tier=trust_tier,
            run_bounds=run_bounds,
        )
        if json_path is None:
            if result.outcome is not None:
                result.outcome = outcome_with_scope_reduction(result.outcome, scope_reduction)
            elif result.success:
                result.outcome = outcome_with_scope_reduction(RunOutcome.passed, scope_reduction)
            result.scope_reduction = scope_reduction
            return result

        finalized = _finalize_structured_findings(result, json_path)
        if finalized.outcome is not None:
            finalized.outcome = outcome_with_scope_reduction(finalized.outcome, scope_reduction)
        elif finalized.success:
            finalized.outcome = outcome_with_scope_reduction(RunOutcome.passed, scope_reduction)
        finalized.scope_reduction = scope_reduction
        return finalized
    finally:
        # Restore the operator's ``.env`` tracing vars so the ``diff-review``
        # overrides never leak into the caller's environment.
        for key, value in tracing_env_previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in telemetry_env_previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for key, value in trust_env_previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _run_agent_review(
    *,
    cwd: Path,
    materialization: DiffMaterialization,
    prompt: str,
    model: str | None,
    tmpdir: Path,
    output_schema: dict[str, Any] | None = None,
    evidence_packet_path: Path | None = None,
    trust_tier: str = "trusted",
    run_bounds: RunBounds | None = None,
) -> OfflineReviewResult:
    stop_mcp = None
    github: GitHubClient | None = None
    try:
        # Offline: no GitHub token required. MCP GitHub tools will fail if called —
        # the prompt forbids them.
        github = GitHubClient(token="")
        tool_state = init_tool_state(owner="local", name=cwd.name, dir=str(cwd))
        # Carry the review's resolved trust tier so drivers resolving the OB2
        # content policy via ``ctx.tool_state.trust_tier`` get the honest
        # derived tier (the OB2 security gate) rather than an env fallback.
        tool_state.trust_tier = trust_tier
        # Point the shared evidence seam at the patch this run reviewed, so the
        # offline packet classifies blast radius from the same diff the agent
        # read — exactly as the Action path does via ``checkout_pr``.
        primary_repo_state(tool_state).diff_path = str(materialization.path)
        settings = load_repo_settings(root=cwd, load_learnings_files=False)
        settings, drops = apply_trust_tier_to_repo_settings(
            settings,
            trust_tier,
            source_label="CLI offline review",
        )
        setup_script_skip_reason = ""
        if drops:
            for reason in drops.values():
                logger.warning("» {}", reason)
            setup_script_skip_reason = build_executable_config_skip_reason(drops)
            if setup_script_skip_reason:
                tool_state.setup_script_skip_reason = setup_script_skip_reason
        resolved_model = resolve_model(slug=model)
        agent = resolve_runtime_agent(model=resolved_model, settings=settings)
        modes = compute_modes(agent.name, signed_commits=False)
        bounds = run_bounds or resolve_run_bounds(settings=settings)
        budget_tracker = BudgetTracker(bounds)

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
            # D7 — untrusted CLI sources must not run repo-authored commands,
            # including Makefile-discovery fallback in ``plan_checks``.
            static_checks_enabled=allow_repo_command_overrides(trust_tier),  # type: ignore[arg-type]  # — trust_tier is str | None here; allow_repo_command_overrides expects TrustTier literal
            analyzers_mode="auto",
            trust_tier=trust_tier,  # type: ignore[arg-type]  # — trust_tier is str | None; callee expects TrustTier literal narrowing
            analyzers_settings_enabled=settings.analyzers.enabled,
            suggest_eval_add=False,
            # Carried so the evidence packet can attribute findings to the
            # model that actually produced them (#96); previously unset, which
            # left the packet's agent.model reading "(unresolved)".
            resolved_model=resolved_model,
            budget_tracker=budget_tracker,
        )

        mcp_url, stop_mcp = start_mcp_http_server(tool_context, output_schema=output_schema)
        tool_context.mcp_server_url = mcp_url
        _mcp_base = mcp_url[: -len(MCP_ENDPOINT)] if mcp_url.endswith(MCP_ENDPOINT) else mcp_url
        _reviewer_mcp_url = _mcp_base + MCP_REVIEWER_ENDPOINT
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
            setup_script_skip_reason=setup_script_skip_reason,
        )
        run_ctx = AgentRunContext(
            payload=payload,
            mcp_server_url=_reviewer_mcp_url,
            mcp_auth_token=tool_context.mcp_auth_token,
            tmpdir=str(tmpdir),
            subagent_denied_tools=subagent_denied_tool_names(tool_context, output_schema),
            instructions=instructions,
            tool_state=tool_state,
            api_token="",
            resolved_model=resolved_model,
        )

        logger.info("» offline diff-review via agent={}", agent.name)
        await agent.install()
        # O8/D10 (OB4) — issue the per-agent identity at dispatch, exactly as
        # the Action path does in main.py, so the CLI and Action traces agree.
        from mergecraft.tracing import get_tracer_from_settings
        from mergecraft.tracing.signals import agent_run_span

        with agent_run_span(
            get_tracer_from_settings(settings),
            agent_id=str(agent.name),
            role="reviewer",
            executed_model=resolved_model,
        ):
            result = await agent.run(run_ctx)
        try:
            record_agent_usage(budget_tracker, result.usage)
        except BudgetExhausted as exc:
            return OfflineReviewResult(
                success=False,
                output=result.output,
                structured_output=tool_state.output,
                error=str(exc),
                diff_path=str(materialization.path),
                outcome=budget_exhaustion_outcome(exc),
            )
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
                outcome=RunOutcome.failed,
            )
        return OfflineReviewResult(
            success=True,
            output=markdown_output,
            structured_output=structured_output,
            diff_path=str(materialization.path),
            evidence_packet_path=packet_path,
            outcome=RunOutcome.passed,
        )
    except Exception as exc:
        logger.exception("offline diff-review failed")
        return _offline_failure(
            error=str(exc),
            outcome=_offline_error_outcome(exc),
            diff_path=str(materialization.path),
        )
    finally:
        if stop_mcp is not None:
            stop_mcp()
        if github is not None:
            await github.aclose()
        if not os.environ.get("MERGECRAFT_KEEP_TMP"):
            logger.debug("offline review artifacts retained at {}", tmpdir)
