"""``mergecraft provider`` — operator provider registry (#477 / BA)."""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
import yaml

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE
from mergecraft.config.provider_registry import (
    BUILTIN_HARNESS_DEFAULTS,
    allocate_env_index,
    default_auth_kind_for_label,
    default_harness_for_label,
    harness_supports_provider,
    list_supported_harnesses,
    supported_harness_names,
    validate_http_url,
)
from mergecraft.config.runtime_provider_registry import SEED_PROVIDER_URLS
from mergecraft.config.settings import _DEFAULT_CONFIG_REL
from mergecraft.models import PROVIDERS

AUTH_KIND_API_KEY = "api_key"
AUTH_KIND_OAUTH = "oauth"
AUTH_KIND_DEVICE_CODE = "device_code"
AUTH_KIND_CLOUD_CHAIN = "cloud_chain"

AUTH_KIND_PRIMARY_SUFFIX: dict[str, str] = {
    AUTH_KIND_API_KEY: "API_KEY",
    AUTH_KIND_OAUTH: "CLAUDE_CODE_OAUTH_TOKEN",
    AUTH_KIND_DEVICE_CODE: "CODEX_AUTH_JSON",
}

BEDROCK_CLOUD_SUFFIXES: tuple[str, ...] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)

VERTEX_CLOUD_SUFFIXES: tuple[str, ...] = ("GOOGLE_APPLICATION_CREDENTIALS",)

_PROVIDER_AUTH_SCOPE_OPTION: str = typer.Option(
    "github",
    "--scope",
    "-s",
    help=(
        "Where to persist credentials: 'local' (.env only), 'github' "
        "(gh secret set, the default), or 'both'."
    ),
)

app = typer.Typer(
    help="Add, list, edit, and delete LLM providers in the operator registry.",
    no_args_is_help=True,
)


@dataclass(frozen=True, slots=True)
class ProviderRegistry:
    """In-memory view of ``providers:`` from config (no ``PROVIDERS`` consult)."""

    entries: tuple[dict[str, Any], ...]

    def get(self, label: str) -> dict[str, Any] | None:
        return self.lookup(label)

    def lookup(self, label: str) -> dict[str, Any] | None:
        lowered = label.strip().lower()
        for entry in self.entries:
            if str(entry.get("label", "")).lower() == lowered:
                return entry
        return None

    def labels(self) -> list[str]:
        return [str(entry["label"]) for entry in self.entries if entry.get("label")]


def _config_path(cwd: Path) -> Path:
    return (cwd / _DEFAULT_CONFIG_REL).resolve()


def _env_path() -> Path:
    configured = os.environ.get("MERGECRAFT_ENV")
    if configured:
        return Path(configured).resolve()
    return Path.cwd() / ".env"


