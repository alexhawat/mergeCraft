"""``mergecraft cache`` — run-cache inspection and maintenance (CC4)."""

from __future__ import annotations

import os
from typing import NoReturn

import typer
from rich.table import Table

from mergecraft.cli.consoles import err_console as console
from mergecraft.utils.run_bounds import resolve_run_bounds
from mergecraft.utils.run_cache import RunCache, default_cache_root, open_run_cache

app = typer.Typer(
    name="cache",
    help="Inspect and maintain the mergeCraft run cache.",
    no_args_is_help=True,
)


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _cache_from_env() -> RunCache:
    root = default_cache_root()
    bounds = resolve_run_bounds(env=os.environ)
    return open_run_cache(root=root, max_bytes=bounds.cache_max_bytes)


@app.command("info")
def info_cmd() -> None:
    """Show cache location, byte ceiling, and current usage."""
    cache = _cache_from_env()
    snapshot = cache.info()
    table = Table(title="Run cache")
    table.add_column("field")
    table.add_column("value")
    table.add_row("root", str(snapshot["root"]))
    table.add_row("entries", str(snapshot["entries"]))
    table.add_row("bytes", str(snapshot["bytes"]))
    table.add_row("max_bytes", str(snapshot["max_bytes"]))
    console.print(table)


@app.command("clear")
def clear_cmd() -> None:
    """Remove every entry from the run cache."""
    cache = _cache_from_env()
    removed = cache.clear()
    console.print(f"[green]cleared {removed} cache entr{'y' if removed == 1 else 'ies'}[/green]")


@app.command("prune")
def prune_cmd() -> None:
    """Evict oldest entries until usage is within the byte ceiling."""
    cache = _cache_from_env()
    pruned = cache.prune()
    snapshot = cache.info()
    console.print(
        f"[green]pruned {pruned} entr{'y' if pruned == 1 else 'ies'}; "
        f"{snapshot['bytes']} / {snapshot['max_bytes']} bytes remain[/green]"
    )
