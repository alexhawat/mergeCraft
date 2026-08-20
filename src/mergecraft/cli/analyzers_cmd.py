"""``mergecraft analyzers`` — catalog inspection and offline runs (C6.8)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

import typer
from rich.table import Table

from mergecraft.analyzers.adapters import run_adapter
from mergecraft.analyzers.catalog_docs import write_analyzers_doc
from mergecraft.analyzers.lockfile import LockEntry, read_lock, write_lock
from mergecraft.analyzers.provision import resolve_with_lock
from mergecraft.analyzers.registry import detect_enabled, load_catalog
from mergecraft.analyzers.sarif import export_sarif
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.target_dir import target_dir as resolve_target_dir

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import AnalyzerManifest

app = typer.Typer(
    name="analyzers",
    help="Inspect and run the mergeCraft analyzer catalog.",
    no_args_is_help=True,
)


def _git_changed_files(target_dir: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=target_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _manifest_by_id(analyzer_id: str) -> AnalyzerManifest:
    for manifest in load_catalog():
        if manifest.id == analyzer_id:
            return manifest
    cli_bail(f"unknown analyzer id: {analyzer_id!r}")
    raise AssertionError("unreachable")


@app.command("list")
def list_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """List catalog analyzers and whether they would enable here."""
    target_dir = resolve_target_dir(cwd)
    changed = _git_changed_files(target_dir) or ["."]
    enabled = {m.id for m in detect_enabled(repo_root=target_dir, changed_files=changed)}
    table = Table(title="Analyzer catalog")
    table.add_column("id")
    table.add_column("category")
    table.add_column("default")
    table.add_column("would enable")
    for manifest in sorted(load_catalog(), key=lambda m: m.id):
        default = str(manifest.default_enabled)
        would = "yes" if manifest.id in enabled else "no"
        table.add_row(manifest.id, manifest.category, default, would)
    console.print(table)


@app.command("detect")
def detect_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
    files: list[str] = typer.Option(None, "--file", "-f", help="Changed paths (repeatable)."),
) -> None:
    """Show analyzers that would run for changed paths in this repo."""
    target_dir = resolve_target_dir(cwd)
    changed = files or _git_changed_files(target_dir)
    if not changed:
        cli_bail("no changed files — pass --file or run inside a git repo with local changes")
    enabled = detect_enabled(repo_root=target_dir, changed_files=changed)
    for manifest in enabled:
        console.print(f"{manifest.id} ({manifest.category}, {manifest.runtime})")


@app.command("run")
def run_cmd(
    analyzer_id: str = typer.Argument(..., help="Catalog analyzer id."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
    files: list[str] = typer.Option(None, "--file", "-f", help="Changed paths (repeatable)."),
) -> None:
    """Execute one analyzer against the working tree."""
    target_dir = resolve_target_dir(cwd)
    changed = files or _git_changed_files(target_dir)
    if not changed:
        cli_bail("no changed files — pass --file or run inside a git repo with local changes")
    result = run_adapter(
        tool_id=analyzer_id,
        repo_root=target_dir,
        changed_files=changed,
        tier="trusted",
    )
    if result.skipped:
        cli_bail(result.skip_reason or f"skipped {analyzer_id}")
    console.print(f"findings: {len(result.findings)}")
    if result.version_note:
        console.print(result.version_note)
    for finding in result.findings[:20]:
        console.print(
            f"  {finding.path}:{finding.start_line} [{finding.severity}] {finding.message}"
        )


@app.command("explain")
def explain_cmd(analyzer_id: str = typer.Argument(..., help="Catalog analyzer id.")) -> None:
    """Print manifest fields and notes for one analyzer."""
    manifest = _manifest_by_id(analyzer_id)
    console.print(f"id: {manifest.id}")
    console.print(f"category: {manifest.category}")
    console.print(f"languages: {', '.join(manifest.languages) or '—'}")
    console.print(f"detect.files: {', '.join(manifest.detect.files)}")
    console.print(f"command: {' '.join(manifest.command)}")
    console.print(f"parser: {manifest.parser}")
    console.print(f"runtime: {manifest.runtime}")
    console.print(f"default_enabled: {manifest.default_enabled}")
    console.print(f"trust: {manifest.trust}")
    if manifest.exclusive_group:
        console.print(f"exclusive_group: {manifest.exclusive_group}")
    if manifest.declared_unavailable:
        console.print(f"declared_unavailable: {manifest.declared_unavailable}")


@app.command("export")
def export_cmd(
    analyzer_id: str = typer.Argument(..., help="Catalog analyzer id."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
    files: list[str] = typer.Option(None, "--file", "-f", help="Changed paths (repeatable)."),
    sarif: bool = typer.Option(False, "--sarif", help="Write SARIF 2.1.0 JSON to stdout."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write SARIF to this file."),
) -> None:
    """Run one analyzer and export findings as SARIF."""
    if not sarif and output is None:
        cli_bail("pass --sarif or --output")
    target_dir = resolve_target_dir(cwd)
    changed = files or _git_changed_files(target_dir)
    if not changed:
        cli_bail("no changed files — pass --file or run inside a git repo with local changes")
    result = run_adapter(
        tool_id=analyzer_id,
        repo_root=target_dir,
        changed_files=changed,
        tier="trusted",
    )
    if result.skipped:
        cli_bail(result.skip_reason or f"skipped {analyzer_id}")
    document = export_sarif(result.findings)
    payload = json.dumps(document, indent=2)
    if output is not None:
        output.write_text(payload + "\n", encoding="utf-8")
        console.print(f"wrote {output}")
    else:
        typer.echo(payload)


@app.command("lock")
def lock_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
    refresh: bool = typer.Option(False, "--refresh", help="Re-resolve managed binaries."),
) -> None:
    """Write or refresh ``.mergecraft/analyzers.lock`` for managed tools."""
    import platform
    import sys

    target_dir = resolve_target_dir(cwd)
    lock_path = target_dir / ".mergecraft" / "analyzers.lock"
    cache_dir = target_dir / ".mergecraft" / "analyzer-cache"
    machine = platform.machine().casefold()
    if sys.platform == "darwin":
        plat = "darwin-arm64" if machine in {"arm64", "aarch64"} else "darwin-amd64"
    elif machine in {"arm64", "aarch64"}:
        plat = "linux-arm64"
    else:
        plat = "linux-amd64"

    existing = {entry.tool_id: entry for entry in read_lock(lock_path)}
    entries: list[LockEntry | dict[str, Any]] = []
    for manifest in load_catalog():
        if manifest.runtime not in {"managed", "container"}:
            continue
        if manifest.declared_unavailable:
            continue
        if not refresh and manifest.id in existing:
            entries.append(existing[manifest.id])
            continue
        if manifest.runtime == "container":
            entries.append(
                LockEntry(
                    tool_id=manifest.id,
                    version=manifest.version,
                    mode="container",
                    source=f"container:{manifest.id}:{manifest.version}",
                    sha256="container",
                )
            )
            continue
        if plat not in manifest.provenance:
            continue
        try:
            result = resolve_with_lock(
                manifest=manifest,
                lock_path=lock_path,
                cache_dir=cache_dir,
                platform=plat,
            )
        except Exception as exc:
            console.print(f"[yellow]skip {manifest.id}: {exc}[/yellow]")
            continue
        entries.append(
            LockEntry(
                tool_id=manifest.id,
                version=manifest.version,
                mode="managed",
                source=result.source,
                sha256=result.sha256,
            )
        )
    write_lock(lock_path, entries, merge=not refresh)
    console.print(f"lockfile updated: {lock_path} ({len(entries)} tools)")


@app.command("docs")
def docs_cmd() -> None:
    """Regenerate ``docs/ANALYZERS.md`` from manifests."""
    path = write_analyzers_doc()
    console.print(f"wrote {path}")


__all__ = ["app"]
