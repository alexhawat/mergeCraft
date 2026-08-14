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
import os
from pathlib import Path
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
from mergecraft.cli.tracing_logfire_wf_yaml import (
    DEFAULT_WORKFLOW_RELATIVE_PATH,
    LogfireWorkflowError,
    apply_logfire_wiring,
    remove_logfire_wiring,
    render_workflow_diff,
)

# ``MERGECRAFT_TRACING_REGION`` selects the Logfire OTLP data region; it is
# written by ``tracing logfire enable --region`` and read by the precedence
# layer alongside the other ``MERGECRAFT_*`` tracing vars.
LOGFIRE_REGION_ENV = "MERGECRAFT_TRACING_REGION"
_VALID_REGIONS = ("us", "eu")

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
        help=(
            "Logfire write token. Precedence: --token flag > "
            "$MERGECRAFT_LOGFIRE_TOKEN in the .env > hidden prompt."
        ),
    ),
    project: str | None = typer.Option(
        None,
        "--project",
        help=(
            "Logfire project label (informational; Logfire routes by token, not a header). "
            "Precedence: --project flag > $MERGECRAFT_TRACING_PROJECT in the "
            ".env > interactive prompt."
        ),
    ),
    scope: str = typer.Option(
        "both",
        "--scope",
        "-s",
        help="Where to persist: 'local' (.env), 'github' (gh secret), or 'both'.",
    ),
    region: str | None = typer.Option(
        None,
        "--region",
        help="Logfire data region for the OTLP endpoint: 'us' or 'eu' (default us).",
    ),
) -> None:
    r"""Enable Logfire tracing by writing the token + project locally and on GitHub.

    Mirrors ``sevn tracing logfire enable --token X --project Y``. Per-key
    precedence (flag > ``$MERGECRAFT_LOGFIRE_TOKEN`` / ``$MERGECRAFT_TRACING_PROJECT``
    in the local ``.env`` — already loaded by ``main()`` — > interactive
    prompt). Each key is resolved independently, so a partial ``.env``
    (token present, project absent) prompts only for the missing piece.

    The token is always validated against Logfire, regardless of source. The
    write-token regex (``pylf_v\{N\}_\{us\|eu\}_…``) routes to the regional
    ``/v1/info`` host; everything else probes the management REST API.
    """
    from mergecraft.cli.auth_cmd import _normalise_scope

    target = _normalise_scope(scope)

    if region is not None:
        region = region.strip().lower()
        if region not in _VALID_REGIONS:
            _bail(f"--region must be one of: {', '.join(_VALID_REGIONS)} (got {region!r}).")

    # Resolve per-key precedence: flag > env (.env, loaded by main()) > prompt.
    # Each key is independent so a partial `.env` (token present, project
    # absent) prompts only for the missing piece.
    token_source: str  # one of "flag" | "env" | "prompt" — used for logging only
    if token is not None and token.strip():
        token_source = "flag"
        token = token.strip()
    else:
        env_token = os.environ.get(LOGFIRE_RUNTIME_TOKEN_ENV, "").strip()
        if env_token:
            token_source = "env"
            token = env_token
        else:
            token_source = "prompt"
            token = getpass.getpass("Logfire write token (Enter to cancel): ").strip()
            if not token:
                console.print("canceled.")
                raise typer.Exit(0)

    project_source: str
    if project is not None and project.strip():
        project_source = "flag"
        project = project.strip()
    else:
        env_project = os.environ.get(LOGFIRE_PROJECT_ENV, "").strip()
        if env_project:
            project_source = "env"
            project = env_project
        else:
            project_source = "prompt"
            import typer as _typer

            project = _typer.prompt("Logfire project label").strip()
            if not project:
                _bail("--project is required (logfire is a named export target).")

    # Always validate the token before writing — flag, env, or prompt.
    # The flag/env paths skip re-prompting; this probe is the only guarantee
    # that the operator has a credential that actually ingests.
    if not _validate_logfire_token(token):
        _bail(
            "Logfire token validation failed (HTTP 401/403 or auth redirect). "
            "Check the token and retry."
        )

    if any(ch.isspace() for ch in project):
        _bail("Logfire project label must not contain whitespace.")

    console.print(f"[dim]resolved token via {token_source}; project via {project_source}[/dim]")

    wrote_local = False
    if target in {"local", "both"}:
        env_path = _local_env_path()
        env_token_ok = _write_env_value(env_path, LOGFIRE_RUNTIME_TOKEN_ENV, token)
        env_project_ok = _write_env_value(env_path, LOGFIRE_PROJECT_ENV, project)
        # ``--region`` (when given) is persisted so ``config tracing`` and the
        # sink factory pick it up through the same ``MERGECRAFT_*`` seam as
        # the token; it never lands in the model dump / config on disk.
        env_region_ok = True
        if region is not None:
            env_region_ok = _write_env_value(env_path, LOGFIRE_REGION_ENV, region)
        # Flips the master switch so ``mergecraft config tracing`` reports
        # enabled after this command runs (the env layer's ``MERGECRAFT_TRACING``
        # is the only local-side knob that sets ``enabled=true``).
        env_enable_ok = _write_env_value(env_path, "MERGECRAFT_TRACING", "true")
        wrote_local = env_token_ok and env_project_ok and env_region_ok and env_enable_ok
        if wrote_local:
            console.print(
                f"[green]wrote[/green] {LOGFIRE_RUNTIME_TOKEN_ENV}, "
                f"{LOGFIRE_PROJECT_ENV} and MERGECRAFT_TRACING to {env_path}"
            )
            if region is not None:
                console.print(f"[green]wrote[/green] {LOGFIRE_REGION_ENV}={region} to {env_path}")
        else:
            # Bandit's B608 fires on the interpolated `env_path`; this is a
            # console warning, not a SQL statement (no DB engine involved).
            console.print(
                f"[yellow]warning:[/yellow] could not update {env_path} "  # nosec B608
                f"— set {LOGFIRE_RUNTIME_TOKEN_ENV}, {LOGFIRE_PROJECT_ENV} "
                f"and MERGECRAFT_TRACING manually or check file permissions."
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
        # Clear the master switch too so ``mergecraft config tracing`` reports
        # disabled again.
        env_enable_ok = _write_env_value(env_path, "MERGECRAFT_TRACING", "")
        wrote_local = env_token_ok and env_project_ok and env_enable_ok
        if wrote_local:
            console.print(
                f"[green]cleared[/green] {LOGFIRE_RUNTIME_TOKEN_ENV}, "
                f"{LOGFIRE_PROJECT_ENV} and MERGECRAFT_TRACING in {env_path}"
            )
        else:
            console.print(
                f"[yellow]warning:[/yellow] could not clear {env_path} — unset "
                f"{LOGFIRE_RUNTIME_TOKEN_ENV}, {LOGFIRE_PROJECT_ENV} and "
                f"MERGECRAFT_TRACING manually."
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


# ---------------------------------------------------------------------------
# Workflow wiring
# ---------------------------------------------------------------------------
#
# These two subcommands surgically mutate ``.github/workflows/<file>`` to add
# or remove the four YAML keys mergeCraft consumes when Logfire is wired into
# the Action:
#
# - ``with.tracing: "true"``
# - ``with.tracing-to: logfire``
# - ``with.logfire-token: ${{ secrets.<secret> }}``
# - ``env.MERGECRAFT_TRACING_PROJECT: ${{ vars.<project-var> }}``
#
# The mutator is regex-based, PyYAML only parses for dispatch + assertions.
# Regex preserves all other YAML content (inline ``#`` comments, ``on:`` block,
# bracketed multi-line strings) untouched on no-op edits. PyYAML's round-trip
# would strip the documented ``#`` comments above the action step on re-dump;
# see ``tracing_logfire_wf_yaml`` for the rationale.


@logfire_app.command("wire-workflow")
def logfire_wire_workflow(
    workflow: Path = typer.Option(
        Path(DEFAULT_WORKFLOW_RELATIVE_PATH),
        "--workflow",
        "-w",
        help="Path to the consumer workflow YAML (default: .github/workflows/mergecraft.yml).",
        exists=False,
    ),
    secret: str = typer.Option(
        LOGFIRE_TOKEN_SECRET,
        "--secret",
        help=(
            "Name of the GitHub Actions secret holding the Logfire write token "
            "(default: LOGFIRE_TOKEN). Written into the ``with.logfire-token:`` "
            "field as ``${{ secrets.<secret> }}`` — the literal secret value "
            "never appears in the workflow file."
        ),
    ),
    project_var: str = typer.Option(
        "LOGFIRE_PROJECT",
        "--project-var",
        help=(
            "Name of the GitHub Actions variable holding the Logfire project "
            "label (default: LOGFIRE_PROJECT). Written into the action step's "
            "``env.MERGECRAFT_TRACING_PROJECT:`` field as ``${{ vars.<project-var> }}``."
        ),
    ),
    step: str = typer.Option(
        "primary",
        "--step",
        help=(
            "Which ``uses: alexhawat/mergecraft@…`` step to wire. "
            "``primary`` (default) wires the first match; ``all`` wires every "
            "match. Pass the step's ``id:`` attribute (or ``name:`` value) to "
            "target a specific step exactly."
        ),
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write the change to disk. Default is dry-run — prints the unified diff and exits 0.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help=(
            "Overwrite existing tracing-related keys whose values differ from "
            "what would be written. Without ``--force``, an existing ``tracing:`` "
            "or ``tracing-to:`` whose value does not match the canonical Logfire "
            "wiring is left alone and the command exits 1."
        ),
    ),
) -> None:
    r"""Wire Logfire tracing into the consumer workflow.

    Example::

        mergecraft tracing logfire wire-workflow
        mergecraft tracing logfire wire-workflow --workflow .github/workflows/ci.yml \
            --secret LOGFIRE_TOKEN --project-var LOGFIRE_PROJECT --apply

    Refuses to add an obvious mismatch (e.g. existing ``tracing-to: otel``)
    unless ``--force`` is given. Dry-run by default; ``--apply`` writes.
    """
    if not secret:
        _bail("--secret cannot be empty")
    if not project_var:
        _bail("--project-var cannot be empty")
    try:
        proposed = apply_logfire_wiring(
            workflow_path=workflow,
            secret_name=secret,
            project_var_name=project_var,
            step_selector=step,
            force=force,
        )
    except LogfireWorkflowError as exc:
        _bail(str(exc))

    if proposed.was_modified:
        diff_text = render_workflow_diff(workflow, proposed)
        console.print(diff_text)
    else:
        console.print(f"[dim]{workflow} already wired for Logfire; no changes needed.[/dim]")

    if not apply:
        console.print("[dim]dry-run (re-run with --apply to write)[/dim]")
        raise typer.Exit(0)

    try:
        workflow.write_text(proposed.new_text, encoding="utf-8")
    except OSError as exc:
        _bail(f"could not write {workflow}: {exc}")
    console.print(f"[green]wrote[/green] {workflow}")


@logfire_app.command("unwire-workflow")
def logfire_unwire_workflow(
    workflow: Path = typer.Option(
        Path(DEFAULT_WORKFLOW_RELATIVE_PATH),
        "--workflow",
        "-w",
        help="Path to the consumer workflow YAML (default: .github/workflows/mergecraft.yml).",
        exists=False,
    ),
    step: str = typer.Option(
        "primary",
        "--step",
        help=(
            "Which ``uses: alexhawat/mergecraft@…`` step to unwire. "
            "Same selectors as ``wire-workflow``: ``primary``, ``all``, or the "
            "step's ``id:`` / ``name:``."
        ),
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write the change to disk. Default is dry-run.",
    ),
) -> None:
    r"""Remove Logfire tracing wiring from the consumer workflow.

    Strips the four keys this command owns (``with.tracing``,
    ``with.tracing-to``, ``with.logfire-token``, and
    ``env.MERGECRAFT_TRACING_PROJECT``) from every matched ``uses:`` step and
    leaves all other YAML content untouched. Pair with
    ``mergecraft tracing logfire disable`` to clear the local ``.env`` and the
    GitHub Actions ``LOGFIRE_TOKEN`` secret symmetrically.

    Dry-run by default; ``--apply`` writes.
    """
    try:
        proposed = remove_logfire_wiring(
            workflow_path=workflow,
            step_selector=step,
        )
    except LogfireWorkflowError as exc:
        _bail(str(exc))

    if proposed.was_modified:
        diff_text = render_workflow_diff(workflow, proposed)
        console.print(diff_text)
    else:
        console.print(f"[dim]{workflow} had no Logfire wiring; no changes needed.[/dim]")

    if not apply:
        console.print("[dim]dry-run (re-run with --apply to write)[/dim]")
        raise typer.Exit(0)

    try:
        workflow.write_text(proposed.new_text, encoding="utf-8")
    except OSError as exc:
        _bail(f"could not write {workflow}: {exc}")
    console.print(f"[green]wrote[/green] {workflow}")

    console.print("\n[bold]Logfire tracing disabled.[/bold]")


def register(root: typer.Typer) -> None:
    """Attach the ``tracing`` Typer subapp to ``root``."""
    root.add_typer(app, name="tracing")


__all__ = [
    "app",
    "logfire_app",
    "logfire_disable",
    "logfire_enable",
    "logfire_unwire_workflow",
    "logfire_wire_workflow",
    "register",
]