def _load_config_dict(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        cli_bail(f"config must be a mapping: {path}")
    return loaded


def _write_config_dict(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _provider_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("providers")
    if raw is None:
        return []
    if not isinstance(raw, list):
        cli_bail("providers must be a list in config")
    return [entry for entry in raw if isinstance(entry, dict)]


def _write_env_label(env_index: int, label: str) -> None:
    from mergecraft.cli.auth_cmd import _write_env_value

    key = f"LLM_PROVIDER_{env_index}"
    _write_env_value(_env_path(), key, label)


def _harness_help_suffix() -> str:
    names = ", ".join(sorted(supported_harness_names()))
    return f"supported harness values: {names}"


def resolve_provider_harness(label: str, *, harness: str | None = None) -> str:
    """Resolve harness for *label*; unknown labels never default to ``opencode`` (D4)."""
    normalised = label.strip().lower()
    if harness is not None:
        harness_value = harness.strip().lower()
        if harness_value not in supported_harness_names():
            msg = f"unknown harness {harness!r}; {_harness_help_suffix()}"
            raise ValueError(msg)
        if default_harness_for_label(normalised) is not None and not harness_supports_provider(
            harness_value, normalised
        ):
            msg = (
                f"incompatible harness {harness_value!r} for provider {label!r}; "
                f"{_harness_help_suffix()}"
            )
            raise ValueError(msg)
        return harness_value

    default = default_harness_for_label(normalised)
    if default is not None:
        return default

    msg = f"provider {label!r} requires --harness; {_harness_help_suffix()}"
    raise ValueError(msg)


def load_provider_registry(config_path: Path) -> ProviderRegistry:
    """Load registry entries from *config_path* only (``PROVIDERS`` is seed-only)."""
    data = _load_config_dict(config_path)
    return ProviderRegistry(entries=tuple(_provider_entries(data)))


def _seed_url_for_label(label: str) -> str | None:
    return SEED_PROVIDER_URLS.get(label)


def seed_builtin_providers(config_path: Path) -> None:
    """Import built-in ``PROVIDERS`` catalog rows once (not a reconcile loop)."""
    data = _load_config_dict(config_path)
    if data.get("providersSeeded"):
        return

    entries = _provider_entries(data)
    existing = {str(entry.get("label", "")).lower() for entry in entries}
    next_index = allocate_env_index(entries)

    for label in sorted(PROVIDERS.keys()):
        if label.lower() in existing:
            continue
        harness = default_harness_for_label(label) or "opencode"
        entry: dict[str, Any] = {
            "label": label,
            "harness": harness,
            "envIndex": next_index,
        }
        auth_kind = default_auth_kind_for_label(label)
        if auth_kind is not None:
            entry["authKind"] = auth_kind
        url = _seed_url_for_label(label)
        if url is not None:
            entry["url"] = url
        entries.append(entry)
        next_index += 1

    data["providers"] = entries
    data["providersSeeded"] = True
    _write_config_dict(config_path, data)


@app.command("harnesses")
def harnesses_cmd() -> None:
    """List supported agent harnesses (generated from code)."""
    for row in list_supported_harnesses():
        console.print(f"{row.name}  {row.description}")


@app.command("list")
def list_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """List registered provider labels."""
    config_path = _config_path(cwd.resolve())
    registry = load_provider_registry(config_path)
    if not registry.labels():
        console.print("no providers registered")
        return
    for label in registry.labels():
        console.print(label)


@app.command("add")
def add_cmd(
    label: str = typer.Option(..., "--label", help="Stable provider handle."),
    url: str | None = typer.Option(None, "--url", help="OpenAI-compatible base URL."),
    harness: str | None = typer.Option(None, "--harness", help="Agent harness for this provider."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Register a provider in config and allocate an indexed ``.env`` slot."""
    repo_root = cwd.resolve()
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    entries = _provider_entries(data)

    normalised_label = label.strip()
    if not normalised_label:
        cli_bail("label must not be empty")

    if any(str(entry.get("label", "")).lower() == normalised_label.lower() for entry in entries):
        cli_bail(f"duplicate provider label {normalised_label!r} already registered")

    try:
        resolved_harness = resolve_provider_harness(normalised_label, harness=harness)
    except ValueError as exc:
        cli_bail(str(exc))

    is_builtin_default = normalised_label.lower() in BUILTIN_HARNESS_DEFAULTS
    resolved_url: str | None = None
    if url is not None:
        try:
            resolved_url = validate_http_url(url)
        except ValueError as exc:
            cli_bail(str(exc))
    elif not is_builtin_default:
        cli_bail(f"provider {normalised_label!r} requires --url (absolute http(s) URL)")

    env_index = allocate_env_index(entries)
    entry: dict[str, Any] = {
        "label": normalised_label,
        "harness": resolved_harness,
        "envIndex": env_index,
    }
    if resolved_url is not None:
        entry["url"] = resolved_url

    entries.append(entry)
    data["providers"] = entries
    _write_config_dict(config_path, data)
    _write_env_label(env_index, normalised_label)
    console.print(
        f"registered provider [green]{normalised_label}[/green] "
        f"(envIndex={env_index}, harness={resolved_harness})"
    )


@app.command("edit")
def edit_cmd(
    label: str = typer.Argument(..., help="Provider label to update."),
    url: str | None = typer.Option(None, "--url", help="New OpenAI-compatible base URL."),
    harness: str | None = typer.Option(None, "--harness", help="New agent harness."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Update an existing provider entry in config."""
    repo_root = cwd.resolve()
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    entries = _provider_entries(data)

    match_index: int | None = None
    for idx, entry in enumerate(entries):
        if str(entry.get("label", "")).lower() == label.strip().lower():
            match_index = idx
            break
    if match_index is None:
        cli_bail(f"unknown provider label {label!r}")

    updated = dict(entries[match_index])
    if url is not None:
        try:
            updated["url"] = validate_http_url(url)
        except ValueError as exc:
            cli_bail(str(exc))
    if harness is not None:
        try:
            updated["harness"] = resolve_provider_harness(
                str(updated.get("label", label)),
                harness=harness,
            )
        except ValueError as exc:
            cli_bail(str(exc))

    entries[match_index] = updated
    data["providers"] = entries
    _write_config_dict(config_path, data)
    console.print(f"updated provider [green]{updated.get('label', label)}[/green]")


@app.command("delete")
def delete_cmd(
    label: str = typer.Argument(..., help="Provider label to remove."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Remove a provider label from config (env index gap is preserved)."""
    repo_root = cwd.resolve()
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    entries = _provider_entries(data)

    remaining: list[dict[str, Any]] = []
    removed = False
    for entry in entries:
        if str(entry.get("label", "")).lower() == label.strip().lower():
            removed = True
            continue
        remaining.append(entry)

    if not removed:
        cli_bail(f"unknown provider label {label!r}")

    data["providers"] = remaining
    _write_config_dict(config_path, data)
    console.print(f"deleted provider [green]{label}[/green]")


def indexed_credential_keys(entry: Mapping[str, Any]) -> Sequence[str]:
    """Return indexed ``LLM_PROVIDER_<N>_<SUFFIX>`` keys for *entry* (#478)."""
    env_index = int(entry["envIndex"])
    auth_kind = str(entry.get("authKind") or AUTH_KIND_API_KEY)
    label = str(entry.get("label", "")).lower()

    if auth_kind == AUTH_KIND_CLOUD_CHAIN:
        if label == "bedrock":
            suffixes = BEDROCK_CLOUD_SUFFIXES
        elif label == "vertex":
            suffixes = VERTEX_CLOUD_SUFFIXES
        else:
            suffixes = BEDROCK_CLOUD_SUFFIXES
    else:
        suffix = AUTH_KIND_PRIMARY_SUFFIX.get(auth_kind, "API_KEY")
        suffixes = (suffix,)

    return [f"LLM_PROVIDER_{env_index}_{suffix}" for suffix in suffixes]


@dataclass(frozen=True, slots=True)
class AuthStrategy:
    """Dispatch target for one provider ``authKind`` (#478)."""

    run: Callable[..., None]


def _entry_auth_kind(entry: Mapping[str, Any]) -> str:
    explicit = entry.get("authKind")
    if explicit is not None:
        return str(explicit)
    label = str(entry.get("label", ""))
    default = default_auth_kind_for_label(label)
    return default or AUTH_KIND_API_KEY


def resolve_auth_strategy(auth_kind: str) -> AuthStrategy:
    """Return the credential collector for *auth_kind*."""
    normalised = auth_kind.strip().lower()
    handlers: dict[str, Callable[..., None]] = {
        AUTH_KIND_API_KEY: _run_api_key_strategy,
        AUTH_KIND_OAUTH: _run_oauth_strategy,
        AUTH_KIND_DEVICE_CODE: _run_device_code_strategy,
        AUTH_KIND_CLOUD_CHAIN: _run_cloud_chain_strategy,
    }
    handler = handlers.get(normalised)
    if handler is None:
        cli_bail(f"unknown auth kind {auth_kind!r}")
    return AuthStrategy(run=handler)


def _indexed_label_key(env_index: int) -> str:
    return f"LLM_PROVIDER_{env_index}"


def _persist_indexed_credentials(
    entry: Mapping[str, Any],
    scope: str,
    credential_map: Mapping[str, str],
) -> None:
    """Write ``LLM_PROVIDER_<N>`` label plus indexed credential suffixes to ``.env``."""
    from mergecraft.cli.auth_cmd import (
        _resolve_auth_target,
        _single_line_credential,
        _write_env_value,
    )

    env_index = int(entry["envIndex"])
    label = str(entry["label"])
    target = _resolve_auth_target(scope)
    if not target.local:
        cli_bail("indexed provider auth requires --scope local or --scope both")

    env_path = _env_path()
    label_key = _indexed_label_key(env_index)
    if not _write_env_value(env_path, label_key, label):
        cli_bail(f"could not write {label_key} to {env_path}")

    for suffix, raw_value in credential_map.items():
        key = f"LLM_PROVIDER_{env_index}_{suffix}"
        value = _single_line_credential(name=key, value=raw_value)
        if not _write_env_value(env_path, key, value):
            cli_bail(f"could not write {key} to {env_path}")

    landed = ", ".join([label_key, *credential_map.keys()])
    console.print(f"[green]wrote {landed}[/green] to {env_path}")


def _cancelable_getpass(prompt: str) -> str | None:
    try:
        value = getpass.getpass(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        console.print("canceled.")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE) from None
    if not value:
        console.print("canceled.")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    return value


def _validate_api_key_for_label(label: str, api_key: str, url: str | None) -> bool:
    from mergecraft.cli.auth_cmd import (
        DEFAULT_TOKENHUB,
        _validate_cursor_api_key,
        _validate_gemini_api_key,
        _validate_minimax_api_key,
        _validate_nous_api_key,
        _validate_openai_compatible_key,
    )

    lowered = label.lower()
    if lowered in {"nous", "google", "gemini"}:
        if lowered == "nous":
            return _validate_nous_api_key(api_key)
        return _validate_gemini_api_key(api_key)
    if lowered == "cursor":
        return _validate_cursor_api_key(api_key)
    if lowered == "minimax":
        return _validate_minimax_api_key(api_key)
    if lowered == "tokenhub":
        return _validate_openai_compatible_key(
            api_key=api_key,
            base_url=DEFAULT_TOKENHUB,
            label="tokenhub",
        )
    if url:
        return _validate_openai_compatible_key(api_key=api_key, base_url=url, label=label)
    return True


def _run_api_key_strategy(entry: Mapping[str, Any], scope: str) -> None:
    label = str(entry["label"])
    url = entry.get("url")
    url_str = str(url) if url is not None else None
    console.print(f"paste the API key for provider [cyan]{label}[/cyan] below.")
    api_key = _cancelable_getpass(f"{label} API key (Enter to cancel): ")
    if api_key is None:
        return
    if not _validate_api_key_for_label(label, api_key, url_str):
        cli_bail(f"{label} API key validation failed (401/403). Check the key and retry.")
    _persist_indexed_credentials(
        entry,
        scope,
        {AUTH_KIND_PRIMARY_SUFFIX[AUTH_KIND_API_KEY]: api_key},
    )


def _run_oauth_strategy(entry: Mapping[str, Any], scope: str) -> None:
    from mergecraft.cli.auth_cmd import CLAUDE_OAUTH_TOKEN_PREFIX

    console.print(
        "mint a token with [cyan]claude setup-token[/cyan], then paste it below "
        f"(expected prefix [cyan]{CLAUDE_OAUTH_TOKEN_PREFIX}…[/cyan])."
    )
    oauth_token = _cancelable_getpass("Claude Code OAuth token (Enter to cancel): ")
    if oauth_token is None:
        return
    if not oauth_token.startswith(CLAUDE_OAUTH_TOKEN_PREFIX):
        console.print(
            f"[yellow]warning:[/yellow] that doesn't look like a claude setup-token "
            f"(expected {CLAUDE_OAUTH_TOKEN_PREFIX}…). saving it anyway."
        )
    suffix = AUTH_KIND_PRIMARY_SUFFIX[AUTH_KIND_OAUTH]
    _persist_indexed_credentials(entry, scope, {suffix: oauth_token})


def _run_device_code_strategy(entry: Mapping[str, Any], scope: str) -> None:
    if not shutil.which("codex"):
        cli_bail(
            "codex CLI not found on PATH.\n"
            "  install: npm i -g @openai/codex\n"
            "  then:    mergecraft provider auth openai"
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
            cli_bail(f"codex login failed (exit {exc.returncode})")

        auth_path = Path(tmp) / "auth.json"
        if not auth_path.is_file():
            cli_bail("no auth.json was written — enable device-code auth and retry")
        value = auth_path.read_text(encoding="utf-8")

    suffix = AUTH_KIND_PRIMARY_SUFFIX[AUTH_KIND_DEVICE_CODE]
    _persist_indexed_credentials(entry, scope, {suffix: value})


def _run_cloud_chain_strategy(entry: Mapping[str, Any], scope: str) -> None:
    label = str(entry.get("label", "")).lower()
    if label == "bedrock":
        credentials: dict[str, str] = {}
        for suffix in BEDROCK_CLOUD_SUFFIXES:
            prompt_label = suffix.replace("_", " ")
            value = _cancelable_getpass(f"{prompt_label} (Enter to cancel): ")
            if value is None:
                return
            credentials[suffix] = value
        _persist_indexed_credentials(entry, scope, credentials)
        return

    if label == "vertex":
        path_or_empty = typer.prompt(
            "Path to service account JSON (Enter to paste inline)",
            default="",
            show_default=False,
        ).strip()
        if path_or_empty:
            _persist_indexed_credentials(
                entry,
                scope,
                {VERTEX_CLOUD_SUFFIXES[0]: path_or_empty},
            )
            return

        pasted = _cancelable_getpass("Paste service account JSON (Enter to cancel): ")
        if pasted is None:
            return
        if "\n" in pasted:
            cli_bail(
                "VERTEX_SERVICE_ACCOUNT_JSON spans multiple lines — refusing to write a "
                "broken .env entry. Provide a path via GOOGLE_APPLICATION_CREDENTIALS, "
                "use --scope github, or store base64 in a GitHub secret."
            )
        suffix = VERTEX_CLOUD_SUFFIXES[0]
        _persist_indexed_credentials(entry, scope, {suffix: pasted})
        return

    cli_bail(f"cloud_chain auth is not configured for provider {label!r}")


def _interactive_provider_picker(registry: ProviderRegistry) -> dict[str, Any]:
    entries = [dict(entry) for entry in registry.entries if entry.get("label")]
    if not entries:
        cli_bail("no providers registered — run mergecraft provider add first")

    console.print("select a provider to authenticate:")
    for idx, entry in enumerate(entries, start=1):
        label = str(entry.get("label", ""))
        url = entry.get("url")
        if url:
            console.print(f"  {idx}. {label}  ({url})")
        else:
            console.print(f"  {idx}. {label}")

    choice = typer.prompt("Selection (Enter to cancel)", default="", show_default=False).strip()
    if not choice:
        console.print("canceled.")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)
    try:
        selected = int(choice)
    except ValueError:
        cli_bail(f"invalid selection {choice!r}")
    if selected < 1 or selected > len(entries):
        cli_bail(f"selection {selected} out of range (1-{len(entries)})")
    return entries[selected - 1]


def run_provider_auth(
    entry: Mapping[str, Any],
    scope: str,
    *,
    credential_map: Mapping[str, str] | None = None,
) -> None:
    """Execute unified provider auth for one registry row (#478)."""
    if credential_map is not None:
        _persist_indexed_credentials(entry, scope, credential_map)
        return
    auth_kind = _entry_auth_kind(entry)
    strategy = resolve_auth_strategy(auth_kind)
    strategy.run(entry, scope)


def persist_legacy_indexed_auth(
    label: str,
    scope: str,
    credential_map: Mapping[str, str],
) -> bool:
    """Write *credential_map* via the indexed provider path when *label* is registered."""
    config_path = _config_path(Path.cwd())
    registry = load_provider_registry(config_path)
    entry = registry.lookup(label)
    if entry is None:
        return False
    run_provider_auth(entry, scope, credential_map=credential_map)
    return True


@app.command("auth")
def provider_auth_cmd(
    label: str | None = typer.Argument(
        None,
        help="Provider label (interactive picker when omitted).",
    ),
    scope: str = _PROVIDER_AUTH_SCOPE_OPTION,
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Authenticate one registered provider into indexed ``LLM_PROVIDER_*`` secrets."""
    repo_root = cwd.resolve()
    config_path = _config_path(repo_root)
    registry = load_provider_registry(config_path)

    if label is not None:
        normalised = label.strip()
        if not normalised:
            cli_bail("provider label must not be empty", code=CLI_USAGE_EXIT_CODE)
        if normalised.lower() == "logfire":
            cli_bail(
                "logfire is telemetry, not an LLM provider — use "
                "[cyan]mergecraft auth logfire[/cyan] instead."
            )
        entry = registry.lookup(normalised)
        if entry is None:
            cli_bail(f"unknown provider label {normalised!r}")
        console.print(f"authenticating provider [cyan]{entry.get('label', normalised)}[/cyan]")
        run_provider_auth(entry, scope)
        return

    picked = _interactive_provider_picker(registry)
    console.print(f"authenticating provider [cyan]{picked.get('label')}[/cyan]")
    run_provider_auth(picked, scope)


__all__ = [
    "AUTH_KIND_API_KEY",
    "AUTH_KIND_CLOUD_CHAIN",
    "AUTH_KIND_DEVICE_CODE",
    "AUTH_KIND_OAUTH",
    "AUTH_KIND_PRIMARY_SUFFIX",
    "AuthStrategy",
    "ProviderRegistry",
    "app",
    "indexed_credential_keys",
    "list_supported_harnesses",
    "load_provider_registry",
    "persist_legacy_indexed_auth",
    "provider_auth_cmd",
    "resolve_auth_strategy",
    "resolve_provider_harness",
    "run_provider_auth",
    "seed_builtin_providers",
]
