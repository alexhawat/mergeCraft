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

from mergecraft.analyzers.sarif import export_sarif
from mergecraft.cli.agent_protocol import AgentProtocolStream
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import RunOutcome, cli_exit_code_for_review
from mergecraft.cli.global_surface import get_cli_globals
from mergecraft.config.settings import parse_cli_trust_override
from mergecraft.offline_review import (
    OfflineReviewResult,
    parse_offline_review_findings,
    run_offline_diff_review,
)
from mergecraft.utils.log import configure_logging
from mergecraft.utils.source_resolve import SourceResolverSpec

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding


OutputFormat = Literal["text", "json", "jsonl", "sarif"]

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
        help="Model slug override (otherwise .mergecraft/config.yaml / MERGECRAFT_MODEL).",
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
            "Review payload format: text (default), json, jsonl, or sarif. "
            "Root --format json selects json when this flag is omitted; "
            "explicit --output-format text always renders human markdown on stderr. "
            "Default text mode writes human-readable review text to stderr (D14); "
            "redirect with 2> to capture it."
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
    trust: str | None = typer.Option(
        None,
        "--trust",
        help=(
            "Explicit trust tier override for this review source (trusted or untrusted). "
            "Never read from repo config — operator flag only (TS1 / D3)."
        ),
        rich_help_panel=_PANEL_TRUST,
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

    if effective_output_format == "json" and json_output is None and output is None:
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

    # The CLI always asks the agent for structured findings (see
    # ``_needs_structured_output`` — always True now). Precedence of the
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
            _exit_with_message(result.error or "diff-review failed", exit_code)

        if agent_mode:
            _emit_agent_protocol(outcome=outcome, exit_code=exit_code, findings=findings)
            raise typer.Exit(exit_code)

        text = result.output or ""

        if effective_output_format == "text":
            if output is not None:
                output.write_text(text, encoding="utf-8")
                console.print(f"[green]wrote[/green] {output}")
            elif json_output is None:
                console.print(text)
        elif effective_output_format == "json":
            target = json_output or output
            if target is not None and target.is_file():
                console.print(f"[green]wrote[/green] {target}")
        elif effective_output_format == "jsonl":
            target = output
            if target is None:
                _exit_with_message("--output is required for --output-format jsonl", exit_code)
            _write_jsonl_findings(target, findings)
            console.print(f"[green]wrote[/green] {target}")
        elif effective_output_format == "sarif":
            target = output
            if target is None:
                _exit_with_message("--output is required for --output-format sarif", exit_code)
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


run.__doc__ = _REVIEW_COMMAND_HELP
