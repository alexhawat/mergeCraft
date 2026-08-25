"""Review output dispatch for ``mergecraft review``.

Hunk export writes a **raw** ``{"comments":[...]}`` JSON object to stdout for
pipe-friendly tooling — not the CLI ``emit_cli_json`` envelope used by
``--format json`` on stdout.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import typer

from mergecraft.analyzers.finding import validate_findings_export, write_findings_json
from mergecraft.analyzers.sarif import export_sarif
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.global_surface import emit_cli_json
from mergecraft.findings.hunk_export import (
    count_dropped_file_level_findings,
    export_hunk_comments,
    first_changed_lines_from_diff,
    format_file_level_drop_warning,
)
from mergecraft.review.output import finding_json_records

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.offline_review import OfflineReviewResult

OutputFormat = Literal["text", "json", "jsonl", "sarif", "hunk"]
HunkFileFindings = Literal["drop", "first-changed-line"]


def write_jsonl_findings(path: Path, findings: Sequence[Finding]) -> None:
    """Write one JSON object per line with short-id finding records."""
    lines = [
        json.dumps({"finding": row}, ensure_ascii=False) for row in finding_json_records(findings)
    ]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def emit_review_json_stdout(
    *,
    review_id: str,
    findings: Sequence[Finding],
    output_text: str | None,
) -> None:
    """Emit the review JSON envelope on stdout (root ``--format json``)."""
    records = finding_json_records(findings)
    validate_findings_export({"findings": records})
    emit_cli_json(
        {
            "review_id": review_id,
            "count": len(findings),
            "findings": records,
            "output": output_text,
        }
    )


def dispatch_review_output(
    *,
    effective_output_format: OutputFormat,
    result: OfflineReviewResult,
    findings: Sequence[Finding],
    review_id: str,
    output: Path | None,
    json_output: Path | None,
    json_stdout: bool,
    hunk_file_findings: HunkFileFindings,
    exit_code: int,
) -> None:
    """Write review artifacts after a successful run (stdout/stderr/files)."""
    text = result.output or ""

    if json_output is not None and findings and effective_output_format != "json":
        write_findings_json(
            json_output,
            [row.model_dump(mode="json") for row in findings],
        )

    if effective_output_format == "text":
        if output is not None:
            output.write_text(text, encoding="utf-8")
            console.print(f"[green]wrote[/green] {output}")
        elif json_output is None:
            console.print(text)
        return

    if effective_output_format == "json":
        if json_stdout:
            emit_review_json_stdout(
                review_id=review_id,
                findings=findings,
                output_text=text or None,
            )
        target = json_output or output
        if target is not None and findings:
            write_findings_json(
                target,
                [row.model_dump(mode="json") for row in findings],
            )
        if target is not None and target.is_file():
            console.print(f"[green]wrote[/green] {target}")
        return

    if effective_output_format == "jsonl":
        target = output
        if target is None:
            console.print("[red]--output is required for --output-format jsonl[/red]")
            raise typer.Exit(exit_code)
        write_jsonl_findings(target, findings)
        console.print(f"[green]wrote[/green] {target}")
        return

    if effective_output_format == "sarif":
        target = output
        if target is None:
            console.print("[red]--output is required for --output-format sarif[/red]")
            raise typer.Exit(exit_code)
        document = export_sarif(list(findings))
        target.write_text(json.dumps(document, indent=2), encoding="utf-8")
        console.print(f"[green]wrote[/green] {target}")
        return

    if effective_output_format == "hunk":
        first_changed_lines: dict[str, int] | None = None
        if hunk_file_findings == "first-changed-line" and result.diff_path:
            diff_path = Path(result.diff_path)
            if diff_path.is_file():
                first_changed_lines = first_changed_lines_from_diff(
                    diff_path.read_text(encoding="utf-8")
                )
        if hunk_file_findings == "drop":
            dropped = count_dropped_file_level_findings(findings)
            if dropped:
                console.print(format_file_level_drop_warning(dropped))
        payload = export_hunk_comments(
            findings,
            file_findings=hunk_file_findings,
            first_changed_lines=first_changed_lines,
        )
        typer.echo(json.dumps(payload, ensure_ascii=False))


__all__ = [
    "dispatch_review_output",
    "emit_review_json_stdout",
    "write_jsonl_findings",
]
