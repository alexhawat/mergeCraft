"""``mergecraft doctor`` — environment and wiring probes (CC2)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mergecraft.analyzers.registry import detect_enabled, load_catalog
from mergecraft.config.settings import _DEFAULT_CONFIG_REL, RepoSettings
from mergecraft.mcp.server import MCP_PORT_START, _port_available
from mergecraft.models import MODEL_ALIASES
from mergecraft.utils.agent_resolve import has_credentials_for_slug

if TYPE_CHECKING:
    from collections.abc import Sequence

console = Console()

_SECRET_ENV_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "MERGECRAFT_LOGFIRE_TOKEN",
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "CURSOR_API_KEY",
)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One doctor probe row."""

    name: str
    status: str
    detail: str
    hard_failure: bool = False


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _git_probe(cwd: Path) -> ProbeResult:
    try:
        completed = subprocess.run(
            ["git", "--version"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return ProbeResult("git", "fail", str(exc), hard_failure=True)
    if completed.returncode != 0:
        return ProbeResult("git", "fail", completed.stderr.strip() or "git unavailable", True)
    detail = completed.stdout.strip()
    if not (cwd / ".git").exists():
        detail = f"{detail}; no .git in {cwd}"
        return ProbeResult("git", "warn", detail)
    return ProbeResult("git", "ok", detail)


def _provider_probe() -> ProbeResult:
    detected: list[str] = []
    for alias in MODEL_ALIASES:
        if alias.hidden:
            continue
        if has_credentials_for_slug(alias.slug):
            detected.append(alias.slug)
    if detected:
        return ProbeResult("provider", "ok", f"{len(detected)} model(s) with credentials")
    return ProbeResult("provider", "warn", "no provider credentials detected")


def _analyzer_probe(cwd: Path) -> ProbeResult:
    try:
        changed = ["."]
        enabled = detect_enabled(repo_root=cwd.resolve(), changed_files=changed)
    except Exception as exc:  # pragma: no cover - defensive
        return ProbeResult("analyzer", "fail", str(exc), hard_failure=True)
    total = len(load_catalog())
    return ProbeResult("analyzer", "ok", f"{len(enabled)}/{total} would enable here")


def _auth_probe() -> ProbeResult:
    present: list[str] = []
    for key in _SECRET_ENV_KEYS:
        if os.environ.get(key, "").strip():
            present.append(key)
    if present:
        return ProbeResult("auth", "ok", f"{len(present)} credential env var(s) present")
    return ProbeResult("auth", "warn", "no credential env vars detected")


def _config_probe(cwd: Path) -> ProbeResult:
    config_path = cwd / _DEFAULT_CONFIG_REL
    env_path = os.environ.get("MERGECRAFT_CONFIG")
    if env_path:
        config_path = Path(env_path)
    if not config_path.is_file():
        return ProbeResult("config", "ok", "no config file (defaults apply)")
    try:
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return ProbeResult("config", "fail", f"parse error: {exc}", hard_failure=True)
    if loaded is None:
        return ProbeResult("config", "ok", "empty config file")
    if not isinstance(loaded, dict):
        return ProbeResult("config", "fail", "config root must be a mapping", hard_failure=True)
    try:
        RepoSettings.model_validate(loaded)
    except ValidationError as exc:
        return ProbeResult("config", "fail", f"validation error: {exc}", hard_failure=True)
    return ProbeResult("config", "ok", str(config_path))


def _mcp_probe() -> ProbeResult:
    if _port_available(MCP_PORT_START):
        return ProbeResult(
            "mcp", "ok", "ephemeral port (bind(0)); MCP_PORT_START available as override"
        )
    return ProbeResult("mcp", "warn", "ephemeral port (bind(0)); MCP_PORT_START in use")


def run_doctor_probes(cwd: Path) -> list[ProbeResult]:
    """Compose all doctor probes for a workspace."""
    root = cwd.resolve()
    return [
        _git_probe(root),
        _provider_probe(),
        _analyzer_probe(root),
        _auth_probe(),
        _config_probe(root),
        _mcp_probe(),
    ]


def render_doctor_table(results: Sequence[ProbeResult]) -> Table:
    """Build the Rich table for doctor output."""
    table = Table(title="mergecraft doctor", show_header=True, header_style="bold")
    table.add_column("probe", style="cyan")
    table.add_column("status")
    table.add_column("detail")
    for row in results:
        status = row.status
        if status == "ok":
            status_cell = "[green]ok[/green]"
        elif status == "warn":
            status_cell = "[yellow]warn[/yellow]"
        else:
            status_cell = "[red]fail[/red]"
        table.add_row(row.name, status_cell, row.detail)
    return table


def run(cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root to diagnose.")) -> None:
    """Diagnose git, providers, analyzers, auth, config, and MCP wiring."""
    root = cwd.resolve()
    results = run_doctor_probes(root)
    console.print(render_doctor_table(results))
    if any(row.hard_failure for row in results):
        raise typer.Exit(1)


def assert_output_contains_no_secrets(text: str) -> None:
    """Raise when any known secret env value appears in rendered doctor output."""
    for key in _SECRET_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value and value in text:
            msg = f"doctor leaked credential material from {key}"
            raise RuntimeError(msg)


__all__ = [
    "ProbeResult",
    "assert_output_contains_no_secrets",
    "render_doctor_table",
    "run",
    "run_doctor_probes",
]
