"""``mergecraft pipeline`` — lint, show and explain declarative review pipelines (AP6)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer
from rich.table import Table

from mergecraft.agents.registry import load_registry
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
)
from mergecraft.cli.target_dir import target_dir as resolve_target_dir
from mergecraft.config.settings import load_repo_settings
from mergecraft.orchestrator.executor import PipelineExecutor
from mergecraft.orchestrator.pipeline import (
    PipelineDefinition,
    lint_pipeline_agents,
    parse_pipeline,
)

app = typer.Typer(
    name="pipeline",
    help="Lint and preview declarative review pipelines.",
    no_args_is_help=True,
)


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE)


def _default_pipeline_path(target_dir: Path, settings: object) -> Path:
    configured = getattr(settings, "pipeline", None)
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else target_dir / path
    return target_dir / ".mergecraft" / "pipeline.yaml"


def _load_pipeline(target_dir: Path) -> tuple[PipelineDefinition, Path]:
    settings = load_repo_settings(root=target_dir)
    path = _default_pipeline_path(target_dir, settings)
    if not path.is_file():
        _bail(f"pipeline file not found: {path}")
    text = path.read_text(encoding="utf-8")
    return parse_pipeline(text), path


@app.command("lint")
def lint_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Validate the pipeline file and registry agent references."""
    target_dir = resolve_target_dir(cwd)
    settings = load_repo_settings(root=target_dir)
    pipeline, path = _load_pipeline(target_dir)
    registry = load_registry(settings=settings, repo_root=target_dir)
    errors = lint_pipeline_agents(pipeline, registry)
    if errors:
        for err in errors:
            typer.echo(err, err=True)
        raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE)
    console.print(f"[green]pipeline OK[/green] ({path})")


@app.command("show")
def show_cmd(
    diff: Path = typer.Option(..., "--diff", help="Unified diff to preview against."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Preview which pipeline steps would run or skip for a diff."""
    target_dir = resolve_target_dir(cwd)
    settings = load_repo_settings(root=target_dir)
    pipeline, _path = _load_pipeline(target_dir)
    registry = load_registry(settings=settings, repo_root=target_dir)
    executor = PipelineExecutor(registry=registry, settings=settings)
    result = executor.run(
        pipeline,
        repo_root=target_dir,
        diff_path=diff.resolve(),
    )
    table = Table(title="Pipeline preview")
    table.add_column("step")
    table.add_column("status")
    table.add_column("detail")
    for record in result.step_records:
        detail = record.skip_reason or ", ".join(record.dispatched_agents)
        table.add_row(record.step_id, record.status, detail)
    console.print(table)


@app.command("explain")
def explain_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Working directory."),
) -> None:
    """Print pipeline step ids and predicate vocabulary."""
    target_dir = resolve_target_dir(cwd)
    pipeline, path = _load_pipeline(target_dir)
    console.print(f"pipeline: {path}")
    for step_id in pipeline.step_ids():
        console.print(f"  - {step_id}")
    console.print(
        "predicates: changed_paths matches, risk_band >=, languages includes, "
        "analyzer_findings.severity >=, decision.<id> is trivial|not_trivial"
    )


__all__ = ["app"]
