"""``mergecraft doctor`` — environment and wiring probes (CC2)."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
import yaml
from pydantic import ValidationError
from rich.table import Table

from mergecraft.analyzers.registry import detect_enabled, load_catalog
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
)
from mergecraft.config.compat import migrate_config
from mergecraft.config.settings import _DEFAULT_CONFIG_REL, RepoSettings
from mergecraft.evidence.run_manifest import runtime_tool_stamp
from mergecraft.mcp.ports import port_available, read_env_port
from mergecraft.models import MODEL_ALIASES
from mergecraft.utils.agent_resolve import has_credentials_for_slug
from mergecraft.utils.git_hardening import git_argv

if TYPE_CHECKING:
    from collections.abc import Sequence


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


@dataclass(frozen=True, slots=True)
class AgentCliProvenance:
    """Outcome of bundled agent-CLI lockfile provenance verification (#366)."""

    verified: bool
    detail: str = ""


def _git_probe(cwd: Path) -> ProbeResult:
    try:
        completed = subprocess.run(
            git_argv(["--version"]),
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
        RepoSettings.model_validate(migrate_config(loaded))
    except (TypeError, ValueError, ValidationError) as exc:
        return ProbeResult("config", "fail", f"validation error: {exc}", hard_failure=True)
    return ProbeResult("config", "ok", str(config_path))


def _mcp_probe() -> ProbeResult:
    try:
        port = read_env_port()
    except ValueError as exc:
        return ProbeResult("mcp", "warn", str(exc))
    if port is not None:
        if port_available(port):
            return ProbeResult("mcp", "ok", f"MERGECRAFT_MCP_PORT={port} is available")
        return ProbeResult("mcp", "warn", f"MERGECRAFT_MCP_PORT={port} is already in use")
    return ProbeResult("mcp", "ok", "ephemeral port allocation (bind(0))")


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


def runtime_tool_versions() -> dict[str, Any]:
    """Return runtime and tool versions for run manifests and doctor probes."""
    return runtime_tool_stamp()


def verify_agent_cli_provenance(agent_clis_dir: Path) -> AgentCliProvenance:
    """Verify ``docker/agent-clis`` lockfile pins and integrity hashes."""
    pkg_path = agent_clis_dir / "package.json"
    lock_path = agent_clis_dir / "package-lock.json"
    if not pkg_path.is_file() or not lock_path.is_file():
        return AgentCliProvenance(
            verified=False,
            detail="missing package.json or package-lock.json",
        )
    try:
        package = json.loads(pkg_path.read_text(encoding="utf-8"))
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return AgentCliProvenance(verified=False, detail=f"parse error: {exc}")
    if not isinstance(package, dict) or not isinstance(lock, dict):
        return AgentCliProvenance(verified=False, detail="agent-cli manifests must be objects")
    deps = package.get("dependencies")
    packages = lock.get("packages")
    if not isinstance(deps, dict) or not deps:
        return AgentCliProvenance(verified=False, detail="package.json has no dependencies")
    if not isinstance(packages, dict):
        return AgentCliProvenance(verified=False, detail="package-lock.json has no packages map")
    missing: list[str] = []
    for name, pinned in deps.items():
        entry = packages.get(f"node_modules/{name}")
        if not isinstance(entry, dict):
            missing.append(str(name))
            continue
        version = str(entry.get("version", ""))
        integrity = str(entry.get("integrity", "")).strip()
        if version != str(pinned) or not integrity:
            missing.append(str(name))
    if missing:
        return AgentCliProvenance(
            verified=False,
            detail=f"unpinned or unsigned: {', '.join(missing)}",
        )
    return AgentCliProvenance(
        verified=True,
        detail=f"{len(deps)} agent CLI(s) lockfile-pinned with integrity",
    )


def _reproducibility_probe(cwd: Path) -> ProbeResult:
    found: list[str] = []
    if (cwd / "uv.lock").is_file():
        found.append("uv.lock")
    agent_lock = cwd / "docker" / "agent-clis" / "package-lock.json"
    if agent_lock.is_file():
        found.append("docker/agent-clis/package-lock.json")
    if found:
        return ProbeResult("reproducibility", "ok", f"pinned lockfiles: {', '.join(found)}")
    return ProbeResult("reproducibility", "warn", "no lockfiles in this workspace")


def _analyzer_pinning_probe() -> ProbeResult:
    catalog = load_catalog()
    total = len(catalog)
    with_version = sum(1 for item in catalog if item.version.strip())
    if total and with_version == total:
        return ProbeResult(
            "analyzer_pinning",
            "ok",
            f"{with_version}/{total} analyzers version-pinned",
        )
    return ProbeResult(
        "analyzer_pinning",
        "warn",
        f"{with_version}/{total} analyzers version-pinned",
    )


def run_supply_chain_probes(*, cwd: Path) -> list[ProbeResult]:
    """Compose supply-chain provenance and pinning probes (#366 / D16)."""
    root = cwd.resolve()
    report = verify_agent_cli_provenance(root / "docker" / "agent-clis")
    versions = runtime_tool_versions()
    python = str(versions.get("python", ""))
    tools = versions.get("tools")
    tool_count = len(tools) if isinstance(tools, dict) else 0
    provenance_status = "ok" if report.verified else "warn"
    return [
        _reproducibility_probe(root),
        _analyzer_pinning_probe(),
        ProbeResult("agent_cli_provenance", provenance_status, report.detail),
        ProbeResult("runtime", "ok", f"python {python}; {tool_count} tools recorded"),
    ]


def render_doctor_table(
    results: Sequence[ProbeResult],
    *,
    title: str = "mergecraft doctor",
) -> Table:
    """Build the Rich table for doctor output."""
    table = Table(title=title, show_header=True, header_style="bold")
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


def run(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root to diagnose."),
    supply_chain: bool = typer.Option(
        False,
        "--supply-chain",
        help="Run supply-chain provenance, pinning, and reproducibility probes.",
    ),
) -> None:
    """Diagnose git, providers, analyzers, auth, config, and MCP wiring."""
    root = cwd.resolve()
    results = run_doctor_probes(root)
    title = "mergecraft doctor"
    if supply_chain:
        results = [*results, *run_supply_chain_probes(cwd=root)]
        title = "mergecraft doctor — supply-chain provenance"
    console.print(render_doctor_table(results, title=title))
    if any(row.hard_failure for row in results):
        raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE)


def assert_output_contains_no_secrets(text: str) -> None:
    """Raise when any known secret env value appears in rendered doctor output."""
    for key in _SECRET_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value and value in text:
            msg = f"doctor leaked credential material from {key}"
            raise RuntimeError(msg)


__all__ = [
    "AgentCliProvenance",
    "ProbeResult",
    "assert_output_contains_no_secrets",
    "render_doctor_table",
    "run",
    "run_doctor_probes",
    "run_supply_chain_probes",
    "runtime_tool_versions",
    "verify_agent_cli_provenance",
]
