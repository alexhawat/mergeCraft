"""``mergecraft diff-review`` — offline local git/patch review (no GitHub PR posting)."""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

import typer
from loguru import logger

from mergecraft.analyzers.finding import Finding
from mergecraft.cli.agent_protocol import AgentProtocolStream, notify_findings
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import RunOutcome, cli_exit_code_for_review
from mergecraft.cli.global_surface import get_cli_globals
from mergecraft.cli.review_output import (
    HunkFileFindings,
    OutputFormat,
    dispatch_review_output,
    finding_json_records,
)
from mergecraft.config.settings import parse_cli_trust_override
from mergecraft.offline_review import (
    OfflineReviewResult,
    parse_offline_review_findings,
    run_offline_diff_review,
)
from mergecraft.review.completed import CompletedReview, persist_completed_review
from mergecraft.review.completed_artifacts import (
    collect_evidence_packets_for_persist,
    collect_trace_events_for_review,
)
from mergecraft.review.engine import ReviewEngine
from mergecraft.review.finding_lookup import is_safe_path_stem
from mergecraft.review.snapshot import ReviewSnapshot, ReviewStageName, canonical_review_snapshot
from mergecraft.types import ShellPermission  # noqa: TC001
from mergecraft.utils.log import configure_logging
from mergecraft.utils.source_resolve import SourceResolverSpec

_PANEL_SOURCE = "Source"
_PANEL_DIFF = "Diff selection"
_PANEL_OUTPUT = "Output"
_PANEL_AGENT = "Agent"
_PANEL_TRACING = "Tracing"
_PANEL_TRUST = "Trust"

# Click treats a leading ``\b`` (backspace) as "do not rewrap this paragraph",
# so example commands stay copy-pasteable in ``mergecraft review --help``.
_REVIEW_COMMAND_HELP = """Review a local git diff offline (no GitHub Action / PR posting).

No flags are required. The minimum invocation is:

\b
  mergecraft review

That reviews the current git checkout: uncommitted edits plus commits since the
detected base (upstream, else origin/main or origin/master). You need:

* a git repository here, or --cwd PATH, or --repo, or --diff FILE
* a provider credential (`mergecraft auth …`) unless you pass --dry-run

This command never posts GitHub review comments. To review a GitHub PR, pass its
diff (--head pull/N/head, `gh pr diff`, or a local checkout of the PR branch).

Required vs optional:

* flags — none; `mergecraft review` is enough inside a git checkout
* source — cwd git repo (default), else one of --cwd / --repo / --diff
* credentials — required for a live review; skip with --dry-run
* --base / --head / --range / --staged / --unstaged — optional diff selectors
* --token — only for private --repo clones (else GH_TOKEN, GITHUB_TOKEN, or `gh auth token`)
* --shell — optional opt-in that lets analyzers run repo-provided tooling (unsafe
  for untrusted code); default disabled

Examples — local checkout / worktree vs a GitHub branch:

\b
  mergecraft review
  mergecraft review --dry-run
  mergecraft review --staged
  mergecraft review --unstaged
  mergecraft review --base origin/main
  mergecraft review --cwd ../feature-wt --base origin/main
  mergecraft review --head HEAD --base origin/pre-0.0.1
  mergecraft review --range HEAD~3..HEAD
  mergecraft review --range origin/main..HEAD
  mergecraft review --diff changes.patch --dry-run

Examples — present or past GitHub PR (diff only; no comments posted):

\b
  mergecraft review --repo owner/repo --head feature --base main
  mergecraft review --repo owner/repo --head pull/42/head --base main
  mergecraft review --repo owner/repo --head pull/42/head --token "$GH_TOKEN"
  gh pr checkout 42
  mergecraft review --base origin/main
  gh pr diff 42 > /tmp/pr-42.diff
  mergecraft review --diff /tmp/pr-42.diff
  gh pr diff 42 --repo owner/repo > /tmp/pr-42.diff
  mergecraft review --diff /tmp/pr-42.diff --dry-run

Examples — output:

\b
  mergecraft review --json findings.json
  mergecraft review --output-format sarif --output report.sarif.json
  mergecraft review --output-format jsonl --output stream.jsonl
  mergecraft review --output-format hunk
  mergecraft review --agent
  mergecraft review 2> review.md              # human text lives on stderr (D14)

Human-readable review text (default ``--output-format text``) is written to stderr
so stdout stays free for ``--agent`` JSONL. Shell redirects like ``> review.md``
capture nothing useful — use ``2> review.md`` instead.
"""


