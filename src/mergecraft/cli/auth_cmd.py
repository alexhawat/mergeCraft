"""``mergecraft auth`` — Codex device auth / Claude token → ``gh secret set``."""

from __future__ import annotations

import getpass
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, NoReturn

import httpx
import typer
from dotenv import set_key as _dotenv_set_key
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
NOUS_PORTAL_BASE_URL = "https://inference-api.nousresearch.com/v1"
TOKENHUB_API_SECRET = "TOKENHUB_API_KEY"
CLAUDE_OAUTH_TOKEN_PREFIX = "sk-ant-oat"
DEFAULT_NOUS_PORTAL = "https://inference-api.nousresearch.com/v1"
DEFAULT_TOKENHUB = "https://tokenhub-intl.tencentcloudmaas.com/v1"
# Logfire setup (issue #56 / D5). ``LOGFIRE_TOKEN`` is the Action secret the
# ``logfire-token`` input maps to; ``MERGECRAFT_LOGFIRE_TOKEN`` is the
# runtime-only env var the sink factory resolves as a fallback; the project
# label becomes the ``x-logfire-project`` header at runtime.
LOGFIRE_TOKEN_SECRET = "LOGFIRE_TOKEN"
LOGFIRE_RUNTIME_TOKEN_ENV = "MERGECRAFT_LOGFIRE_TOKEN"
LOGFIRE_PROJECT_ENV = "MERGECRAFT_TRACING_PROJECT"
LOGFIRE_PROBE_URL = "https://logfire.pydantic.dev/api/v1/projects"
LogfireScope = Literal["local", "github", "both"]


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


