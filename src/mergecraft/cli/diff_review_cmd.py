"""``mergecraft diff-review`` — offline local git/patch review (no GitHub PR posting)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NoReturn

import typer
from loguru import logger
from rich.console import Console

from mergecraft.analyzers.sarif import export_sarif
from mergecraft.cli.agent_protocol import AgentProtocolStream
from mergecraft.config.settings import parse_cli_trust_override
from mergecraft.offline_review import (
    OfflineReviewResult,
    parse_offline_review_findings,
    run_offline_diff_review,
)
from mergecraft.run_outcome import RunOutcome, cli_exit_code_for_review
from mergecraft.utils.log import configure_logging
from mergecraft.utils.source_resolve import SourceResolverSpec

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

console = Console()
error_console = Console(stderr=True)

OutputFormat = Literal["text", "json", "jsonl", "sarif"]


def _exit_with_message(msg: str, exit_code: int, *, agent_mode: bool = False) -> NoReturn:
    target = error_console if agent_mode else console
    target.print(f"[red]{msg}[/red]")
    raise typer.Exit(exit_code)


def _resolve_outcome(result: OfflineReviewResult) -> RunOutcome:
    if result.outcome is not None:
        return result.outcome
    return RunOutcome.passed if result.success else RunOutcome.failed


def _needs_structured_output(
    *,
    json_output: Path | None,
    output_format: OutputFormat,
) -> bool:
    # The agent's structured findings are read for two reasons: (a) writing
    # --json/--format json/jsonl/sarif, (b) computing the CC1 exit codes
    # 10/11 (which key off the parsed findings list). Default text ``review``
    # therefore *also* requests structured findings — the temp file is
    # cleaned up at end of run — so a CI script running `review` and
    # blocking on exit 10/11 sees the contract applied uniformly. PR #242
    # review findings ``3f363546e98dad517048b8b9`` and
    # ``7a3cdf5ef1994610113e8e37``.
    return True


def _write_jsonl_findings(path: Path, findings: Sequence[Finding]) -> None:
    lines: list[str] = []
    for row in findings:
        lines.append(json.dumps({"finding": row.model_dump()}, ensure_ascii=False))
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _emit_agent_protocol(
    *,
    outcome: RunOutcome,
    exit_code: int,
    findings: Sequence[Finding],
) -> None:
    stream = AgentProtocolStream()
    stream.run_started()
    stream.phase("materialize")
    stream.phase("review")
    for row in findings:
        stream.finding(row.model_dump())
    stream.verdict(outcome.value, exit_code)
    stream.run_finished(exit_code)


def run(
    base: str | None = typer.Option(
        None,
        "--base",
        "-b",
        help="Git base ref for merge-base diff (default: upstream or origin/main|master).",
    ),
    repo: str | None = typer.Option(
        None,
        "--repo",
        help=(
            "Review source: local path, https://github.com/owner/repo URL, or owner/repo shorthand."
        ),
    ),
    head: str | None = typer.Option(
        None,
        "--head",
        help="Head ref to review (default: current HEAD or clone ref).",
    ),
    staged: bool = typer.Option(
        False,
        "--staged",
        help="Review only staged changes (`git diff --cached`).",
    ),
    unstaged: bool = typer.Option(
        False,
        "--unstaged",
        help="Review only unstaged working-tree changes.",
    ),
    commit_range: str | None = typer.Option(
        None,
        "--range",
        help="Explicit commit range (e.g. HEAD~3..HEAD).",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help=(
            "GitHub token for private clone (wins over GH_TOKEN/GITHUB_TOKEN and `gh auth token`)."
        ),
    ),
    diff: Path | None = typer.Option(
        None,
        "--diff",
        "-d",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Use an existing unified diff/patch file instead of computing one.",
    ),
    cwd: Path = typer.Option(
        Path("."),
        "--cwd",
        help="Repository working directory (default: current directory).",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model slug override (otherwise .mergecraft/config.yaml / MERGECRAFT_MODEL).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Write review markdown or structured output (depends on --format) to this file.",
    ),
    json_output: Path | None = typer.Option(
        None,
        "--json",
        help="Write structured findings JSON to this file.",
    ),
    output_format: OutputFormat = typer.Option(
        "text",
        "--format",
        help="Machine output format: text (default), json, jsonl, or sarif.",
    ),
    agent_mode: bool = typer.Option(
        False,
        "--agent",
        help="Stream the agent JSONL protocol on stdout (orchestrator mode).",
    ),
    evidence_packet: Path | None = typer.Option(
        None,
        "--evidence-packet",
        help=(
            "Write the Merge Evidence Packet JSON to this file. "
            "Defaults to the run's temp directory (the path is logged either way)."
        ),
    ),
    prompt: str | None = typer.Option(
        None,
        "--prompt",
        "-p",
        help="Extra instructions appended to the offline Review prompt.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Materialize the diff and print the Review prompt without invoking an agent.",
    ),
    tracing: bool | None = typer.Option(
        None,
        "--tracing/--no-tracing",
        help=(
            "Override tracing enablement for this invocation. "
            "Wins over MERGECRAFT_TRACING and .mergecraft/config.yaml (W8.4 / W7.6)."
        ),
    ),
    tracing_to: str | None = typer.Option(
        None,
        "--tracing-to",
        help=(
            "Override the tracing shorthand: local_files, logfire, or otel. "
            "Wins over MERGECRAFT_TRACING_TO and the config block (W8.4 / W7.6)."
        ),
    ),
    trace_dir: Path | None = typer.Option(
        None,
        "--trace-dir",
        help="Override the jsonl_file sink path for local traces (W8.4 / W7.6).",
    ),
    logfire_token: str | None = typer.Option(
        None,
        "--logfire-token",
        help=(
            "Resolve the logfire token directly. Wins over MERGECRAFT_LOGFIRE_TOKEN "
            "and the config block (W8.4 / W7.6)."
        ),
    ),
    otel_endpoint: str | None = typer.Option(
        None,
        "--otel-endpoint",
        help=(
            "Override the OTLP collector endpoint. Wins over MERGECRAFT_OTEL_ENDPOINT "
            "and the config block (W8.4 / W7.6)."
        ),
    ),
    trust: str | None = typer.Option(
        None,
        "--trust",
        help=(
            "Explicit trust tier override for this review source (trusted or untrusted). "
            "Never read from repo config — operator flag only (TS1 / D3)."
        ),
    ),
) -> None:
    """Review a local git diff offline (no GitHub Action / PR posting).

    Computes ``git diff --merge-base <base>`` (or uses ``--diff``), then runs the
    Review-mode agent against that on-disk patch. Use ``--dry-run`` to inspect the
    prompt without LLM credentials.
    """
    configure_logging()
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

    if output_format == "json" and json_output is None and output is None:
        _exit_with_message(
            "--output is required for --format json (or use --json PATH)",
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

    # The CLI always asks the agent for structured findings (see
    # ``_needs_structured_output`` — always True now). Precedence of the
    # structured sink path:
    # 1. ``--json PATH`` if supplied — that is the canonical findings file.
    # 2. ``--output PATH`` for ``--format json|jsonl|sarif`` — the writer is
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
        and output_format
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
        output is not None and output_format in {"json", "jsonl", "sarif"}
    )

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
                source_spec=source_spec,
            )
        )

        if result.diff_path:
            logger.info("» diff path: {}", result.diff_path)

        if result.evidence_packet_path:
            logger.info("» evidence packet: {}", result.evidence_packet_path)

        outcome = _resolve_outcome(result)
        findings = parse_offline_review_findings(result)
        exit_code = cli_exit_code_for_review(outcome, findings)

        if not result.success:
            if result.output and not agent_mode:
                console.print(result.output)
            if agent_mode:
                _emit_agent_protocol(outcome=outcome, exit_code=exit_code, findings=findings)
            _exit_with_message(
                result.error or "diff-review failed", exit_code, agent_mode=agent_mode
            )

        if agent_mode:
            _emit_agent_protocol(outcome=outcome, exit_code=exit_code, findings=findings)
            raise typer.Exit(exit_code)

        text = result.output or ""

        if output_format == "text":
            if output is not None:
                output.write_text(text, encoding="utf-8")
                console.print(f"[green]wrote[/green] {output}")
            elif json_output is None:
                console.print(text)
        elif output_format == "json":
            target = json_output or output
            if target is not None and target.is_file():
                console.print(f"[green]wrote[/green] {target}")
        elif output_format == "jsonl":
            target = output
            if target is None:
                _exit_with_message("--output is required for --format jsonl", exit_code)
            _write_jsonl_findings(target, findings)
            console.print(f"[green]wrote[/green] {target}")
        elif output_format == "sarif":
            target = output
            if target is None:
                _exit_with_message("--output is required for --format sarif", exit_code)
            document = export_sarif(findings)
            target.write_text(json.dumps(document, indent=2), encoding="utf-8")
            console.print(f"[green]wrote[/green] {target}")

        if json_output is not None and result.success and not dry_run:
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