def _exit_with_message(msg: str, exit_code: int) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(exit_code)


def _resolve_review_output_format(
    ctx: typer.Context,
    *,
    output_format: OutputFormat | None,
) -> OutputFormat:
    """Resolve review payload format: explicit flag wins, else inherit root ``--format json``."""
    if output_format is not None:
        return output_format
    if get_cli_globals(ctx).format == "json":
        return "json"
    return "text"


def _resolve_outcome(result: OfflineReviewResult) -> RunOutcome:
    if result.outcome is not None:
        return result.outcome
    return RunOutcome.passed if result.success else RunOutcome.failed


def _safe_review_id_for_persist(review_id: str) -> str:
    """Return a path-safe review id for durable storage."""
    if is_safe_path_stem(review_id):
        return review_id
    logger.warning(
        "ignoring unsafe {} for durable review storage; using generated id",
        review_id,
    )
    return uuid.uuid4().hex


def _agent_finding_record(finding: dict[str, Any]) -> dict[str, Any]:
    """Normalize a streamed finding without attaching a per-row short id."""
    if finding.get("fingerprint"):
        return finding
    try:
        model = Finding.model_validate(finding)
    except ValueError:
        return finding
    return model.model_dump(mode="json")


def _persist_completed_cli_review(
    *,
    review_id: str,
    snapshot: ReviewSnapshot,
    cwd: Path,
    model: str | None,
    prompt: str | None,
    findings: Sequence[Finding],
    evidence_packet_path: str | None = None,
) -> None:
    from mergecraft.evidence.run_manifest import build_run_manifest

    safe_review_id = _safe_review_id_for_persist(review_id)
    manifest = build_run_manifest(
        cwd=cwd,
        model=model or "(unresolved)",
        agent_id="mergecraft",
        prompt_text=prompt or "",
    )
    findings_records = finding_json_records(findings)
    review = CompletedReview(
        review_id=safe_review_id,
        snapshot=snapshot,
        manifest=manifest,
        findings=findings_records,
        trace_session_id=review_id,
    )
    evidence_packets = collect_evidence_packets_for_persist(
        findings,
        repo_root=cwd,
        evidence_packet_path=evidence_packet_path,
    )
    trace_events = collect_trace_events_for_review(review_id, repo_root=cwd)
    try:
        persist_completed_review(
            review,
            repo_root=cwd,
            evidence_packets=evidence_packets,
            trace_events=trace_events,
        )
    except ValueError as exc:
        logger.warning("skipped durable review persistence: {}", exc)


def cleanup_review_subprocesses() -> None:
    """Kill agent and analyzer process groups after a cancelled review (#378)."""
    from mergecraft.reliability.recovery import cleanup_on_failure

    cleanup_on_failure("cancellation")


def _start_agent_protocol() -> AgentProtocolStream:
    from mergecraft.cli.agent_protocol import (
        ProtocolNegotiationError,
        accepted_protocol_versions,
        negotiate_protocol,
        protocol_budget_payload,
    )

    try:
        selected = negotiate_protocol(accepted=accepted_protocol_versions())
    except ProtocolNegotiationError as exc:
        _exit_with_message(
            str(exc),
            cli_exit_code_for_review(RunOutcome.configuration_error),
        )
    stream = AgentProtocolStream()
    stream.run_started(negotiated=selected, **protocol_budget_payload())
    return stream


