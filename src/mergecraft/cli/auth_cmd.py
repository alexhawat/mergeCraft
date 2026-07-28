"""``mergecraft auth`` — Codex device auth / Claude token → ``gh secret set``."""

from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import NoReturn

import typer
from loguru import logger
from rich.console import Console

app = typer.Typer(
    help="Manage provider credentials for the current repository.", no_args_is_help=True
)
console = Console()

CODEX_AUTH_SECRET = "CODEX_AUTH_JSON"
CLAUDE_OAUTH_SECRET = "CLAUDE_CODE_OAUTH_TOKEN"
CLAUDE_OAUTH_TOKEN_PREFIX = "sk-ant-oat"


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _get_gh_token() -> str:
    try:
        token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
    except subprocess.CalledProcessError, FileNotFoundError, OSError:
        _bail(
            "gh cli not found or not authenticated.\n"
            "  install: https://cli.github.com\n"
            "  then:    gh auth login"
        )
    if not token:
        _bail("gh cli returned an empty token. try: gh auth login")
    return token


def _parse_git_remote() -> tuple[str, str]:
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError, FileNotFoundError, OSError:
        _bail("not a git repository or no 'origin' remote found.")
    match = re.search(r"github\.com(?::\d+)?[:/]+([^/]+)/(.+?)(?:\.git)?(?:/)?$", url)
    if not match:
        _bail(f"could not parse github owner/repo from remote: {url}")
    return match.group(1), match.group(2)


def _set_gh_secret(*, name: str, value: str, repo_slug: str) -> bool:
    try:
        subprocess.run(
            ["gh", "secret", "set", name, "--repo", repo_slug],
            input=value,
            text=True,
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        logger.warning("gh secret set failed: {}", exc)
        return False


@app.command("codex")
def auth_codex() -> None:
    """Mint a Codex subscription credential and save it as CODEX_AUTH_JSON."""
    _get_gh_token()
    owner, repo = _parse_git_remote()
    repo_slug = f"{owner}/{repo}"
    console.print(f"detected repo [cyan]{repo_slug}[/cyan]")

    if not shutil.which("codex"):
        _bail(
            "codex CLI not found on PATH.\n"
            "  install: npm i -g @openai/codex\n"
            "  then:    mergecraft auth codex"
        )

    with tempfile.TemporaryDirectory(prefix="mergecraft-codex-") as tmp:
        env = {**os.environ, "CODEX_HOME": tmp}
        console.print("running [cyan]codex login --device-auth[/cyan] (isolated CODEX_HOME)...")
        try:
            subprocess.run(
                ["codex", "login", "--device-auth"],
                env=env,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            _bail(f"codex login failed (exit {exc.returncode})")

        auth_path = Path(tmp) / "auth.json"
        if not auth_path.is_file():
            _bail("no auth.json was written — enable device-code auth and retry")
        value = auth_path.read_text(encoding="utf-8")

    console.print(f"saving [cyan]{CODEX_AUTH_SECRET}[/cyan] via gh secret set...")
    if not _set_gh_secret(name=CODEX_AUTH_SECRET, value=value, repo_slug=repo_slug):
        _bail(
            f"could not set secret — set it manually at:\n"
            f"  https://github.com/{repo_slug}/settings/secrets/actions"
        )
    console.print(f"[green]saved {CODEX_AUTH_SECRET}[/green] to GitHub Actions secrets")


@app.command("claude")
def auth_claude() -> None:
    """Save a Claude Code OAuth token as CLAUDE_CODE_OAUTH_TOKEN."""
    _get_gh_token()
    owner, repo = _parse_git_remote()
    repo_slug = f"{owner}/{repo}"
    console.print(f"detected repo [cyan]{repo_slug}[/cyan]")
    console.print(
        "mint a token with [cyan]claude setup-token[/cyan], then paste it below "
        f"(expected prefix [cyan]{CLAUDE_OAUTH_TOKEN_PREFIX}…[/cyan])."
    )
    try:
        oauth_token = getpass.getpass("Claude Code OAuth token (Enter to cancel): ").strip()
    except EOFError, KeyboardInterrupt:
        console.print("canceled.")
        raise typer.Exit(0) from None
    if not oauth_token:
        console.print("canceled.")
        raise typer.Exit(0)
    if not oauth_token.startswith(CLAUDE_OAUTH_TOKEN_PREFIX):
        console.print(
            f"[yellow]warning:[/yellow] that doesn't look like a claude setup-token "
            f"(expected {CLAUDE_OAUTH_TOKEN_PREFIX}…). saving it anyway."
        )

    console.print(f"saving [cyan]{CLAUDE_OAUTH_SECRET}[/cyan] via gh secret set...")
    if not _set_gh_secret(name=CLAUDE_OAUTH_SECRET, value=oauth_token, repo_slug=repo_slug):
        _bail(
            f"could not set secret — set it manually at:\n"
            f"  https://github.com/{repo_slug}/settings/secrets/actions"
        )
    console.print(f"[green]saved {CLAUDE_OAUTH_SECRET}[/green] to GitHub Actions secrets")
