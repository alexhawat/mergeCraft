"""Offline local diff review orchestration (no GitHub PR posting)."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import (
    STRUCTURED_OUTPUT_REQUIRED_MSG,
    Finding,
    FindingsPayload,
    FindingValidationError,
    findings_output_schema,
    parse_findings_payload,
    write_findings_json,
)
from mergecraft.analyzers.trust import (
    build_review_source,
    derive_source_trust_tier,
)
from mergecraft.config import load_repo_settings
from mergecraft.mcp.checkout import changed_paths_in_diff
from mergecraft.review.offline_agent import run_offline_agent_review
from mergecraft.review.offline_result import (
    OfflineReviewResult as OfflineReviewResult,
)
from mergecraft.review.offline_result import (
    _offline_error_outcome,
    _offline_failure,
)
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
    from mergecraft.mcp.tool_state import AnalyzerRunState
    from mergecraft.review.engine import ReviewEngine
    from mergecraft.tracing.review_context import ReviewContext
    from mergecraft.types import ShellPermission
    from mergecraft.utils.source_resolve import ResolvedWorkspace


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


def findings_from_analyzer_run(state: AnalyzerRunState | None) -> list[Finding]:
    """Coerce stored analyzer rows into typed findings; skip invalid rows."""
    if state is None:
        return []
    findings: list[Finding] = []
    for row in state.findings:
        try:
            findings.append(row if isinstance(row, Finding) else Finding.model_validate(row))
        except (FindingValidationError, ValueError):
            continue
    return findings


def merge_analyzer_findings_into_result(
    result: OfflineReviewResult,
    extra: list[Finding],
) -> OfflineReviewResult:
    """Fold analyzer findings into structured output used for CLI exit codes."""
    if result.structured_output:
        try:
            parse_findings_payload(result.structured_output)
        except ValueError as exc:
            return _offline_failure(
                error=str(exc),
                outcome=RunOutcome.configuration_error,
                diff_path=result.diff_path,
                evidence_packet_path=result.evidence_packet_path,
            )
    if not extra:
        return result
    if result.structured_output:
        try:
            existing = [
                Finding.model_validate(row)
                for row in parse_findings_payload(result.structured_output)
            ]
        except ValueError:
            # Invalid agent output must fail in finalize — do not mask it with
            # analyzer rows (tests/cli/test_diff_review_json.py invalid_finding).
            return result
    else:
        existing = []
    seen = {row.fingerprint for row in existing}
    merged = list(existing)
    for finding in extra:
        if finding.fingerprint in seen:
            continue
        merged.append(finding)
        seen.add(finding.fingerprint)
    if len(merged) == len(existing) and result.structured_output:
        return result
    result.structured_output = FindingsPayload(findings=merged).model_dump_json()
    return result


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


def _iter_diff_file_blocks(diff_text: str) -> list[str]:
    """Split a unified diff into per-file hunks (each starts with ``diff --git``)."""
    blocks: list[str] = []
    current: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git ") and current:
            blocks.append("".join(current))
            current = [line]
            continue
        if current or line.startswith("diff --git "):
            current.append(line)
    if current:
        blocks.append("".join(current))
    return blocks


def _filter_diff_to_paths(diff_text: str, kept_paths: list[str]) -> str:
    """Keep only diff hunks for paths in ``kept_paths`` (D7 containment)."""
    if not kept_paths:
        return ""
    keep = set(kept_paths)
    blocks: list[str] = []
    for block in _iter_diff_file_blocks(diff_text):
        paths = changed_paths_in_diff(block)
        if paths and paths[0] in keep:
            blocks.append(block)
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
        elif token == "--tracing-content":
            overrides["MERGECRAFT_TRACING_CONTENT"] = next(iterator, "")
        elif token == "--tracing-export-untrusted-content":
            overrides["MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT"] = "true"
        elif token == "--no-tracing-export-untrusted-content":
            overrides["MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT"] = "false"
        elif token.startswith("--tracing-to="):
            overrides["MERGECRAFT_TRACING_TO"] = token.split("=", 1)[1]
        elif token.startswith("--trace-dir="):
            overrides["MERGECRAFT_TRACE_DIR"] = token.split("=", 1)[1]
        elif token.startswith("--logfire-token="):
            overrides["MERGECRAFT_LOGFIRE_TOKEN"] = token.split("=", 1)[1]
        elif token.startswith("--otel-endpoint="):
            overrides["MERGECRAFT_OTEL_ENDPOINT"] = token.split("=", 1)[1]
        elif token.startswith("--tracing-content="):
            overrides["MERGECRAFT_TRACING_CONTENT"] = token.split("=", 1)[1]

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
    shell: ShellPermission = "disabled",
    invocation_root: Path | None = None,
    trust_override: CliTrustOverride | None = None,
    cloned: bool = False,
    source_spec: SourceResolverSpec | None = None,
    on_finding: Callable[[dict[str, Any]], None] | None = None,
    use_cache: bool = False,
    engine: ReviewEngine[OfflineReviewResult] | None = None,
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
            shell=shell,
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


@dataclass(slots=True)
class _OfflineDiffReviewRun:
    """Typed stage driver for one offline CLI review (no closed-over locals)."""

    cwd: Path
    workspace: ResolvedWorkspace
    spec: SourceResolverSpec
    out_dir: Path
    diff_file: Path | None
    trust_tier: str
    run_bounds: RunBounds
    analyzers_enabled: bool
    json_path: Path | None
    prompt_extra: str | None
    dry_run: bool
    model: str | None
    evidence_packet_path: Path | None
    on_finding: Callable[[dict[str, Any]], None] | None
    read_cache: bool
    # Operator opt-in (#1). Defaults to the historical hardcoded value so any
    # caller that omits it keeps the pre-flag behaviour: repo-native analyzers
    # stay withheld unless `mergecraft review --shell` explicitly raises this.
    shell: ShellPermission = "disabled"
    materialization: DiffMaterialization | None = None
    scope_reduction: ScopeReduction | None = None
    cache_key: str | None = None
    from_cache: bool = False
    analyzer_run: AnalyzerRunState | None = None

    async def materialize(self) -> DiffMaterialization:
        built = materialize_resolved_diff(
            self.workspace,
            spec=self.spec,
            out_dir=self.out_dir,
            diff_file=self.diff_file,
        )
        if self.trust_tier == "untrusted":
            diff_text = built.path.read_text(encoding="utf-8")
            paths = changed_paths_in_diff(diff_text)
            kept = filter_confined_paths(self.cwd, paths)
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
        reduced_text, self.scope_reduction = apply_diff_line_budget(
            diff_text,
            max_lines=self.run_bounds.max_diff_lines,
        )
        if self.scope_reduction is not None:
            built.path.write_text(reduced_text, encoding="utf-8")
            built = DiffMaterialization(
                path=built.path,
                base_ref=built.base_ref,
                line_count=self.scope_reduction.kept_lines,
                empty=not reduced_text.strip(),
            )
        self.materialization = built
        return built

    async def analyze(self) -> None:
        assert self.materialization is not None
        if self.dry_run:
            return
        from mergecraft.review.offline_stages import run_offline_analyze

        self.analyzer_run = await run_offline_analyze(
            cwd=self.cwd,
            materialization=self.materialization,
            trust_tier=self.trust_tier,
            shell=self.shell,
            analyzers_enabled=self.analyzers_enabled,
        )

    async def review(self) -> OfflineReviewResult:
        assert self.materialization is not None
        if self.materialization.empty:
            if self.json_path is not None:
                try:
                    write_findings_json(self.json_path, [])
                except OSError as exc:
                    return _offline_failure(
                        error=f"failed to write findings JSON: {exc}",
                        outcome=RunOutcome.configuration_error,
                    )
            return OfflineReviewResult(
                success=True,
                output="no changes to review (empty diff).",
                diff_path=str(self.materialization.path),
                empty_diff=True,
                outcome=outcome_with_scope_reduction(RunOutcome.passed, self.scope_reduction),
                scope_reduction=self.scope_reduction,
            )

        output_schema = findings_output_schema() if self.json_path is not None else None
        prompt = build_offline_review_prompt(
            diff_path=self.materialization.path,
            base_ref=self.materialization.base_ref,
            extra=self.prompt_extra,
            json_mode=output_schema is not None,
        )

        if self.dry_run:
            return OfflineReviewResult(
                success=True,
                output=prompt,
                diff_path=str(self.materialization.path),
                empty_diff=False,
                outcome=outcome_with_scope_reduction(RunOutcome.passed, self.scope_reduction),
                scope_reduction=self.scope_reduction,
            )

        resolved_model = resolve_model(slug=self.model)
        if self.read_cache:
            from mergecraft.utils.review_result_cache import (
                cache_key_for_diff_path,
                load_review_result,
            )

            self.cache_key = cache_key_for_diff_path(
                self.materialization.path,
                model=resolved_model,
                trust_tier=self.trust_tier,
                prompt_extra=self.prompt_extra,
                json_mode=self.json_path is not None,
                base_ref=self.materialization.base_ref,
                cwd=self.cwd,
            )
            cached = load_review_result(self.cache_key)
            if cached is not None:
                if cached.diff_path is None:
                    cached.diff_path = str(self.materialization.path)
                self.from_cache = True
                return merge_analyzer_findings_into_result(
                    cached, findings_from_analyzer_run(self.analyzer_run)
                )

        reviewed = await run_offline_agent_review(
            cwd=self.cwd,
            materialization=self.materialization,
            prompt=prompt,
            model=resolved_model,
            tmpdir=self.out_dir,
            output_schema=output_schema,
            evidence_packet_path=self.evidence_packet_path,
            trust_tier=self.trust_tier,
            shell=self.shell,
            run_bounds=self.run_bounds,
            on_finding=self.on_finding,
            analyzer_run=self.analyzer_run,
        )
        return merge_analyzer_findings_into_result(
            reviewed, findings_from_analyzer_run(self.analyzer_run)
        )

    async def publish(self, review_out: OfflineReviewResult) -> OfflineReviewResult:
        if review_out.empty_diff or self.dry_run:
            return review_out
        store_key = None if self.from_cache else self.cache_key
        return _finish_offline_result(
            review_out,
            json_path=self.json_path,
            scope_reduction=self.scope_reduction,
            cache_key=store_key,
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
    shell: ShellPermission = "disabled",
    workspace: ResolvedWorkspace,
    spec: SourceResolverSpec,
    review_root: Path,
    trust_override: CliTrustOverride | None = None,
    cloned: bool = False,
    on_finding: Callable[[dict[str, Any]], None] | None = None,
    use_cache: bool = False,
    engine: ReviewEngine[OfflineReviewResult] | None = None,
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

    out_dir = Path(tempfile.mkdtemp(prefix="mergecraft-diff-review-"))
    from mergecraft.review.engine import ReviewEngine
    from mergecraft.review.snapshot import canonical_review_snapshot
    from mergecraft.utils.process_group import kill_all_active_process_groups

    runner: ReviewEngine[OfflineReviewResult] = engine or ReviewEngine(
        snapshot=canonical_review_snapshot(entry="cli", source=str(cwd))
    )
    runner.set_on_timeout(lambda _name: kill_all_active_process_groups())
    driver = _OfflineDiffReviewRun(
        cwd=cwd,
        workspace=workspace,
        spec=spec,
        out_dir=out_dir,
        diff_file=diff_file,
        trust_tier=trust_tier,
        shell=shell,
        run_bounds=run_bounds,
        analyzers_enabled=settings.analyzers.enabled,
        json_path=json_path,
        prompt_extra=prompt_extra,
        dry_run=dry_run,
        model=model,
        evidence_packet_path=evidence_packet_path,
        on_finding=on_finding,
        read_cache=use_cache,
    )

    try:
        try:
            staged = await runner.run(driver)
            return staged.published_or(
                _offline_failure(
                    error="review engine returned no result",
                    outcome=RunOutcome.infra_error,
                )
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
