"""``mergecraft doctor`` — environment and wiring probes (CC2)."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from mergecraft.analyzers.registry import detect_enabled, load_catalog
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
)
from mergecraft.cli.workflow_wf_yaml import DEFAULT_WORKFLOW_RELATIVE_PATH
from mergecraft.config.agent_roster import load_roster
from mergecraft.config.compat import migrate_config
from mergecraft.config.env import ConfigLocatorEnv
from mergecraft.config.io import config_path_for_root, load_config_dict
from mergecraft.config.layered import merge_config_dicts, resolve_config_sources
from mergecraft.config.roster_unwired import iter_roster_model_slots
from mergecraft.config.runtime_provider_registry import (
    credential_env_keys_for_entry,
    lookup_registry_entry,
)
from mergecraft.config.settings import RepoSettings
from mergecraft.config.yaml_unique import ConfigParseError, safe_load_unique
from mergecraft.evidence.run_manifest import runtime_tool_stamp
from mergecraft.mcp.ports import port_available, read_env_port
from mergecraft.models import MODEL_ALIASES
from mergecraft.utils.agent_resolve import has_credentials_for_slug
from mergecraft.utils.git_hardening import git_argv
from mergecraft.workflow.auth_manifest import (
    WorkflowAuthManifestError,
    flat_credential_env_keys,
    iter_mergecraft_action_steps,
    workflow_secret_bindings,
)

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
    try:
        for alias in MODEL_ALIASES:
            if alias.hidden:
                continue
            if has_credentials_for_slug(alias.slug):
                detected.append(alias.slug)
    except ConfigParseError:
        # The config probe reports the unparseable file as the hard failure;
        # doctor stays a diagnostic instead of crashing on the same error.
        return ProbeResult("provider", "warn", "config unreadable; credentials not evaluated")
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
    sources = resolve_config_sources(cwd)
    env_note = ""
    if sources.env_config_missing:
        env_path = ConfigLocatorEnv().config_path or ""
        env_note = f"MERGECRAFT_CONFIG={env_path} does not exist"
    if not sources.files:
        if env_note:
            return ProbeResult("config", "warn", f"{env_note}; no config file found")
        return ProbeResult("config", "ok", "no config file (defaults apply)")

    merged: dict[str, Any] = {}
    for path in sources.files:
        try:
            loaded = safe_load_unique(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            detail = f"config parse error: {path} ({type(exc).__name__})"
            return ProbeResult("config", "fail", detail, hard_failure=True)
        if loaded is None:
            continue
        if not isinstance(loaded, dict):
            return ProbeResult("config", "fail", "config root must be a mapping", hard_failure=True)
        merged = merge_config_dicts(merged, loaded)

    try:
        RepoSettings.model_validate(migrate_config(merged))
    except (TypeError, ValueError, ValidationError) as exc:
        return ProbeResult("config", "fail", f"validation error: {exc}", hard_failure=True)

    contributing = ", ".join(str(path) for path in sources.files)
    if env_note:
        return ProbeResult("config", "warn", f"{env_note}; contributing: {contributing}")
    return ProbeResult("config", "ok", contributing)


def repository_secret_names(root: Path) -> frozenset[str] | None:
    """Return the Actions secret names the repository can read, or ``None``.

    Repository secrets and, when ``gh`` may read them, the organization secrets
    shared with the repository. ``None`` means the list could not be read (no
    ``gh``, not authenticated, no GitHub remote): the caller must not guess.

    Args:
        root (Path): Repository root; ``gh`` infers the repository from it.

    Returns:
        frozenset[str] | None: Secret names, or ``None`` when unreadable.
    """
    if shutil.which("gh") is None:
        return None
    names: set[str] = set()
    for endpoint, required in (
        ("repos/{owner}/{repo}/actions/secrets", True),
        ("repos/{owner}/{repo}/actions/organization-secrets", False),
    ):
        try:
            completed = subprocess.run(
                ["gh", "api", "--paginate", endpoint, "--jq", ".secrets[].name"],
                cwd=root,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            completed = None
        if completed is None or completed.returncode != 0:
            if required:
                return None
            continue
        names.update(line.strip() for line in completed.stdout.splitlines() if line.strip())
    return frozenset(names)


def _probe_slugs(raw: dict[str, Any], workflow: Path) -> tuple[list[str], bool]:
    """Return the model slugs CI needs credentials for, and whether all are required.

    A committed ``agents:`` roster is checked slot by slot at run start, so every
    roster provider needs its secret. Without a roster the run walks the
    ``models:`` chain and the workflow's ``with.model``, so one usable provider
    is enough.

    Args:
        raw (dict[str, Any]): Committed config mapping.
        workflow (Path): Consumer workflow file.

    Returns:
        tuple[list[str], bool]: Slugs in order, and ``True`` when all are required.
    """
    roster_slugs = [slug for _agent, _slot, slug in iter_roster_model_slots(load_roster(raw))]
    if roster_slugs:
        return roster_slugs, True
    models = raw.get("models")
    slugs = [str(item) for item in models] if isinstance(models, list) else []
    for step in iter_mergecraft_action_steps(workflow):
        model = step.get("model")
        if isinstance(model, str) and model.strip() and "${{" not in model:
            slugs.append(model.strip())
    return slugs, False


def _workflow_auth_probe(root: Path) -> ProbeResult:
    """Check that the consumer workflow passes a stored credential to the Action.

    ``provider auth --scope github`` stores ``LLM_PROVIDER_<N>_*`` secrets; a
    workflow that passes other names (or none) gives the CI review no
    credential, and the run fails or is skipped while the check stays green.

    Args:
        root (Path): Repository root.

    Returns:
        ProbeResult: ``fail`` (hard) when CI would have no usable credential.
    """
    name = "workflow auth"
    workflow = root / DEFAULT_WORKFLOW_RELATIVE_PATH
    if not workflow.is_file():
        return ProbeResult(
            name, "ok", f"no {DEFAULT_WORKFLOW_RELATIVE_PATH} (CI review not set up)"
        )
    try:
        # CI runs with the committed config only, never config.local.yaml.
        raw = load_config_dict(config_path_for_root(root))
        settings = RepoSettings.model_validate(migrate_config(raw)) if raw else None
        slugs, require_all = _probe_slugs(raw, workflow)
        bindings = workflow_secret_bindings(workflow)
    except (OSError, ValueError, ValidationError, yaml.YAMLError, WorkflowAuthManifestError) as exc:
        return ProbeResult(name, "warn", f"not evaluated ({type(exc).__name__})")

    providers: list[str] = []
    for slug in slugs:
        provider = slug.partition("/")[0].strip().lower()
        if provider and provider not in providers:
            providers.append(provider)
    if not providers:
        return ProbeResult(name, "warn", "no model configured; nothing to authenticate")

    stored = repository_secret_names(root)
    usable: list[str] = []
    unverified: list[str] = []
    problems: list[str] = []
    for provider in providers:
        entry = lookup_registry_entry(settings, provider)
        keys = set(credential_env_keys_for_entry(entry)) if entry is not None else set()
        if entry is None or not require_all:
            keys.update(flat_credential_env_keys(provider))
        bound = sorted({secret for env_key, secret in bindings if env_key in keys})
        fix = f"run mergecraft provider auth {provider} --scope github"
        if not bound:
            problems.append(f"{provider}: the workflow passes no credential ({fix})")
        elif stored is None:
            unverified.append(provider)
        elif not stored.intersection(bound):
            problems.append(
                f"{provider}: the workflow reads {', '.join(bound)}, which the repository "
                f"does not have ({fix})"
            )
        else:
            usable.append(provider)

    if (require_all and problems) or (not usable and not unverified):
        return ProbeResult(name, "fail", "; ".join(problems), hard_failure=True)
    if unverified:
        return ProbeResult(
            name,
            "warn",
            f"repository secrets not verified (gh cannot list them) for {', '.join(unverified)}",
        )
    return ProbeResult(name, "ok", f"CI credential stored for {', '.join(usable)}")


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
        _workflow_auth_probe(root),
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


def _render_table_text(table: Table) -> str:
    """Render *table* to plain text for a secret tripwire before it is printed."""
    buffer = io.StringIO()
    renderer = Console(file=buffer, stderr=True, no_color=True, soft_wrap=True, width=400)
    renderer.print(table)
    return buffer.getvalue()


def run(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root to diagnose."),
    supply_chain: bool = typer.Option(
        False,
        "--supply-chain",
        help="Run supply-chain provenance, pinning, and reproducibility probes.",
    ),
) -> None:
    """Diagnose git, providers, analyzers, auth, config, workflow auth, and MCP wiring."""
    root = cwd.resolve()
    results = run_doctor_probes(root)
    title = "mergecraft doctor"
    if supply_chain:
        results = [*results, *run_supply_chain_probes(cwd=root)]
        title = "mergecraft doctor — supply-chain provenance"
    table = render_doctor_table(results, title=title)
    # The tripwire is a hard failure checked on the rendered table *before* it
    # is printed: a credential that reached a probe detail exits before any of
    # the table lands, naming the env key and never the value.
    try:
        assert_output_contains_no_secrets(_render_table_text(table))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE) from exc
    console.print(table)
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
    "repository_secret_names",
    "run",
    "run_doctor_probes",
    "run_supply_chain_probes",
    "runtime_tool_versions",
    "verify_agent_cli_provenance",
]
