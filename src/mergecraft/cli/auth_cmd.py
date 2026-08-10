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

import httpx
import typer
from loguru import logger
from rich.console import Console

app = typer.Typer(
    help="Manage provider credentials for the current repository.", no_args_is_help=True
)
console = Console()

CODEX_AUTH_SECRET = "CODEX_AUTH_JSON"
CLAUDE_OAUTH_SECRET = "CLAUDE_CODE_OAUTH_TOKEN"
GEMINI_API_SECRET = "GEMINI_API_KEY"
CURSOR_API_SECRET = "CURSOR_API_KEY"
NOUS_API_SECRET = "NOUS_API_KEY"
TOKENHUB_API_SECRET = "TOKENHUB_API_KEY"
CLAUDE_OAUTH_TOKEN_PREFIX = "sk-ant-oat"
DEFAULT_NOUS_PORTAL = "https://inference-api.nousresearch.com/v1"
DEFAULT_TOKENHUB = "https://tokenhub-intl.tencentcloudmaas.com/v1"


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


def _validate_gemini_api_key(api_key: str) -> bool:
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                params={"key": api_key, "pageSize": 1},
            )
        if response.status_code == 200:
            return True
        if response.status_code in {401, 403}:
            return False
        logger.warning(
            "gemini key validation returned HTTP {} — saving anyway", response.status_code
        )
        return True
    except httpx.HTTPError as exc:
        logger.warning("gemini key validation skipped (network): {}", exc)
        return True


@app.command("gemini")
def auth_gemini() -> None:
    """Save a Gemini API key as GEMINI_API_KEY."""
    _get_gh_token()
    owner, repo = _parse_git_remote()
    repo_slug = f"{owner}/{repo}"
    console.print(f"detected repo [cyan]{repo_slug}[/cyan]")
    console.print(
        "create an API key at [cyan]https://aistudio.google.com/apikey[/cyan], then paste it below."
    )
    try:
        api_key = getpass.getpass("Gemini API key (Enter to cancel): ").strip()
    except EOFError, KeyboardInterrupt:
        console.print("canceled.")
        raise typer.Exit(0) from None
    if not api_key:
        console.print("canceled.")
        raise typer.Exit(0)
    if not _validate_gemini_api_key(api_key):
        _bail("Gemini API key validation failed (401/403). Check the key and retry.")

    console.print(f"saving [cyan]{GEMINI_API_SECRET}[/cyan] via gh secret set...")
    if not _set_gh_secret(name=GEMINI_API_SECRET, value=api_key, repo_slug=repo_slug):
        _bail(
            f"could not set secret — set it manually at:\n"
            f"  https://github.com/{repo_slug}/settings/secrets/actions"
        )
    console.print(f"[green]saved {GEMINI_API_SECRET}[/green] to GitHub Actions secrets")


def _validate_cursor_api_key(api_key: str) -> bool:
    try:
        import base64

        token = base64.b64encode(f"{api_key}:".encode()).decode("ascii")
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                "https://api.cursor.com/v1/agents",
                params={"limit": 1},
                headers={
                    "Authorization": f"Basic {token}",
                    "Accept": "application/json",
                },
            )
        if response.status_code == 200:
            return True
        if response.status_code in {401, 403}:
            return False
        logger.warning(
            "cursor key validation returned HTTP {} — saving anyway", response.status_code
        )
        return True
    except httpx.HTTPError as exc:
        logger.warning("cursor key validation skipped (network): {}", exc)
        return True


@app.command("cursor")
def auth_cursor() -> None:
    """Save a Cursor API key as CURSOR_API_KEY."""
    _get_gh_token()
    owner, repo = _parse_git_remote()
    repo_slug = f"{owner}/{repo}"
    console.print(f"detected repo [cyan]{repo_slug}[/cyan]")
    console.print(
        "create an API key in the Cursor dashboard, then paste it below "
        "(Cloud Agent API — Phase A; local Cursor CLI is not wired yet)."
    )
    try:
        api_key = getpass.getpass("Cursor API key (Enter to cancel): ").strip()
    except EOFError, KeyboardInterrupt:
        console.print("canceled.")
        raise typer.Exit(0) from None
    if not api_key:
        console.print("canceled.")
        raise typer.Exit(0)
    if not _validate_cursor_api_key(api_key):
        _bail("Cursor API key validation failed (401/403). Check the key and retry.")

    console.print(f"saving [cyan]{CURSOR_API_SECRET}[/cyan] via gh secret set...")
    if not _set_gh_secret(name=CURSOR_API_SECRET, value=api_key, repo_slug=repo_slug):
        _bail(
            f"could not set secret — set it manually at:\n"
            f"  https://github.com/{repo_slug}/settings/secrets/actions"
        )
    console.print(f"[green]saved {CURSOR_API_SECRET}[/green] to GitHub Actions secrets")


