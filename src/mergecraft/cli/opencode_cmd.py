"""``mergecraft opencode install|doctor`` — first-class OpenCode integration.

``install`` copies the OpenCode commands, subagents, and plugin into the project
(``.opencode/``) or the global config (``~/.config/opencode/``), writes the V2
``mcp.servers.mergecraft`` block, and sets ``harness: opencode`` in
``.mergecraft/config.yaml``.

``doctor`` reports whether the CLI, assets, config, MCP block, JEV, and Logfire
are wired, and exits non-zero under ``--strict`` when anything is missing.

Exports:
    app -- the ``opencode`` Typer subapp registered on the root CLI.
"""

from __future__ import annotations

import json
import os
import shutil
from importlib import resources
from pathlib import Path
from typing import Any

import typer

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_AUDIT_VERIFY_FAILED_EXIT_CODE
from mergecraft.cli.typer_group import mergecraft_typer
from mergecraft.config.io import load_config_dict, patch_config_dict

_ASSET_SUBDIRS = ("commands", "agents", "plugins")
_MCP_SERVER_NAME = "mergecraft"
_MCP_COMMAND = ["mergecraft", "mcp", "serve", "--role", "public", "--transport", "stdio"]
_CONFIG_CANDIDATES = (
    "opencode.jsonc",
    "opencode.json",
    ".opencode/opencode.jsonc",
    ".opencode/opencode.json",
)

app = mergecraft_typer(
    name="opencode",
    help="Install and diagnose the mergeCraft OpenCode integration.",
    no_args_is_help=True,
)


def _packaged_root() -> Path | None:
    """Return the wheel-packaged asset root, or ``None`` when running from source."""
    try:
        candidate = resources.files("mergecraft.data").joinpath("opencode")
    except (ModuleNotFoundError, TypeError, ValueError):  # pragma: no cover - defensive
        return None
    try:
        path = Path(str(candidate))
    except TypeError:  # pragma: no cover - non-filesystem traversable
        return None
    return path if path.is_dir() else None


def _source_root() -> Path:
    """Return ``integrations/opencode`` from a source checkout."""
    # src/mergecraft/cli/opencode_cmd.py -> parents[3] is the repo root.
    return Path(__file__).resolve().parents[3] / "integrations" / "opencode"


def assets_root() -> Path:
    """Resolve the integration asset root (packaged first, then source)."""
    for candidate in (_packaged_root(), _source_root()):
        if candidate is not None and candidate.is_dir():
            return candidate
    cli_bail(
        "OpenCode integration assets not found; reinstall mergecraft or run from a source checkout"
    )
    raise AssertionError("unreachable")  # pragma: no cover - cli_bail exits


def _destination_root(*, global_install: bool, project_root: Path) -> Path:
    if global_install:
        return Path.home() / ".config" / "opencode"
    return project_root / ".opencode"


def _copy_assets(root: Path, destination: Path, *, force: bool) -> list[str]:
    """Copy commands/agents/plugins under ``destination``; return written paths."""
    written: list[str] = []
    for subdir in _ASSET_SUBDIRS:
        source = root / subdir
        if not source.is_dir():
            continue
        target = destination / subdir
        for item in sorted(source.rglob("*")):
            if not item.is_file():
                continue
            relative = item.relative_to(source)
            out = target / relative
            if out.exists() and not force:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, out)
            written.append(str(out))
    return written


def _mcp_block() -> dict[str, Any]:
    return {
        _MCP_SERVER_NAME: {
            "type": "local",
            "command": list(_MCP_COMMAND),
        }
    }


def _find_config_file(target: Path) -> Path | None:
    """Return the first existing OpenCode config file under ``target``."""
    for relative in _CONFIG_CANDIDATES:
        candidate = target / relative
        if candidate.is_file():
            return candidate
    return None


