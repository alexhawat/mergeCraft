"""``mergecraft diff-review`` — offline local git/patch review (no GitHub PR posting)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import NoReturn

import typer
from loguru import logger
from rich.console import Console

from mergecraft.offline_review import run_offline_diff_review
from mergecraft.utils.log import configure_logging

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
) -> None:
    """Review a local git diff offline (no GitHub Action / PR posting).

    Computes ``git diff --merge-base <base>`` (or uses ``--diff``), then runs the
    Review-mode agent against that on-disk patch. Use ``--dry-run`` to inspect the
    prompt without LLM credentials.
    """
    configure_logging()
    root = cwd.resolve()
    if diff is None and not (root / ".git").exists():
        _bail(f"not a git repository: {root} (or pass --diff PATH)")

    result = asyncio.run(
        run_offline_diff_review(
            cwd=root,
            base=base,
            diff_file=diff,
            model=model,
            prompt_extra=prompt,
            dry_run=dry_run,
            json_path=json_output,
        )
    )

    if result.diff_path:
        logger.info("» diff path: {}", result.diff_path)

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
