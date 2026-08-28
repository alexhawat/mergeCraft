"""``mergecraft init`` — scaffold local ``.mergecraft/config.yaml`` + example workflow."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer
import yaml
from loguru import logger

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.provider_cmd import seed_builtin_providers
from mergecraft.enterprise.audit import DEFAULT_AUDIT_REL
from mergecraft.pins import action_pin_minimal
from mergecraft.review.completed import COMPLETED_REVIEWS_GITIGNORE_LINE
from mergecraft.utils.git_hardening import git_argv

DEFAULT_CONFIG: dict[str, object] = {
    "models": ["anthropic/claude-sonnet"],
    "push": "restricted",
    "shell": "restricted",
    "signedCommits": False,
    "prApproveEnabled": False,
    "autoMergeEnabled": False,
}

_DEFAULT_MODELS = DEFAULT_CONFIG["models"]
assert isinstance(_DEFAULT_MODELS, list)
assert _DEFAULT_MODELS
_DEFAULT_MODEL = str(_DEFAULT_MODELS[0])


def _workflow_template() -> str:
    """Build the init scaffold workflow without import-time pin resolution."""
    pin = action_pin_minimal()
    return f"""\
name: mergeCraft

on:
  pull_request:
    types: [opened, ready_for_review, synchronize]
  workflow_dispatch:
    inputs:
      prompt:
        description: Prompt for the agent
        required: true
        type: string

permissions:
  contents: write
  pull-requests: write
  issues: write
  checks: write
  actions: read

jobs:
  mergecraft:
    if: >
      github.event_name == 'pull_request' ||
      github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - name: Run mergeCraft
        uses: alexhawat/mergeCraft@{pin}
        with:
          prompt: >
            ${{{{ github.event_name == 'pull_request'
                && 'Review this pull request.'
                || github.event.inputs.prompt }}}}
          model: {_DEFAULT_MODEL}
          status_checks: enabled
        env:
          CLAUDE_CODE_OAUTH_TOKEN: ${{{{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}}}
          # ANTHROPIC_API_KEY: ${{{{ secrets.ANTHROPIC_API_KEY }}}}
          # CODEX_AUTH_JSON: ${{{{ secrets.CODEX_AUTH_JSON }}}}
          # OPENAI_API_KEY: ${{{{ secrets.OPENAI_API_KEY }}}}
"""


def _audit_jsonl_gitignore_line() -> str:
    return DEFAULT_AUDIT_REL.as_posix()


def _reviews_gitignore_line() -> str:
    return COMPLETED_REVIEWS_GITIGNORE_LINE


def _ensure_gitignore_line(root: Path, line: str) -> None:
    """Ensure consumer ``.gitignore`` contains ``line`` once."""
    gitignore_path = root / ".gitignore"
    if gitignore_path.is_file():
        text = gitignore_path.read_text(encoding="utf-8")
        if line in text:
            return
        suffix = "" if not text or text.endswith("\n") else "\n"
        gitignore_path.write_text(f"{text}{suffix}{line}\n", encoding="utf-8")
    else:
        gitignore_path.write_text(f"{line}\n", encoding="utf-8")
    console.print(f"wrote [green]{gitignore_path.relative_to(root)}[/green]")


def _ensure_audit_jsonl_gitignore(root: Path) -> None:
    """Ensure consumer ``.gitignore`` ignores enterprise audit JSONL (D10 / #487)."""
    _ensure_gitignore_line(root, _audit_jsonl_gitignore_line())


def _ensure_reviews_gitignore(root: Path) -> None:
    """Ensure consumer ``.gitignore`` ignores durable local review artifacts."""
    _ensure_gitignore_line(root, _reviews_gitignore_line())


def _parse_git_remote() -> tuple[str, str] | None:
    try:
        url = subprocess.check_output(
            git_argv(["remote", "get-url", "origin"]),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, OSError, FileNotFoundError):  # fmt: skip
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
        workflow_path.write_text(_workflow_template(), encoding="utf-8")
        console.print(f"wrote [green]{workflow_path.relative_to(root)}[/green]")

    learnings = config_dir / "learnings.md"
    if not learnings.exists():
        learnings.write_text(
            "# Learnings\n\nOperational notes accumulated across agent runs.\n",
            encoding="utf-8",
        )
        console.print(f"wrote [green]{learnings.relative_to(root)}[/green]")

    _ensure_audit_jsonl_gitignore(root)
    _ensure_reviews_gitignore(root)

    if config_path.is_file():
        seed_builtin_providers(config_path)

    console.print("\n[bold]next steps[/bold]")
    console.print(
        "  1. set provider secrets: [cyan]mergecraft auth claude[/cyan] or [cyan]mergecraft auth codex[/cyan]"
    )
    console.print("  2. commit and push the workflow + config")
    console.print("  3. open a PR or run workflow_dispatch")
    logger.debug("init complete at {}", root)
