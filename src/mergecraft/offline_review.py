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

from mergecraft.analyzers.finding import (
    STRUCTURED_OUTPUT_REQUIRED_MSG,
    Finding,
    findings_output_schema,
    parse_findings_payload,
    write_findings_json,
)
from mergecraft.analyzers.trust import (
    build_review_source,
    derive_source_trust_tier,
)
from mergecraft.config import load_repo_settings
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.agent_resolve import resolve_model
from mergecraft.utils.fence import Fence, render_untrusted
from mergecraft.utils.offline_diff import DiffMaterialization, summarize_diff
from mergecraft.utils.run_bounds import (
    BudgetExhausted,
    RunBounds,
    ScopeReduction,
    apply_diff_line_budget,
    budget_exhaustion_outcome,
    outcome_with_scope_reduction,
    resolve_run_bounds,
)
from mergecraft.utils.source_resolve import (
    SourceResolverSpec,
    filter_confined_paths,
    materialize_resolved_diff,
    resolve_workspace,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from mergecraft.config.settings import CliTrustOverride
    from mergecraft.mcp.context import ToolContext
    from mergecraft.review.engine import ReviewEngine
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


def _finish_offline_result(
    result: OfflineReviewResult,
    *,
    json_path: Path | None,
    scope_reduction: ScopeReduction | None,
    cache_key: str | None,
) -> OfflineReviewResult:
    """Apply structured-output finalize, then optionally store the post-finalize payload."""
    finished = result
    if json_path is not None:
        finished = _finalize_structured_findings(result, json_path)
    if finished.outcome is not None:
        finished.outcome = outcome_with_scope_reduction(finished.outcome, scope_reduction)
    elif finished.success:
        finished.outcome = outcome_with_scope_reduction(RunOutcome.passed, scope_reduction)
    finished.scope_reduction = scope_reduction
    if cache_key is not None and finished.success:
        from mergecraft.utils.review_result_cache import store_review_result

        store_review_result(cache_key, finished)
    return finished


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
    on_finding: Callable[[dict[str, Any]], None] | None = None,
    use_cache: bool = False,
    engine: ReviewEngine | None = None,
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
            on_finding=on_finding,
            use_cache=use_cache,
            engine=engine,
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
    on_finding: Callable[[dict[str, Any]], None] | None = None,
    use_cache: bool = False,
    engine: ReviewEngine | None = None,
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
    from mergecraft.review.engine import ReviewEngine
    from mergecraft.review.snapshot import canonical_review_snapshot
    from mergecraft.utils.process_group import kill_all_active_process_groups

    runner = engine or ReviewEngine(
        snapshot=canonical_review_snapshot(entry="cli", source=str(cwd))
    )
    runner.set_on_timeout(lambda _name: kill_all_active_process_groups())
    read_cache = use_cache
    materialization: DiffMaterialization | None = None
    cache_key: str | None = None
    from_cache = False

    async def _materialize() -> DiffMaterialization:
        nonlocal materialization, scope_reduction
        built = materialize_resolved_diff(
            workspace,
            spec=spec,
            out_dir=out_dir,
            diff_file=diff_file,
        )
        if trust_tier == "untrusted":
            diff_text = built.path.read_text(encoding="utf-8")
            paths = [
                line.split()[3].removeprefix("b/")
                for line in diff_text.splitlines()
                if line.startswith("diff --git ") and len(line.split()) >= 4
            ]
            kept = filter_confined_paths(cwd, paths)
            if kept != paths:
                filtered = _filter_diff_to_paths(diff_text, kept)
                built.path.write_text(filtered, encoding="utf-8")
                built = DiffMaterialization(
                    path=built.path,
                    base_ref=built.base_ref,
                    line_count=0 if not filtered.strip() else filtered.count("\n"),
                    empty=not filtered.strip(),
                )
        diff_text = built.path.read_text(encoding="utf-8")
        reduced_text, scope_reduction = apply_diff_line_budget(
            diff_text,
            max_lines=run_bounds.max_diff_lines,
        )
        if scope_reduction is not None:
            built.path.write_text(reduced_text, encoding="utf-8")
            built = DiffMaterialization(
                path=built.path,
                base_ref=built.base_ref,
                line_count=scope_reduction.kept_lines,
                empty=not reduced_text.strip(),
            )
        materialization = built
        return built

    async def _analyze() -> None:
        assert materialization is not None
        from mergecraft.review.offline_stages import run_offline_analyze

        await run_offline_analyze(
            cwd=cwd,
            materialization=materialization,
            trust_tier=trust_tier,
            analyzers_enabled=settings.analyzers.enabled,
        )

    async def _review() -> OfflineReviewResult:
        nonlocal cache_key, from_cache
        assert materialization is not None
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

        resolved_model = resolve_model(slug=model)
        if read_cache:
            from mergecraft.utils.review_result_cache import (
                cache_key_for_diff_path,
                load_review_result,
            )

            cache_key = cache_key_for_diff_path(
                materialization.path,
                model=resolved_model,
                trust_tier=trust_tier,
                prompt_extra=prompt_extra,
                json_mode=json_path is not None,
                base_ref=materialization.base_ref,
            )
            cached = load_review_result(cache_key)
            if cached is not None:
                if cached.diff_path is None:
                    cached.diff_path = str(materialization.path)
                from_cache = True
                return cached

        return await _run_agent_review(
            cwd=cwd,
            materialization=materialization,
            prompt=prompt,
            model=resolved_model,
            tmpdir=out_dir,
            output_schema=output_schema,
            evidence_packet_path=evidence_packet_path,
            trust_tier=trust_tier,
            run_bounds=run_bounds,
            on_finding=on_finding,
        )

    async def _publish(result: OfflineReviewResult) -> OfflineReviewResult:
        if result.empty_diff or dry_run:
            return result
        store_key = None if from_cache else cache_key
        return _finish_offline_result(
            result,
            json_path=json_path,
            scope_reduction=scope_reduction,
            cache_key=store_key,
        )

    try:
        try:
            staged = await runner.run(
                materialize=_materialize,
                analyze=_analyze,
                review=_review,
                publish=_publish,
            )
            output = staged.output
            if isinstance(output, OfflineReviewResult):
                return output
            return _offline_failure(
                error="review engine returned no result",
                outcome=RunOutcome.infra_error,
            )
        except TimeoutError:
            return _offline_failure(
                error="review timed out",
                outcome=RunOutcome.timed_out,
            )
        except BudgetExhausted as exc:
            return _offline_failure(
                error=str(exc),
                outcome=budget_exhaustion_outcome(exc),
            )
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            return _offline_failure(error=str(exc), outcome=_offline_error_outcome(exc))
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
    on_finding: Callable[[dict[str, Any]], None] | None = None,
) -> OfflineReviewResult:
    """Dispatch the Review agent; implementation lives in ``review.offline_agent``."""
    from mergecraft.review.offline_agent import run_offline_agent_review

    return await run_offline_agent_review(
        cwd=cwd,
        materialization=materialization,
        prompt=prompt,
        model=model,
        tmpdir=tmpdir,
        output_schema=output_schema,
        evidence_packet_path=evidence_packet_path,
        trust_tier=trust_tier,
        run_bounds=run_bounds,
        on_finding=on_finding,
    )
