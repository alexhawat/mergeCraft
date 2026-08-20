"""``mergecraft context`` — inspect retrieved review context."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.table import Table

from mergecraft.cli.consoles import err_console as console
from mergecraft.context.change_graph import ChangedSymbol, resolve_change_graph
from mergecraft.context.provenance import ContextItem, inspect_context
from mergecraft.context.repo_paths import git_blob_sha, git_show_text
from mergecraft.context.symbol_index import index_symbols

app = typer.Typer(
    name="context",
    help="Inspect repository context retrieval for a scope.",
    no_args_is_help=True,
)


def _parse_scope(scope: str) -> tuple[str, str]:
    if ":" not in scope:
        msg = f"invalid scope {scope!r}; expected path:symbol"
        raise typer.BadParameter(msg)
    path, symbol = scope.split(":", 1)
    if not path or not symbol:
        msg = f"invalid scope {scope!r}; expected path:symbol"
        raise typer.BadParameter(msg)
    return path, symbol


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _symbol_kind(
    *,
    repo_root: Path,
    tree_sha: str,
    path: str,
    symbol_name: str,
) -> str:
    lookup_name = symbol_name.split(".")[-1]
    source = git_show_text(repo_root, tree_sha, path)
    if source is None:
        return "symbol"
    blob_sha = git_blob_sha(repo_root, tree_sha, path)
    indexed = index_symbols(
        repo_root=repo_root,
        rel_path=path,
        blob_sha=blob_sha,
        source=source,
    )
    for symbol in indexed.symbols:
        if symbol.name == lookup_name:
            return symbol.kind
    return "symbol"


@app.command("inspect")
def inspect_cmd(
    repo_root: Path = typer.Option(..., "--repo-root", help="Repository root to inspect."),
    repo: str = typer.Option(..., "--repo", help="Logical repo name for citations."),
    commit_sha: str = typer.Option(..., "--commit-sha", help="Commit SHA for citations."),
    tree_sha: str = typer.Option(..., "--tree-sha", help="Tree SHA for indexed context."),
    scope: str = typer.Option(..., "--scope", help="Scope as path:symbol."),
) -> None:
    """Report sources, scope, provenance citations, and token totals."""
    path, symbol_name = _parse_scope(scope)
    symbol_kind = _symbol_kind(
        repo_root=repo_root,
        tree_sha=tree_sha,
        path=path,
        symbol_name=symbol_name,
    )
    change = resolve_change_graph(
        repo_root=repo_root,
        tree_sha=tree_sha,
        changed=[ChangedSymbol(path=path, name=symbol_name, kind=symbol_kind)],
    )

    items: list[ContextItem] = [
        ContextItem(
            repo=repo,
            sha=commit_sha,
            path=path,
            reason="change_graph",
            text=f"dependents={','.join(change.dependents) or '-'}",
            token_cost=_estimate_tokens(path),
        )
    ]
    for test_path in change.tests:
        items.append(
            ContextItem(
                repo=repo,
                sha=commit_sha,
                path=test_path,
                reason="covering_test",
                text=test_path,
                token_cost=_estimate_tokens(test_path),
            )
        )
    for contract_path in change.contracts:
        items.append(
            ContextItem(
                repo=repo,
                sha=commit_sha,
                path=contract_path,
                reason="affected_contract",
                text=contract_path,
                token_cost=_estimate_tokens(contract_path),
            )
        )

    report = inspect_context(items)
    sources = ("call_graph", "change_graph", "symbol_index")

    console.print("[bold]Sources[/bold]")
    for source in sources:
        console.print(f"- {source}")

    console.print("\n[bold]Scope[/bold]")
    console.print(f"{scope}")

    table = Table(title="Provenance")
    table.add_column("citation")
    table.add_column("reason")
    table.add_column("tokens")
    for item in items:
        table.add_row(item.as_citation(), item.reason, str(item.token_cost))
    console.print(table)

    console.print(f"\n[bold]Token total[/bold]: {report.total_tokens}")


__all__ = ["app", "inspect_cmd"]