def _finish_agent_protocol(
    stream: AgentProtocolStream,
    *,
    outcome: RunOutcome,
    exit_code: int,
    findings: Sequence[Finding],
    seen: set[str],
) -> None:
    notify_findings(
        stream.finding,
        finding_json_records(findings),
        seen=seen,
        refresh=True,
    )
    stream.verdict(outcome.value, exit_code)
    stream.run_finished(exit_code)


_DIFF_REVIEW_DEPRECATION = (
    "warning: `mergecraft diff-review` is deprecated; use `mergecraft review` instead."
)


def run(
    ctx: typer.Context,
    base: str | None = typer.Option(
        None,
        "--base",
        "-b",
        help=(
            "Git base ref for the diff (branch, origin/name, or SHA). "
            "Optional; default is upstream or origin/main|master."
        ),
        rich_help_panel=_PANEL_DIFF,
    ),
    repo: str | None = typer.Option(
        None,
        "--repo",
        help=(
            "Optional review source: local path, owner/repo, or "
            "https://github.com/owner/repo URL. Omit to use --cwd / the current checkout."
        ),
        rich_help_panel=_PANEL_SOURCE,
    ),
    head: str | None = typer.Option(
        None,
        "--head",
        help=(
            "Head ref to review (branch, SHA, or GitHub pull ref like pull/42/head). "
            "Optional; default is current HEAD or the cloned --repo ref."
        ),
        rich_help_panel=_PANEL_DIFF,
    ),
    staged: bool = typer.Option(
        False,
        "--staged",
        help="Review only staged changes (`git diff --cached`). Optional.",
        rich_help_panel=_PANEL_DIFF,
    ),
    unstaged: bool = typer.Option(
        False,
        "--unstaged",
        help="Review only unstaged working-tree changes. Optional.",
        rich_help_panel=_PANEL_DIFF,
    ),
    commit_range: str | None = typer.Option(
        None,
        "--range",
        help="Optional explicit commit range (e.g. HEAD~3..HEAD or origin/main..HEAD).",
        rich_help_panel=_PANEL_DIFF,
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help=(
            "GitHub token for a private --repo clone (wins over GH_TOKEN/GITHUB_TOKEN "
            "and `gh auth token`). Not needed for a local checkout."
        ),
        rich_help_panel=_PANEL_SOURCE,
    ),
    diff: Path | None = typer.Option(
        None,
        "--diff",
        "-d",
        exists=True,
        dir_okay=False,
        readable=True,
        help=(
            "Use an existing unified diff/patch file instead of computing one. "
            "Optional alternative to a git checkout (e.g. `gh pr diff 42 > pr.diff`)."
        ),
        rich_help_panel=_PANEL_SOURCE,
    ),
    cwd: Path = typer.Option(
        Path("."),
        "--cwd",
        help=(
            "Repository or linked-worktree path (default: current directory). "
            "Optional; the minimum `mergecraft review` uses `.`."
        ),
        rich_help_panel=_PANEL_SOURCE,
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help=(
            "Model slug override — wins over MERGECRAFT_MODEL, which wins over "
            ".mergecraft/config.yaml."
        ),
        rich_help_panel=_PANEL_AGENT,
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write review markdown or structured output (depends on --output-format) to this file.",
        rich_help_panel=_PANEL_OUTPUT,
    ),
    json_output: Path | None = typer.Option(
        None,
        "--json",
        help="Write structured findings JSON to this file.",
        rich_help_panel=_PANEL_OUTPUT,
    ),
    output_format: OutputFormat | None = typer.Option(
        None,
        "--output-format",
        help=(
            "Review payload format: text (default), json, jsonl, sarif, or hunk. "
            "Root --format json selects json when this flag is omitted; "
            "explicit --output-format text always renders human markdown on stderr. "
            "Default text mode writes human-readable review text to stderr (D14); "
            "redirect with 2> to capture it. "
            "hunk writes Hunk comment JSON to stdout (stdout-only; no --output)."
        ),
        rich_help_panel=_PANEL_OUTPUT,
    ),
    hunk_file_findings: HunkFileFindings = typer.Option(
        "drop",
        "--hunk-file-findings",
        help=(
            "For --output-format hunk: drop file-level findings (default) or "
            "anchor them on the first changed line per file (first-changed-line)."
        ),
        rich_help_panel=_PANEL_OUTPUT,
    ),
    agent_mode: bool = typer.Option(
        False,
        "--agent",
        help="Stream the agent JSONL protocol on stdout (orchestrator mode).",
        rich_help_panel=_PANEL_OUTPUT,
    ),
    evidence_packet: Path | None = typer.Option(
        None,
        "--evidence-packet",
        help=(
            "Write the Merge Evidence Packet JSON to this file. "
            "Defaults to the run's temp directory (the path is logged either way)."
        ),
        rich_help_panel=_PANEL_OUTPUT,
    ),
    prompt: str | None = typer.Option(
        None,
        "--prompt",
        "-p",
        help="Extra instructions appended to the offline Review prompt.",
        rich_help_panel=_PANEL_AGENT,
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Materialize the diff and print the Review prompt without invoking an agent.",
        rich_help_panel=_PANEL_AGENT,
    ),
    tracing: bool | None = typer.Option(
        None,
        "--tracing/--no-tracing",
        help=(
            "Override tracing enablement for this invocation. "
            "Wins over MERGECRAFT_TRACING and .mergecraft/config.yaml (W8.4 / W7.6)."
        ),
        rich_help_panel=_PANEL_TRACING,
    ),
    tracing_to: str | None = typer.Option(
        None,
        "--tracing-to",
        help=(
            "Override the tracing shorthand: local_files, logfire, or otel. "
            "Wins over MERGECRAFT_TRACING_TO and the config block (W8.4 / W7.6)."
        ),
        rich_help_panel=_PANEL_TRACING,
    ),
    trace_dir: Path | None = typer.Option(
        None,
        "--trace-dir",
        help="Override the jsonl_file sink path for local traces (W8.4 / W7.6).",
        rich_help_panel=_PANEL_TRACING,
    ),
    logfire_token: str | None = typer.Option(
        None,
        "--logfire-token",
        help=(
            "Resolve the logfire token directly. Wins over MERGECRAFT_LOGFIRE_TOKEN "
            "and the config block (W8.4 / W7.6)."
        ),
        rich_help_panel=_PANEL_TRACING,
    ),
    otel_endpoint: str | None = typer.Option(
        None,
        "--otel-endpoint",
        help=(
            "Override the OTLP collector endpoint. Wins over MERGECRAFT_OTEL_ENDPOINT "
            "and the config block (W8.4 / W7.6)."
        ),
        rich_help_panel=_PANEL_TRACING,
    ),
    shell: ShellPermission = typer.Option(
        "disabled",
        "--shell",
        help=(
            "Shell permission for this review: disabled (default), restricted, or enabled. "
            "Raising it lets analyzers execute tooling provided by the repository under "
            "review (ruff, mypy, bandit, vulture and the other repo-native analyzers, which "
            "are withheld at disabled). Unsafe for untrusted code — an opt-in for repos you "
            "trust. Operator flag only; never read from repo config."
        ),
        rich_help_panel=_PANEL_TRUST,
    ),
    trust: str | None = typer.Option(
        None,
        "--trust",
        help=(
            "Explicit trust tier override for this review source (trusted or untrusted). "
            "Never read from repo config — operator flag only (TS1 / D3)."
        ),
        rich_help_panel=_PANEL_TRUST,
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        help=(
            "Reuse a cached review result for this diff when one exists "
            "(same local result cache as --use-cache). Does not restore a live "
            "agent checkpoint."
        ),
        rich_help_panel=_PANEL_OUTPUT,
    ),
    use_cache: bool = typer.Option(
        False,
        "--use-cache/--no-use-cache",
        help=(
            "Read and write the local review result cache for this diff "
            "(same policy as --resume; distinct from the `mergecraft cache` typer)."
        ),
        rich_help_panel=_PANEL_OUTPUT,
    ),
) -> None:
    if ctx.info_name == "diff-review":
        console.print(_DIFF_REVIEW_DEPRECATION)
    configure_logging()
    effective_output_format = _resolve_review_output_format(ctx, output_format=output_format)
    invocation_root = Path.cwd().resolve()
    root = cwd.resolve()
    source_spec = SourceResolverSpec(
        repo=repo,
        head=head,
        base=base,
        staged=staged,
        unstaged=unstaged,
        commit_range=commit_range,
        token=token,
        cwd=root,
        invocation_root=invocation_root,
    )
    if diff is None and repo is None and not (root / ".git").exists():
        _exit_with_message(
            f"not a git repository: {root} (or pass --diff PATH or --repo)",
            cli_exit_code_for_review(RunOutcome.configuration_error),
        )

    try:
        trust_override = parse_cli_trust_override(trust)
    except ValueError as exc:
        _exit_with_message(str(exc), cli_exit_code_for_review(RunOutcome.configuration_error))

    try:
        from mergecraft.cli.config_surface_cmd import validate_repo_config_or_raise

        validate_repo_config_or_raise(cwd=root)
    except ValueError as exc:
        _exit_with_message(str(exc), cli_exit_code_for_review(RunOutcome.configuration_error))

    if (
        effective_output_format == "json"
        and json_output is None
        and output is None
        and not agent_mode
        and get_cli_globals(ctx).format != "json"
    ):
        _exit_with_message(
            "--output is required for --output-format json (or use --json PATH)",
            cli_exit_code_for_review(RunOutcome.configuration_error),
        )

    # Build the tracing CLI tokens (CLI > env > config precedence) and forward
    tracing_cli: list[str] = []
    if tracing is True:
        tracing_cli.append("--tracing")
    elif tracing is False:
        tracing_cli.append("--no-tracing")
    if tracing_to is not None:
        tracing_cli.extend(["--tracing-to", tracing_to])
    if trace_dir is not None:
        tracing_cli.extend(["--trace-dir", str(trace_dir)])
    if logfire_token is not None:
        tracing_cli.extend(["--logfire-token", logfire_token])
    if otel_endpoint is not None:
        tracing_cli.extend(["--otel-endpoint", otel_endpoint])

    # The CLI always asks the agent for structured findings. Precedence of the
    # structured sink path:
    # 1. ``--json PATH`` if supplied — that is the canonical findings file.
    # 2. ``--output PATH`` for ``--output-format json|jsonl|sarif`` — the writer is
    #    the same JSON in the requested container (jsonl/sarif readers get
    #    *real* findings instead of an empty file — PR #242 / 3f363546…).
    # 3. Default text mode — a temp file inside the run tmpdir that is parsed
    #    into the exit-code resolution and removed on exit (so the default
    #    text ``review`` can still exit 10/11 — PR #242 / 7a3cdf5e…; no
    #    findings.json is left next to the diff).
    json_path_for_run = json_output
    if (
        json_path_for_run is None
        and output is not None
        and effective_output_format
        in {
            "json",
            "jsonl",
            "sarif",
        }
    ):
        json_path_for_run = output
    if json_path_for_run is None:
        # ``needs_structured`` is always True now (default-text also asks).
        # Allocate a temp sink under our own ``tmpdir`` so cleanup is
        # straightforward; the file is removed at end of run regardless of
        # the text-format branch taken below.
        json_path_for_run = Path(
            tempfile.mkstemp(prefix="mergecraft-review-findings-", suffix=".json")[1]
        )

    internal_json_sink = json_output is None and not (
        output is not None and effective_output_format in {"json", "jsonl", "sarif"}
    )

    snapshot: ReviewSnapshot = canonical_review_snapshot(
        entry="cli",
        source=str(root),
        replay_key=str(diff) if diff is not None else None,
    )
    engine: ReviewEngine[OfflineReviewResult] = ReviewEngine(snapshot=snapshot)
    from mergecraft.tracing.review_context import resolve_review_id

    review_id = resolve_review_id()
    persist_review_id = _safe_review_id_for_persist(review_id)
    json_stdout = (
        effective_output_format == "json"
        and json_output is None
        and output is None
        and not agent_mode
        and get_cli_globals(ctx).format == "json"
    )

    stream: AgentProtocolStream | None = None
    seen: set[str] = set()
    phases_emitted = False
    if agent_mode:
        agent_stream = _start_agent_protocol()
        stream = agent_stream

        def _on_stage(name: ReviewStageName) -> None:
            nonlocal phases_emitted
            phases_emitted = True
            agent_stream.phase(name)

        engine.set_on_stage(_on_stage)

    def _on_finding(finding: dict[str, Any]) -> None:
        if stream is None:
            return
        notify_findings(stream.finding, [_agent_finding_record(finding)], seen=seen)

    read_cache = use_cache or resume

    try:
        try:
            result = asyncio.run(
                run_offline_diff_review(
                    cwd=root,
                    base=base,
                    diff_file=diff,
                    model=model,
                    prompt_extra=prompt,
                    dry_run=dry_run,
                    json_path=json_path_for_run,
                    evidence_packet_path=evidence_packet,
                    tracing_cli=tracing_cli,
                    invocation_root=invocation_root,
                    trust_override=trust_override,
                    shell=shell,
                    source_spec=source_spec,
                    on_finding=_on_finding if agent_mode else None,
                    use_cache=read_cache,
                    engine=engine,
                )
            )
        except TimeoutError:
            cleanup_review_subprocesses()
            result = OfflineReviewResult(
                success=False,
                error="review timed out",
                outcome=RunOutcome.timed_out,
            )
        except (KeyboardInterrupt, asyncio.CancelledError):
            cleanup_review_subprocesses()
            raise

        if agent_mode and stream is not None and not phases_emitted:
            # Tests (and other stubs) replace ``run_offline_diff_review`` and
            # never drive ``ReviewEngine``; still emit the documented phases.
            stream.phase("materialize")
            stream.phase("review")

        if result.diff_path:
            logger.info("» diff path: {}", result.diff_path)

        packet_path = result.evidence_packet_path
        if packet_path and Path(packet_path).is_file():
            logger.info("» evidence packet: {}", packet_path)

        outcome = _resolve_outcome(result)
        findings = parse_offline_review_findings(result)
        exit_code = cli_exit_code_for_review(outcome, findings)

        if result.success and not dry_run:
            _persist_completed_cli_review(
                review_id=review_id,
                snapshot=snapshot,
                cwd=root,
                model=model,
                prompt=prompt,
                findings=findings,
                evidence_packet_path=result.evidence_packet_path,
            )

        if not result.success:
            if result.output and not agent_mode:
                console.print(result.output)
            if agent_mode and stream is not None:
                _finish_agent_protocol(
                    stream,
                    outcome=outcome,
                    exit_code=exit_code,
                    findings=findings,
                    seen=seen,
                )
            _exit_with_message(result.error or "diff-review failed", exit_code)

        if agent_mode and stream is not None:
            _finish_agent_protocol(
                stream,
                outcome=outcome,
                exit_code=exit_code,
                findings=findings,
                seen=seen,
            )
            raise typer.Exit(exit_code)

        dispatch_review_output(
            effective_output_format=effective_output_format,
            result=result,
            findings=findings,
            review_id=persist_review_id,
            output=output,
            json_output=json_output,
            json_stdout=json_stdout,
            hunk_file_findings=hunk_file_findings,
            exit_code=exit_code,
        )

        if (
            json_output is not None
            and result.success
            and not dry_run
            and effective_output_format != "json"
        ):
            console.print(f"[green]wrote[/green] {json_output}")

        raise typer.Exit(exit_code)
    finally:
        # Default-text reviews borrow an internal JSON sink to populate the
        # exit-code resolution (PR #242 / 7a3cdf5e…). That file is never a
        # user-visible artifact — clean it up so the run leaves no side
        # effects behind. User-supplied sinks (``--json``, ``--output``) stay.
        if internal_json_sink:
            with contextlib.suppress(OSError):
                json_path_for_run.unlink(missing_ok=True)


run.__doc__ = _REVIEW_COMMAND_HELP