def _validate_nous_api_key(api_key: str) -> bool:
    """Return whether ``api_key`` authenticates against the Nous Portal.

    Probes ``POST {NOUS_PORTAL_BASE_URL}/chat/completions`` with a minimal
    body (``{"model": "deepseek/deepseek-v4-flash", "messages": []}``) and a
    ``Bearer`` auth header. Mirrors ``_validate_gemini_api_key`` semantics:

    - ``200`` → accept (True)
    - ``401`` / ``403`` → reject (False)
    - any other status, ``httpx.HTTPError``, network/DNS/5xx → warn and accept
      (True) so an offline operator can still save the secret locally and
      retry later.

    The probe path is ``/v1/chat/completions`` rather than ``/v1/models``
    because the Portal's catalog endpoint is unauthenticated and would return
    200 even for a fake bearer token (W0.4).
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{NOUS_PORTAL_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": "deepseek/deepseek-v4-flash", "messages": []},
            )
        if response.status_code == 200:
            return True
        if response.status_code in {401, 403}:
            return False
        logger.warning("nous key validation returned HTTP {} — saving anyway", response.status_code)
        return True
    except httpx.HTTPError as exc:
        logger.warning("nous key validation skipped (network): {}", exc)
        return True


@app.command("nous")
def auth_nous() -> None:
    """Save a Nous Portal API key as NOUS_API_KEY."""
    _get_gh_token()
    owner, repo = _parse_git_remote()
    repo_slug = f"{owner}/{repo}"
    console.print(f"detected repo [cyan]{repo_slug}[/cyan]")
    console.print(
        "create an API key at [cyan]https://portal.nousresearch.com[/cyan], then paste it below."
    )
    try:
        api_key = getpass.getpass("Nous Portal API key (Enter to cancel): ").strip()
    except EOFError, KeyboardInterrupt:
        console.print("canceled.")
        raise typer.Exit(0) from None
    if not api_key:
        console.print("canceled.")
        raise typer.Exit(0)
    if not _validate_nous_api_key(api_key):
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


# ---------------------------------------------------------------------------
# ``mergecraft auth logfire`` — Logfire token + project for remote tracing.
# Issue #56 / D5 / D15. The sink type lives behind the optional ``[tracing]``
# extra; this command does not auto-install the extra (BYOK / convention 5).
# ---------------------------------------------------------------------------


def _validate_logfire_token(api_key: str) -> bool:
    """Return whether ``api_key`` authenticates against Logfire.

    Probes ``GET /api/v1/projects`` on the public Logfire ingest host with a
    ``Bearer`` auth header. Mirrors the other validators' contract:

    - ``200`` → accept (True).
    - ``401`` / ``403`` → reject (False).
    - ``3xx`` (redirect — Logfire uses a 302 to the auth flow when the bearer
      is missing/expired) → reject (False). Treating 302 as "saving anyway"
      leaves a token saved that never produces a span silently.
    - any other status, ``httpx.HTTPError``, network/DNS/5xx → warn and accept
      (True) so an offline operator can still save the secret locally and
      retry later.

    The probe path is ``/api/v1/projects`` rather than the OTLP ingest because
    OTLP/HTTP returns 200 even for invalid tokens (it accepts and discards),
    while the projects endpoint enforces the bearer token with a real 401/403.
    """
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False) as client:
            response = client.get(
                LOGFIRE_PROBE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
            )
    except httpx.HTTPError as exc:
        logger.warning("logfire key validation skipped (network): {}", exc)
        return True
    if response.status_code == 200:
        return True
    if response.status_code in {401, 403}:
        return False
    if 300 <= response.status_code < 400:
        # Logfire returns 302 to a sign-in URL when the bearer is missing or
        # expired. A saved token that 302s will never ingest — refuse it now.
        logger.warning(
            "logfire key validation returned HTTP {} (redirect to auth) — token rejected",
            response.status_code,
        )
        return False
    logger.warning(
        "logfire key validation returned HTTP {} — saving anyway",
        response.status_code,
    )
    return True


def _logfire_extra_installed() -> bool:
    """True when the optional ``[tracing]`` extra (``logfire`` package) is present.

    Mirrors ``shutil.which("codex")`` for ``auth_codex``: the auth command
    never auto-installs, but tells the operator what's missing before saving
    a token that will silently no-op until the extra lands.
    """
    try:
        import logfire  # noqa: F401 — import probe only

        return True
    except ImportError:
        return False


def _write_env_value(env_path: Path, key: str, value: str) -> bool:
    """Write ``key=value`` into ``env_path`` idempotently via ``python-dotenv``.

    Returns ``True`` when the write landed, ``False`` when ``python-dotenv``
    failed to update the file (rare — a permissions error on ``.env``). The
    helper is the only code path that writes ``.env``; ``python-dotenv`` is
    already a base dep (``pyproject.toml``) so this adds zero new surface.

    ``set_key`` preserves comments and other keys, creates the file when
    absent, and returns the new value verbatim. We do not return the value to
    the caller — it is already in scope — only success/failure.
    """
    try:
        _dotenv_set_key(str(env_path), key, value, quote_mode="always")
    except OSError as exc:
        logger.warning("dotenv set_key failed for {}: {}", env_path, exc)
        return False
    return True


def _local_env_path() -> Path:
    """Return the local ``.env`` path the auth command writes to.

    Resolution order: ``$MERGECRAFT_ENV`` if set (lets tests pin a temp file),
    otherwise ``./.env`` relative to the current working directory. The
    ``.env.example`` template at the repo root is the documented starting
    point — operators who haven't initialised run ``cp .env.example .env``
    first; the auth command writes into whatever ``.env`` they already have.
    """
    configured = os.environ.get("MERGECRAFT_ENV")
    if configured:
        return Path(configured).resolve()
    return Path.cwd() / ".env"


def _normalise_scope(value: str) -> LogfireScope:
    """Coerce a CLI string into one of ``local`` / ``github`` / ``both``.

    Accepts ``both`` and ``all`` as synonyms (the latter for parity with how
    some operators verbalise it). Anything else bails with a hint that points
    back at ``--help``.
    """
    lowered = value.strip().lower()
    if lowered in {"local"}:
        return "local"
    if lowered in {"github", "gh", "action"}:
        return "github"
    if lowered in {"both", "all"}:
        return "both"
    msg = f"unknown --scope value {value!r}; expected one of: local, github, both"
    _bail(msg)


@app.command("logfire")
def auth_logfire(
    scope: str = typer.Option(
        "both",
        "--scope",
        "-s",
        help=(
            "Where to persist the credentials: 'local' (.env), 'github' "
            "(gh secret set), or 'both' (default). 'both' writes the local "
            ".env AND sets the GitHub Actions secret on the origin repo."
        ),
    ),
) -> None:
    r"""Save a Logfire write token + project for the ``logfire`` tracing sink.

    Writes ``MERGECRAFT_LOGFIRE_TOKEN`` and ``MERGECRAFT_TRACING_PROJECT``
    into the local ``.env`` and/or the ``LOGFIRE_TOKEN`` Actions secret on the
    ``origin`` GitHub repo. After this runs, ``mergecraft diff-review
    --tracing --tracing-to logfire`` ships spans to Logfire; ``mergecraft
    config tracing`` shows the project and a redacted token.

    The ``\[tracing]`` extra must be installed for spans to actually leave
    the runner — install with ``uv pip install 'merge-craft' --extra tracing``
    (or ``uv sync --extra tracing``) when the warning fires.

    NOTE: the ``\[tracing]`` above is literal text, not a Rich markup tag.
    """
    target = _normalise_scope(scope)

    # Probe both halves up front so the operator does not half-save a broken
    # token. Local writes happen after validation; the gh secret set runs
    # last so a failed ``gh auth`` bails before any state changes. ``gh`` is
    # only required when the scope actually writes a secret — local-only
    # operators on a machine without ``gh`` should not be blocked.
    repo_slug: str | None = None
    if target in {"github", "both"}:
        _get_gh_token()
        owner, repo = _parse_git_remote()
        repo_slug = f"{owner}/{repo}"
        console.print(f"detected repo [cyan]{repo_slug}[/cyan]")

    console.print(
        "create a write token at [cyan]https://logfire.pydantic.dev/[/cyan] "
        "(Settings → Write tokens), then paste it below. The token grants "
        "trace ingest for the project you name — keep it out of chat and "
        "logs."
    )
    try:
        token = getpass.getpass("Logfire write token (Enter to cancel): ").strip()
    except EOFError, KeyboardInterrupt:
        console.print("canceled.")
        raise typer.Exit(0) from None
    if not token:
        console.print("canceled.")
        raise typer.Exit(0)
    if not _validate_logfire_token(token):
        _bail(
            "Logfire token validation failed (HTTP 401/403 or auth redirect). "
            "Check the token and retry."
        )

    project = typer.prompt(
        "Logfire project label (Enter to cancel)",
        default="",
        show_default=False,
    ).strip()
    if not project:
        console.print("canceled.")
        raise typer.Exit(0)
    # Same surface as the validator: Logfire accepts arbitrary project strings
    # via the ``x-logfire-project`` header, but reject whitespace inside the
    # label so a stray newline does not silently change the routing key.
    if any(ch.isspace() for ch in project):
        _bail("Logfire project label must not contain whitespace.")

    # Optional-but-loud check: the [tracing] extra must be installed for
    # spans to actually leave the runner. Don't fail closed — the operator
    # may want to set the secret first and install later — but print a clear
    # one-liner so the failure mode is not "nothing happens".
    if not _logfire_extra_installed():
        # The literal `[tracing]` would be parsed as Rich markup inside the
        # `[cyan]` spans, so render the warning in two passes: the colored
        # prefix via markup, then the bracketed install command as plain text.
        console.print(
            "[yellow]warning:[/yellow] the [tracing] extra is not installed.", markup=False
        )
        console.print(
            "Spans will not leave the runner until you run "
            "`uv pip install 'merge-craft' --extra tracing`.",
            markup=False,
        )
        console.print(
            "The token and project were saved regardless — re-running this "
            "command after install is not required.",
            markup=False,
        )

    wrote_local = False
    if target in {"local", "both"}:
        env_path = _local_env_path()
        env_token_ok = _write_env_value(env_path, LOGFIRE_RUNTIME_TOKEN_ENV, token)
        env_project_ok = _write_env_value(env_path, LOGFIRE_PROJECT_ENV, project)
        wrote_local = env_token_ok and env_project_ok
        if wrote_local:
            console.print(
                f"[green]wrote[/green] {LOGFIRE_RUNTIME_TOKEN_ENV} and "
                f"{LOGFIRE_PROJECT_ENV} to {env_path}"
            )
        else:
            # Bandit's B608 fires on the interpolated `env_path`; this is a
            # console warning, not a SQL statement (no DB engine involved).
            console.print(
                f"[yellow]warning:[/yellow] could not update {env_path} "  # nosec B608
                f"— set {LOGFIRE_RUNTIME_TOKEN_ENV} and "
                f"{LOGFIRE_PROJECT_ENV} manually or check file permissions."
            )

    wrote_github = False
    if target in {"github", "both"}:
        assert repo_slug is not None
        console.print(f"saving [cyan]{LOGFIRE_TOKEN_SECRET}[/cyan] via gh secret set...")
        wrote_github = _set_gh_secret(name=LOGFIRE_TOKEN_SECRET, value=token, repo_slug=repo_slug)
        if wrote_github:
            console.print(f"[green]saved {LOGFIRE_TOKEN_SECRET}[/green] to GitHub Actions secrets")
        else:
            console.print(
                f"[yellow]warning:[/yellow] gh secret set failed — set it manually at:\n"
                f"  https://github.com/{repo_slug}/settings/secrets/actions"
            )

    if not wrote_local and not wrote_github:
        _bail(
            "nothing was written — both local and github scopes failed. "
            "retry with --scope local or --scope github to isolate the failure."
        )

    console.print(
        "\n[bold]next steps[/bold]\n"
        f"  - verify wiring: [cyan]mergecraft config tracing[/cyan] "
        f"(token is redacted)\n"
        f"  - run with traces: [cyan]mergecraft diff-review --tracing --tracing-to logfire[/cyan]\n"
        f"  - in the GitHub Action, the workflow can pass "
        f"[cyan]tracing-to: logfire[/cyan] + [cyan]logfire-token: ${{{{ secrets.{LOGFIRE_TOKEN_SECRET} }}}}[/cyan]"
    )
