"""``mergecraft diff-review`` — offline local git/patch review (no GitHub PR posting)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import NoReturn

import typer
from loguru import logger
from rich.console import Console

from mergecraft.config.settings import parse_cli_trust_override
from mergecraft.offline_review import run_offline_diff_review
from mergecraft.utils.log import configure_logging
from mergecraft.utils.source_resolve import SourceResolverSpec

console = Console()


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


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
        help="Write the review markdown (or dry-run prompt) to this file.",
    ),
    json_output: Path | None = typer.Option(
        None,
        "--json",
        help="Write structured findings JSON to this file.",
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
        _bail(f"not a git repository: {root} (or pass --diff PATH or --repo)")

    try:
        trust_override = parse_cli_trust_override(trust)
    except ValueError as exc:
        _bail(str(exc))

    # Build the tracing CLI tokens (CLI > env > config precedence) and forward
    # them to the offline review, which exposes them as ``MERGECRAFT_*`` env
    # overrides so the agent stream tracers honor the operator's flags. The
    # ``--no-tracing`` / ``--tracing`` pair is a Typer bool flag (``None`` when
    # the operator left it at default), so we only emit a token when it was set.
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

    result = asyncio.run(
        run_offline_diff_review(
            cwd=root,
            base=base,
            diff_file=diff,
            model=model,
            prompt_extra=prompt,
            dry_run=dry_run,
            json_path=json_output,
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

    if not result.success:
        if result.output:
            console.print(result.output)
        _bail(result.error or "diff-review failed")

    text = result.output or ""
    if output is not None:
        output.write_text(text, encoding="utf-8")
        console.print(f"[green]wrote[/green] {output}")
    elif json_output is None:
        console.print(text)

    if json_output is not None and result.success and not dry_run:
        console.print(f"[green]wrote[/green] {json_output}")

    if result.empty_diff:
        raise typer.Exit(0)