def _write_or_patch_config(target: Path) -> tuple[Path, bool]:
    """Write the MCP block, or return the file plus whether it was patched."""
    existing = _find_config_file(target)
    if existing is None:
        path = target / "opencode.json"
        payload: dict[str, Any] = {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {"servers": _mcp_block()},
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path, True

    text = existing.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return existing, False
    if not isinstance(data, dict):
        return existing, False
    servers = data.setdefault("mcp", {}).setdefault("servers", {})
    if not isinstance(servers, dict):
        return existing, False
    servers[_MCP_SERVER_NAME] = _mcp_block()[_MCP_SERVER_NAME]
    existing.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return existing, True


def _mcp_snippet(config_file: Path) -> str:
    return (
        f"[yellow]{config_file} is JSONC (comments); add this block manually:[/yellow]\n\n"
        '  "mcp": { "servers": { "mergecraft": { "type": "local",\n'
        '    "command": ["mergecraft", "mcp", "serve", "--role", "public", "--transport", "stdio"] } } }\n'
    )


@app.command("install")
def install(
    target: Path | None = typer.Option(
        None, "--target", help="Project root to install into (default: current directory)."
    ),
    global_install: bool = typer.Option(
        False, "--global", help="Install into ~/.config/opencode/ instead of the project."
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing asset files."),
    router: bool = typer.Option(
        True, "--router/--no-router", help="Set harness: opencode in .mergecraft/config.yaml."
    ),
) -> None:
    """Install OpenCode commands, subagents, plugin, and MCP config."""
    root = assets_root()
    project_root = target if target is not None else Path.cwd()
    dest = _destination_root(global_install=global_install, project_root=project_root)
    dest.mkdir(parents=True, exist_ok=True)
    written = _copy_assets(root, dest, force=force)
    for path in written:
        console.print(f"wrote [green]{path}[/green]")
    if not written:
        console.print("[dim]assets already present — pass --force to refresh[/dim]")

    config_file, patched = _write_or_patch_config(dest)
    if patched:
        console.print(f"wrote MCP block in [green]{config_file}[/green]")
    else:
        console.print(_mcp_snippet(config_file))

    if router and not global_install:
        config_path = project_root / ".mergecraft" / "config.yaml"
        if config_path.is_file():
            current = load_config_dict(config_path).get("harness")
            if current != "opencode":
                patch_config_dict(config_path, {"harness": "opencode"})
                console.print(f"set [green]harness: opencode[/green] in {config_path}")
        else:
            console.print(
                "[dim]no .mergecraft/config.yaml yet — run [cyan]mergecraft init[/cyan] "
                "then re-run install[/dim]"
            )

    console.print("\n[bold]next steps[/bold]")
    console.print("  1. restart OpenCode so it loads the plugin")
    console.print("  2. [cyan]opencode mcp list[/cyan] — expect mergecraft connected")
    console.print("  3. try [cyan]/mergecraft/review[/cyan]")


def _check(label: str, ok: bool, detail: str) -> tuple[str, bool, str]:
    return label, ok, detail


def _doctor_checks(target: Path, root: Path, project_root: Path) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    checks.append(_check("assets", root.is_dir(), str(root) if root.is_dir() else "not found"))
    checks.append(
        _check(
            "mergecraft on PATH",
            shutil.which("mergecraft") is not None,
            shutil.which("mergecraft") or "not found",
        )
    )
    commands_dir = target / "commands" / "mergecraft"
    checks.append(_check("review commands", commands_dir.is_dir(), str(commands_dir)))
    agents_dir = target / "agents" / "mergecraft"
    checks.append(_check("reviewer subagent", agents_dir.is_dir(), str(agents_dir)))
    plugin = target / "plugins" / "mergecraft" / "index.ts"
    checks.append(_check("plugin", plugin.is_file(), str(plugin)))

    config_file = _find_config_file(target)
    if config_file is None:
        checks.append(_check("MCP config", False, "no opencode.json(c) found"))
    else:
        text = config_file.read_text(encoding="utf-8")
        has_block = "mergecraft" in text and '"mcp"' in text
        checks.append(
            _check(
                "MCP config",
                has_block,
                f"{config_file}" + ("" if has_block else " — add mcp.servers"),
            )
        )

    repo_config = project_root / ".mergecraft" / "config.yaml"
    if repo_config.is_file():
        harness = load_config_dict(repo_config).get("harness")
        checks.append(
            _check("harness", harness == "opencode", f"harness: {harness!r} (want 'opencode')")
        )
    else:
        checks.append(_check("harness", False, "no .mergecraft/config.yaml"))

    jev_env = os.environ.get("TYPESAFE_API_KEY", "").strip() != ""
    jev_cfg = False
    if repo_config.is_file():
        jev_cfg = bool(load_config_dict(repo_config).get("jev"))
    checks.append(
        _check(
            "JEV",
            jev_env or jev_cfg,
            "TYPESAFE_API_KEY set"
            if jev_env
            else ("jev configured" if jev_cfg else "run mergecraft jev enable"),
        )
    )

    logfire_env = any(
        os.environ.get(name, "").strip() for name in ("MERGECRAFT_LOGFIRE_TOKEN", "LOGFIRE_TOKEN")
    )
    env_file = project_root / ".env"
    logfire_dotenv = env_file.is_file() and "MERGECRAFT_LOGFIRE_TOKEN" in env_file.read_text(
        encoding="utf-8"
    )
    checks.append(
        _check(
            "Logfire",
            logfire_env or logfire_dotenv,
            "token present" if (logfire_env or logfire_dotenv) else "run mergecraft auth logfire",
        )
    )
    return checks


@app.command("doctor")
def doctor(
    target: Path | None = typer.Option(
        None, "--target", help="Project root to inspect (default: current directory)."
    ),
    global_install: bool = typer.Option(
        False, "--global", help="Inspect ~/.config/opencode/ instead of the project."
    ),
    strict: bool = typer.Option(False, "--strict", help="Exit non-zero when any check fails."),
) -> None:
    """Report whether the OpenCode integration is fully wired."""
    try:
        root = assets_root()
    except SystemExit:
        root = Path("<missing>")
    project_root = target if target is not None else Path.cwd()
    destination = _destination_root(global_install=global_install, project_root=project_root)
    checks = _doctor_checks(destination, root, project_root)
    failures = 0
    for label, ok, detail in checks:
        mark = "[green]ok[/green]" if ok else "[red]missing[/red]"
        if not ok:
            failures += 1
        console.print(f"  {mark:>22}  {label}: {detail}")
    if failures and strict:
        raise typer.Exit(code=CLI_AUDIT_VERIFY_FAILED_EXIT_CODE)
    console.print(
        "[yellow]some checks need attention[/yellow]"
        if failures
        else "[green]all checks passed[/green]"
    )
