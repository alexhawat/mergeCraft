"""``mergecraft ask`` — output-only, line-scoped Q&A over the reviewed tree (#377).

Exports: ``run``
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.table import Table

from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_USAGE_EXIT_CODE
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output


def _read_line(path: Path, line: int) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = text.splitlines()
    if line < 1 or line > len(lines):
        return ""
    return lines[line - 1]


def _payload(
    *,
    question: str | None,
    file: Path | None,
    line: int | None,
    excerpt: str,
) -> dict[str, Any]:
    scoped = file is not None and line is not None
    if excerpt:
        answer = excerpt
    elif scoped:
        answer = "No line text at that location."
    elif question:
        answer = "No stored review to answer from; pass --file and --line for line-scoped Q&A."
    else:
        answer = "Ask a question, optionally scoped with --file and --line."
    return {
        "verb": "ask",
        "question": question,
        "file": str(file) if file is not None else None,
        "line": line,
        "excerpt": excerpt,
        "answer": answer,
    }


def _render_table(payload: dict[str, Any]) -> Table:
    table = Table(title="mergecraft ask", show_header=True, header_style="bold")
    table.add_column("field")
    table.add_column("value")
    table.add_row("question", str(payload.get("question") or "none"))
    table.add_row("file", str(payload.get("file") or "none"))
    table.add_row("line", str(payload.get("line") if payload.get("line") is not None else "none"))
    table.add_row("excerpt", str(payload.get("excerpt") or "none"))
    table.add_row("answer", str(payload.get("answer") or ""))
    return table


def run(
    ctx: typer.Context,
    question: str | None = typer.Argument(
        default=None,
        help="Question about the change or a specific line.",
    ),
    file: Path | None = typer.Option(
        None,
        "--file",
        help="Source file for line-scoped Q&A (read-only).",
    ),
    line: int | None = typer.Option(
        None,
        "--line",
        help="1-based line number in --file.",
    ),
) -> None:
    """Answer a question about the tree, optionally scoped to a file line."""
    if line is not None and line < 1:
        cli_bail("--line must be a 1-based line number", code=CLI_USAGE_EXIT_CODE)
    if line is not None and file is None:
        cli_bail("--line requires --file", code=CLI_USAGE_EXIT_CODE)
    excerpt = ""
    if file is not None and line is not None:
        excerpt = _read_line(file.expanduser().resolve(), line)
    payload = _payload(question=question, file=file, line=line, excerpt=excerpt)
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(payload)
        return
    console.print(_render_table(payload))


__all__ = ["run"]
