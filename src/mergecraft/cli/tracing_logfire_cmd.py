"""``mergecraft tracing logfire enable|disable`` subcommands (issue #56 follow-up).

Symmetric with sevn's ``sevn tracing logfire enable|disable`` (`specs/04-tracing.md`).
Where :mod:`mergecraft.cli.auth_cmd` is the *interactive* setup (prompt for token,
prompt for project, validate against the Logfire REST API), this module is the
*non-interactive* counterpart — an operator-facing toggle that reads ``--token`` /
``--project`` from flags, validates the bearer (when given), and writes the
same two env vars + the same ``LOGFIRE_TOKEN`` Actions secret.

Exports:
    register -- attach the ``tracing`` Typer subapp to the root CLI.
"""

from __future__ import annotations

import getpass
from typing import NoReturn

import typer
from rich.console import Console

from mergecraft.cli.auth_cmd import (
    LOGFIRE_PROJECT_ENV,
    LOGFIRE_RUNTIME_TOKEN_ENV,
    LOGFIRE_TOKEN_SECRET,
    _local_env_path,
    _set_gh_secret,
    _validate_logfire_token,
    _write_env_value,
)

app = typer.Typer(
    name="tracing",
    help="Trace export configuration (Logfire). Mirrors ``sevn tracing logfire``.",
    no_args_is_help=True,
)
console = Console(stderr=True)

logfire_app = typer.Typer(
    name="logfire",
    help="Logfire trace export. Mirrors ``sevn tracing logfire``.",
    no_args_is_help=True,
)
app.add_typer(logfire_app, name="logfire")


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _delete_gh_secret(*, name: str, repo_slug: str) -> bool:
    """Best-effort ``gh secret delete`` on the origin repo.

    Returns ``True`` when the secret was absent or successfully removed; ``False``
    when ``gh`` failed (e.g. unauthenticated) so the operator can clean up via
    the repository UI.
    """
    import subprocess

    try:
        completed = subprocess.run(  # nosec B603 B607 — fixed argv, gh binary
            ["gh", "secret", "delete", name, "--repo", repo_slug],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return False
    if completed.returncode == 0:
        return True
    # ``gh secret delete`` exits 1 when the secret does not exist — treat as
    # success because the post-condition we want (secret is absent) holds.
    return "not found" in (completed.stderr or "").lower()


def _parse_repo_slug() -> str:
    """Return ``owner/repo`` from the local origin remote.

    Raises on parse failure so the operator knows the disable ran locally only.
    """
    import re
    import subprocess

    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        _bail(f"could not read git origin remote: {exc}")
    match = re.search(r"github\.com(?::\d+)?[:/]+([^/]+)/(.+?)(?:\.git)?(?:/)?$", url)
    if not match:
        _bail(f"could not parse github owner/repo from remote: {url}")
    return f"{match.group(1)}/{match.group(2)}"


@logfire_app.command("enable")
def logfire_enable(
    token: str | None = typer.Option(
        None,
        "--token",
        help="Logfire write token. When omitted, the prompt asks for one (hidden).",
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help="Logfire project label (becomes the ``x-logfire-project`` header).",
    ),
    scope: str = typer.Option(
        "both",
        "--scope",
        "-s",
        help="Where to persist: 'local' (.env), 'github' (gh secret), or 'both'.",
    ),
) -> None:
    """Enable Logfire tracing by writing the token + project locally and on GitHub.

    Mirrors ``sevn tracing logfire enable --token X --project Y``. When ``--token``
    is omitted the command reads the token via ``getpass`` so it does not appear
    in shell history. ``--project`` is required; the ``logfire`` sink is a
    *named* export target and the operator must own the project label.
    """
    from mergecraft.cli.auth_cmd import _normalise_scope

    target = _normalise_scope(scope)

    if token is None:
        token = getpass.getpass("Logfire write token (Enter to cancel): ").strip()
    if not token:
        console.print("canceled.")
        raise typer.Exit(0)

    if project is None or not project.strip():
        _bail("--project is required (logfire is a named export target).")

    if not _validate_logfire_token(token):
        _bail(
            "Logfire token validation failed (HTTP 401/403 or auth redirect). "
            "Check the token and retry."
        )

    project = project.strip()
    if any(ch.isspace() for ch in project):
        _bail("Logfire project label must not contain whitespace.")

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
        repo_slug = _parse_repo_slug()
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
        f"\n[bold]Logfire tracing enabled ([/bold][cyan]project={project}[/cyan][bold])[/bold]"
    )


@logfire_app.command("disable")
def logfire_disable(
    scope: str = typer.Option(
        "both",
        "--scope",
        "-s",
        help="Where to clear: 'local' (.env keys), 'github' (gh secret), or 'both'.",
    ),
) -> None:
    """Disable Logfire tracing by removing the token + project locally and on GitHub.

    Mirrors ``sevn tracing logfire disable``. The local ``.env`` keys are
    cleared via :func:`python_dotenv.set_key` with an empty value so the
    operator can re-enable without first re-installing the package. The
    GitHub secret is removed via ``gh secret delete``; a missing secret is
    treated as success (the post-condition — secret is absent — already holds).
    """
    from mergecraft.cli.auth_cmd import _normalise_scope

    target = _normalise_scope(scope)

    wrote_local = False
    if target in {"local", "both"}:
        env_path = _local_env_path()
        # ``set_key`` with an empty value still rewrites the line, so the key
        # is present (for re-enable) but blank.
        env_token_ok = _write_env_value(env_path, LOGFIRE_RUNTIME_TOKEN_ENV, "")
        env_project_ok = _write_env_value(env_path, LOGFIRE_PROJECT_ENV, "")
        wrote_local = env_token_ok and env_project_ok
        if wrote_local:
            console.print(
                f"[green]cleared[/green] {LOGFIRE_RUNTIME_TOKEN_ENV} and "
                f"{LOGFIRE_PROJECT_ENV} in {env_path}"
            )
        else:
            console.print(
                f"[yellow]warning:[/yellow] could not clear {env_path} — unset "
                f"{LOGFIRE_RUNTIME_TOKEN_ENV} and {LOGFIRE_PROJECT_ENV} manually."
            )

    wrote_github = False
    if target in {"github", "both"}:
        repo_slug = _parse_repo_slug()
        console.print(f"deleting [cyan]{LOGFIRE_TOKEN_SECRET}[/cyan] via gh secret delete...")
        wrote_github = _delete_gh_secret(name=LOGFIRE_TOKEN_SECRET, repo_slug=repo_slug)
        if wrote_github:
            console.print(
                f"[green]deleted {LOGFIRE_TOKEN_SECRET}[/green] from GitHub Actions secrets"
            )
        else:
            console.print(
                f"[yellow]warning:[/yellow] gh secret delete failed — remove it "
                f"manually at:\n  https://github.com/{repo_slug}/settings/secrets/actions"
            )

    if not wrote_local and not wrote_github:
        _bail(
            "nothing was cleared — both local and github scopes failed. "
            "retry with --scope local or --scope github to isolate the failure."
        )

    console.print("\n[bold]Logfire tracing disabled.[/bold]")


def register(root: typer.Typer) -> None:
    """Attach the ``tracing`` Typer subapp to ``root``."""
    root.add_typer(app, name="tracing")


__all__ = ["app", "logfire_app", "logfire_disable", "logfire_enable", "register"]
