"""``mergecraft init`` — scaffold local ``.mergecraft/config.yaml`` + example workflow."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
import yaml
from loguru import logger

from mergecraft.cli.consoles import err_console as console

DEFAULT_CONFIG: dict[str, object] = {
    "model": "anthropic/claude-sonnet",
    "push": "restricted",
    "shell": "restricted",
    "signedCommits": False,
    "prApproveEnabled": False,
    "autoMergeEnabled": False,
}

WORKFLOW_TEMPLATE = """\
name: mergeCraft

on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]
  workflow_dispatch:
    inputs:
      prompt:
        description: Prompt for the agent
        required: true

permissions:
  contents: write
  pull-requests: write
  issues: write
  checks: write
  actions: read

jobs:
  mergecraft:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run mergeCraft
        uses: ./  # or your published action ref
        with:
          prompt: ${{ github.event.inputs.prompt || github.event.comment.body }}
          model: anthropic/claude-sonnet
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          # or: CLAUDE_CODE_OAUTH_TOKEN / CODEX_AUTH_JSON / OPENAI_API_KEY
"""


def _parse_git_remote() -> tuple[str, str] | None:
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError, OSError, FileNotFoundError:
        return None
    import re

    match = re.search(r"github\.com(?::\d+)?[:/]+([^/]+)/(.+?)(?:\.git)?(?:/)?$", url)
    if not match:
        return None
    return match.group(1), match.group(2)


def run(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files."),
) -> None:
    """Scaffold ``.mergecraft/config.yaml`` and an example workflow (local, no API)."""
    root = Path.cwd()
    config_dir = root / ".mergecraft"
    config_path = config_dir / "config.yaml"
    workflow_dir = root / ".github" / "workflows"
    workflow_path = workflow_dir / "mergecraft.yml"

    remote = _parse_git_remote()
    if remote:
        console.print(f"detected repo [cyan]{remote[0]}/{remote[1]}[/cyan]")
    else:
        console.print("[dim]no git remote detected — scaffolding locally[/dim]")

    config_dir.mkdir(parents=True, exist_ok=True)
    if config_path.exists() and not force:
        console.print(
            "[yellow].mergecraft/config.yaml already exists[/yellow] — pass --force to overwrite"
        )
    else:
        config_path.write_text(
            yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        console.print(f"wrote [green]{config_path.relative_to(root)}[/green]")

    workflow_dir.mkdir(parents=True, exist_ok=True)
    if workflow_path.exists() and not force:
        console.print(f"[yellow]{workflow_path.relative_to(root)} already exists[/yellow]")
    else:
        workflow_path.write_text(WORKFLOW_TEMPLATE, encoding="utf-8")
        console.print(f"wrote [green]{workflow_path.relative_to(root)}[/green]")

    learnings = config_dir / "learnings.md"
    if not learnings.exists():
        learnings.write_text(
            "# Learnings\n\nOperational notes accumulated across agent runs.\n",
            encoding="utf-8",
        )
        console.print(f"wrote [green]{learnings.relative_to(root)}[/green]")

    console.print("\n[bold]next steps[/bold]")
    console.print(
        "  1. set provider secrets: [cyan]mergecraft auth claude[/cyan] or [cyan]mergecraft auth codex[/cyan]"
    )
    console.print("  2. commit and push the workflow + config")
    console.print("  3. trigger via comment or workflow_dispatch")
    logger.debug("init complete at {}", root)
