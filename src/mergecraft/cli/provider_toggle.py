"""``mergecraft provider enable|disable`` — provider on/off switches (#520).

Where :mod:`mergecraft.cli.auth_cmd` and ``mergecraft provider auth`` are the
*set* half of provider credentials, this module is the missing *unset* half.
It mirrors the ``mergecraft tracing logfire enable|disable`` contract exactly:
the same ``--scope local|github|both`` option, the same "delete the Actions
secret, blank the ``.env`` entry" post-condition, and the same treatment of an
already-absent secret as success rather than an error.

Disabling a provider removes its **credentials**, not its registration. The
``providers:`` row and its ``LLM_PROVIDER_<N>`` label survive, so ``provider
enable`` can re-authenticate the same env index without re-adding the row. Use
``mergecraft provider delete`` to drop the registration itself.

This lives outside :mod:`mergecraft.cli.provider_cmd` deliberately: that module
is already 1200+ lines and is claimed by concurrent work, so the toggle keeps
its own file and is attached to the existing ``provider`` Typer app by
:func:`register`.

Every destructive target is resolved from ``--cwd``, not from the process
working directory, so the repository whose registry is read is the same one
whose ``.env`` is blanked and whose Actions secrets are deleted.

Exports:
    ProviderSecrets -- the Actions-secret and ``.env`` key names for one label.
    resolve_provider_secrets -- map a provider label to those names.
    resolve_local_env_path -- the ``.env`` a given ``--cwd`` may blank.
    resolve_repo_slug -- the ``owner/repo`` a given ``--cwd`` may delete from.
    register -- attach ``enable``/``disable`` to the ``provider`` Typer app.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

# Provider labels whose credentials predate the indexed ``LLM_PROVIDER_<N>_*``
# registry and are still what the shipped consumer workflow references by name.
# ``mergecraft auth <name>`` writes these, so ``provider disable`` has to clear
# them too — clearing only the indexed keys would leave CI fully authenticated
# and make the command a silent no-op.
#
# Keys are the *canonical registry label*; ``_LABEL_ALIASES`` maps the
# ``auth`` subcommand names onto them so ``provider disable codex`` and
# ``provider disable openai`` mean the same thing.
_FLAT_SECRETS_BY_LABEL: dict[str, tuple[str, ...]] = {
    "openai": ("CODEX_AUTH_JSON", "OPENAI_API_KEY"),
    "anthropic": ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY"),
    # Both names are recognised credentials for Google: ``models.py`` lists
    # them as that provider's ``env_vars`` and ``docs/authentication.md``
    # documents the alias. Clearing only ``GEMINI_API_KEY`` would report the
    # provider disabled while it stayed authenticated through the alias.
    "google": ("GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"),
    "cursor": ("CURSOR_API_KEY",),
    "deepseek": ("DEEPSEEK_API_KEY",),
    "nous": ("NOUS_API_KEY",),
    "tokenhub": ("TOKENHUB_API_KEY",),
    "minimax": ("MERGECRAFT_CUSTOM_PROVIDER_API_KEY",),
    "bedrock": (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ),
    "vertex": ("GOOGLE_APPLICATION_CREDENTIALS",),
}

# ``mergecraft auth <name>`` subcommand names that are not themselves registry
# labels. ``codex``/``claude`` are harness names for the ``openai``/``anthropic``
# providers; ``gemini`` is the API-key name for ``google``.
_LABEL_ALIASES: dict[str, str] = {
    "codex": "openai",
    "claude": "anthropic",
    "gemini": "google",
}


@dataclass(frozen=True, slots=True)
class ProviderSecrets:
    """Every credential name one provider label owns, split by where it lives.

    ``github`` names Actions secrets to delete; ``local`` names ``.env`` keys to
    blank. They overlap heavily by design — a flat credential like
    ``NOUS_API_KEY`` is both — but the indexed registry keys and the flat
    workflow-facing keys are collected together so a single disable clears the
    provider however it happened to be authenticated.
    """

    label: str
    github: tuple[str, ...]
    local: tuple[str, ...]

    def __bool__(self) -> bool:
        return bool(self.github or self.local)


def canonical_provider_label(label: str) -> str:
    """Return the registry label *label* refers to, resolving ``auth`` aliases."""
    lowered = label.strip().lower()
    return _LABEL_ALIASES.get(lowered, lowered)


def resolve_provider_secrets(
    label: str,
    entry: Mapping[str, Any] | None = None,
) -> ProviderSecrets:
    """Return every credential name to clear when disabling *label*.

    *entry* is the ``providers:`` registry row when the label is registered; its
    ``envIndex``/``authKind`` yield the indexed ``LLM_PROVIDER_<N>_*`` keys. An
    unregistered label still resolves when it is a known built-in, so a provider
    authenticated through ``mergecraft auth <name>`` before the registry existed
    can still be turned off.
    """
    from mergecraft.cli.provider_cmd import indexed_credential_keys

    canonical = canonical_provider_label(label)
    names: list[str] = list(_FLAT_SECRETS_BY_LABEL.get(canonical, ()))

    if entry is not None and entry.get("envIndex") is not None:
        for key in indexed_credential_keys(entry):
            if key not in names:
                names.append(key)

    return ProviderSecrets(label=canonical, github=tuple(names), local=tuple(names))


def _clear_local(secrets: ProviderSecrets, env_path: Path) -> tuple[list[str], list[str]]:
    """Blank every ``.env`` entry in *secrets*, returning ``(cleared, failed)``.

    Entries are blanked rather than deleted, matching ``tracing logfire
    disable``: the key stays present so the operator can see what the repo
    expects and re-enable in place.
    """
    from mergecraft.cli.auth_cmd import _write_env_value

    cleared: list[str] = []
    failed: list[str] = []
    # Not short-circuited — a failure on one key must not strand the rest.
    for key in secrets.local:
        if _write_env_value(env_path, key, ""):
            cleared.append(key)
        else:
            failed.append(key)
    return cleared, failed


def _delete_github(secrets: ProviderSecrets, repo_slug: str) -> tuple[list[str], list[str]]:
    """Delete every Actions secret in *secrets*, returning ``(deleted, failed)``.

    An absent secret counts as deleted: the post-condition the operator asked
    for is "the secret is not set", and ``gh secret delete`` exits non-zero for
    both "did not exist" and "could not reach GitHub". ``_delete_gh_secret``
    already distinguishes the two.
    """
    from mergecraft.cli.tracing_logfire_cmd import _delete_gh_secret

    deleted: list[str] = []
    failed: list[str] = []
    for name in secrets.github:
        if _delete_gh_secret(name=name, repo_slug=repo_slug):
            deleted.append(name)
        else:
            failed.append(name)
    return deleted, failed


def resolve_local_env_path(cwd: Path) -> Path:
    """Return the ``.env`` this invocation may blank, anchored on *cwd*.

    ``--cwd`` selects which repository the command acts on, so the destructive
    local target must follow it. Anchoring on the *process* working directory
    instead would read the registry from one repository and blank the ``.env``
    of another — the operator would be told a provider was disabled in a repo
    the command never touched.

    ``MERGECRAFT_ENV`` still wins, matching
    :func:`mergecraft.cli.auth_cmd._local_env_path`: an operator who has pinned
    an explicit env file has named the target unambiguously.
    """
    import os

    from mergecraft.utils.workspace import git_repo_root

    configured = os.environ.get("MERGECRAFT_ENV")
    if configured:
        return Path(configured).resolve()

    resolved = cwd.resolve()
    root = git_repo_root(str(resolved))
    if root is None:
        cli_bail(
            f"could not locate a git repository root at {resolved} — run from "
            "inside the repository, pass --cwd, or point MERGECRAFT_ENV at the "
            ".env you want cleared."
        )
    return root / ".env"


def resolve_repo_slug(cwd: Path) -> str:
    """Return ``owner/repo`` for the origin remote of the repository at *cwd*.

    The GitHub half of the same problem as :func:`resolve_local_env_path`:
    ``gh secret delete`` must target the repository ``--cwd`` names, not
    whichever repository the operator happens to be standing in.
    """
    import re
    import subprocess

    from mergecraft.utils.git_hardening import git_argv

    resolved = cwd.resolve()
    try:
        url = subprocess.check_output(
            git_argv(["remote", "get-url", "origin"]),
            cwd=str(resolved),
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except (subprocess.SubprocessError, OSError) as exc:
        cli_bail(f"could not read the git origin remote at {resolved}: {exc}")
    match = re.search(r"github\.com(?::\d+)?[:/]+([^/]+)/(.+?)(?:\.git)?(?:/)?$", url)
    if not match:
        cli_bail(f"could not parse a github owner/repo from the remote at {resolved}: {url}")
    return f"{match.group(1)}/{match.group(2)}"


def _lookup_entry(label: str, cwd: Path) -> Mapping[str, Any] | None:
    """Return the ``providers:`` row for *label*, or ``None`` when unregistered."""
    from mergecraft.cli.provider_cmd import _config_path, load_provider_registry

    registry = load_provider_registry(_config_path(cwd.resolve()))
    canonical = canonical_provider_label(label)
    return registry.lookup(canonical) or registry.lookup(label.strip())


def _reject_logfire(label: str) -> None:
    """Bail when *label* is Logfire, which has its own toggle."""
    if canonical_provider_label(label) == "logfire":
        cli_bail(
            "logfire is telemetry, not an LLM provider — use "
            "[cyan]mergecraft tracing logfire disable[/cyan] instead."
        )


def _require_label(label: str) -> str:
    """Return *label* stripped, bailing on an empty argument."""
    normalised = label.strip()
    if not normalised:
        cli_bail("provider label must not be empty", code=CLI_USAGE_EXIT_CODE)
    return normalised


_SCOPE_OPTION: str = typer.Option(
    "github",
    "--scope",
    "-s",
    help=("Where to act: 'local' (.env only), 'github' (Actions secrets, the default), or 'both'."),
)

_CWD_OPTION: Path = typer.Option(Path("."), "--cwd", help="Repository root.")


def provider_disable_cmd(
    label: str = typer.Argument(..., help="Provider label to disable."),
    scope: str = _SCOPE_OPTION,
    cwd: Path = _CWD_OPTION,
) -> None:
    """Clear one provider's credentials so GitHub CI and the local CLI stop using it.

    The ``providers:`` registration is left alone — this is the inverse of
    ``provider auth``, not of ``provider add``. Workflow YAML is never rewritten;
    the shipped cascade already no-ops a provider whose secret is absent.
    """
    from mergecraft.cli.auth_cmd import _normalise_scope

    normalised = _require_label(label)
    _reject_logfire(normalised)
    target = _normalise_scope(scope)

    entry = _lookup_entry(normalised, cwd)
    secrets = resolve_provider_secrets(normalised, entry)
    if not secrets:
        cli_bail(
            f"unknown provider label {normalised!r} — it is not registered and is "
            "not a built-in provider. Run [cyan]mergecraft provider list[/cyan] to "
            "see registered labels."
        )

    # "Disabled" is an all-or-nothing claim about the provider, not about one
    # key. A provider stays usable through ANY of its credentials, so a single
    # surviving key means it is not disabled — reporting success because some
    # *other* key was already absent would be the exact failure the operator
    # asked this command to prevent. Every unresolved key is collected and the
    # command bails naming them.
    unresolved: list[str] = []

    if target in {"local", "both"}:
        env_path = resolve_local_env_path(cwd)
        cleared_local, failed_local = _clear_local(secrets, env_path)
        if cleared_local:
            console.print(f"[green]cleared[/green] {', '.join(cleared_local)} in {env_path}")
        if failed_local:
            console.print(
                f"[yellow]warning:[/yellow] could not clear "
                f"{', '.join(failed_local)} in {env_path} — unset them manually."
            )
            unresolved.extend(f"{key} (.env)" for key in failed_local)

    if target in {"github", "both"}:
        repo_slug = resolve_repo_slug(cwd)
        console.print(
            f"deleting [cyan]{', '.join(secrets.github)}[/cyan] via gh secret delete "
            f"on [cyan]{repo_slug}[/cyan]..."
        )
        deleted_github, failed_github = _delete_github(secrets, repo_slug)
        if deleted_github:
            console.print(
                f"[green]deleted {', '.join(deleted_github)}[/green] from GitHub "
                "Actions secrets (absent counts as deleted)"
            )
        if failed_github:
            console.print(
                f"[yellow]warning:[/yellow] gh secret delete failed for "
                f"{', '.join(failed_github)} — remove them manually at:\n"
                f"  https://github.com/{repo_slug}/settings/secrets/actions"
            )
            unresolved.extend(f"{name} (Actions secret)" for name in failed_github)

    if unresolved:
        cli_bail(
            f"{secrets.label} is NOT disabled — {len(unresolved)} credential(s) "
            f"could not be cleared: {', '.join(unresolved)}. The provider stays "
            "usable through any one of them; clear the listed credentials and "
            "re-run."
        )

    console.print(f"\n[bold]Provider {secrets.label} disabled.[/bold]")
    console.print(
        f"the registry entry is untouched — re-enable with "
        f"[cyan]mergecraft provider enable {secrets.label}[/cyan]."
    )


def provider_enable_cmd(
    label: str = typer.Argument(..., help="Provider label to enable."),
    scope: str = _SCOPE_OPTION,
    cwd: Path = _CWD_OPTION,
) -> None:
    """Authenticate one provider — the enable half of the toggle.

    This is the existing ``provider auth`` flow under the name that pairs with
    ``disable``; no new credential-minting path is introduced.
    """
    from mergecraft.cli.provider_cmd import (
        _config_path,
        load_provider_registry,
        run_provider_auth,
    )

    normalised = _require_label(label)
    _reject_logfire(normalised)

    repo_root = cwd.resolve()
    registry = load_provider_registry(_config_path(repo_root))
    canonical = canonical_provider_label(normalised)
    entry = registry.lookup(canonical) or registry.lookup(normalised)
    if entry is None:
        cli_bail(
            f"unknown provider label {normalised!r} — register it first with "
            f"[cyan]mergecraft provider add {canonical}[/cyan]."
        )

    console.print(f"enabling provider [cyan]{entry.get('label', canonical)}[/cyan]")
    run_provider_auth(entry, scope, cwd=repo_root)


def register(provider_app: typer.Typer) -> None:
    """Attach ``enable`` and ``disable`` to the ``provider`` Typer app."""
    provider_app.command("enable")(provider_enable_cmd)
    provider_app.command("disable")(provider_disable_cmd)


__all__ = [
    "ProviderSecrets",
    "canonical_provider_label",
    "provider_disable_cmd",
    "provider_enable_cmd",
    "register",
    "resolve_local_env_path",
    "resolve_provider_secrets",
    "resolve_repo_slug",
]