def _validate_openai_compatible_key(*, api_key: str, base_url: str, label: str) -> bool:
    """GET ``{base}/models`` with a Bearer token; treat 401/403 as invalid."""
    url = base_url.rstrip("/") + "/models"
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                params={"limit": 1},
            )
        if response.status_code == 200:
            return True
        if response.status_code in {401, 403}:
            return False
        logger.warning(
            "{} key validation returned HTTP {} — saving anyway",
            label,
            response.status_code,
        )
        return True
    except httpx.HTTPError as exc:
        logger.warning("{} key validation skipped (network): {}", label, exc)
        return True


@app.command("nous")
def auth_nous() -> None:
    """Save a Nous Portal API key as NOUS_API_KEY."""
    _get_gh_token()
    owner, repo = _parse_git_remote()
    repo_slug = f"{owner}/{repo}"
    console.print(f"detected repo [cyan]{repo_slug}[/cyan]")
    console.print(
        "create an API key in the Nous Portal, then paste it below "
        f"(OpenAI-compatible endpoint [cyan]{DEFAULT_NOUS_PORTAL}[/cyan])."
    )
    try:
        api_key = getpass.getpass("Nous Portal API key (Enter to cancel): ").strip()
    except EOFError, KeyboardInterrupt:
        console.print("canceled.")
        raise typer.Exit(0) from None
    if not api_key:
        console.print("canceled.")
        raise typer.Exit(0)
    if not _validate_openai_compatible_key(
        api_key=api_key, base_url=DEFAULT_NOUS_PORTAL, label="nous"
    ):
        _bail("Nous API key validation failed (401/403). Check the key and retry.")

    console.print(f"saving [cyan]{NOUS_API_SECRET}[/cyan] via gh secret set...")
    if not _set_gh_secret(name=NOUS_API_SECRET, value=api_key, repo_slug=repo_slug):
        _bail(
            f"could not set secret — set it manually at:\n"
            f"  https://github.com/{repo_slug}/settings/secrets/actions"
        )
    console.print(f"[green]saved {NOUS_API_SECRET}[/green] to GitHub Actions secrets")
    console.print(
        "use model [cyan]nous/deepseek/deepseek-v4-flash[/cyan] "
        "(opencode harness; no MERGECRAFT_CUSTOM_PROVIDER_* required)."
    )


@app.command("tokenhub")
def auth_tokenhub() -> None:
    """Save a Tencent TokenHub API key as TOKENHUB_API_KEY."""
    _get_gh_token()
    owner, repo = _parse_git_remote()
    repo_slug = f"{owner}/{repo}"
    console.print(f"detected repo [cyan]{repo_slug}[/cyan]")
    console.print(
        "create an API key in the TokenHub console, then paste it below "
        f"(OpenAI-compatible endpoint [cyan]{DEFAULT_TOKENHUB}[/cyan]; models include "
        "[cyan]hy3[/cyan], DeepSeek, GLM, Kimi)."
    )
    try:
        api_key = getpass.getpass("TokenHub API key (Enter to cancel): ").strip()
    except EOFError, KeyboardInterrupt:
        console.print("canceled.")
        raise typer.Exit(0) from None
    if not api_key:
        console.print("canceled.")
        raise typer.Exit(0)
    if not _validate_openai_compatible_key(
        api_key=api_key, base_url=DEFAULT_TOKENHUB, label="tokenhub"
    ):
        _bail("TokenHub API key validation failed (401/403). Check the key and retry.")

    console.print(f"saving [cyan]{TOKENHUB_API_SECRET}[/cyan] via gh secret set...")
    if not _set_gh_secret(name=TOKENHUB_API_SECRET, value=api_key, repo_slug=repo_slug):
        _bail(
            f"could not set secret — set it manually at:\n"
            f"  https://github.com/{repo_slug}/settings/secrets/actions"
        )
    console.print(f"[green]saved {TOKENHUB_API_SECRET}[/green] to GitHub Actions secrets")
    console.print(
        "use model [cyan]tokenhub/hy3[/cyan] (or any TokenHub model id as "
        "[cyan]tokenhub/<id>[/cyan]; opencode harness)."
    )
