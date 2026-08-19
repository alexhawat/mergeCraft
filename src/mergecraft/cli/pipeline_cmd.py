"""``mergecraft pipeline`` — lint, show and explain declarative review pipelines (AP6)."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console
from rich.table import Table

from mergecraft.agents.registry import load_registry
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
console = Console()


def _bail(msg: str) -> NoReturn:
    console.print(f"[red]{msg}[/red]")
    raise typer.Exit(1)


def _target_dir(cwd: Path) -> Path:
    """The directory this command operates on — ``cwd``, resolved.

    Deliberately not ``git_repo_root``: these commands act on whatever tree they
    are pointed at, including one that is not a git checkout at all. Named for
    that so it cannot be mistaken for the canonical repo-root helper in
    ``utils/workspace.py``.
    """
    return cwd.resolve()


def _default_pipeline_path(repo_root: Path, settings: object) -> Path:
    configured = getattr(settings, "pipeline", None)
    if configured:
        path = Path(configured)
        return path if path.is_absolute() else repo_root / path
    return repo_root / ".mergecraft" / "pipeline.yaml"


def _load_pipeline(repo_root: Path) -> tuple[PipelineDefinition, Path]:
    settings = load_repo_settings(root=repo_root)
    path = _default_pipeline_path(repo_root, settings)
    if not path.is_file():
        _bail(f"pipeline file not found: {path}")
    text = path.read_text(encoding="utf-8")
    return parse_pipeline(text), path


@app.command("lint")
def lint_cmd(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Validate the pipeline file and registry agent references."""
    repo_root = _target_dir(cwd)
    settings = load_repo_settings(root=repo_root)
    pipeline, path = _load_pipeline(repo_root)
    registry = load_registry(settings=settings, repo_root=repo_root)
    errors = lint_pipeline_agents(pipeline, registry)
    if errors:
        for err in errors:
            typer.echo(err, err=True)
        raise typer.Exit(1)
    console.print(f"[green]pipeline OK[/green] ({path})")


@app.command("show")
def show_cmd(
    diff: Path = typer.Option(..., "--diff", help="Unified diff to preview against."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Preview which pipeline steps would run or skip for a diff."""
    repo_root = _target_dir(cwd)
    settings = load_repo_settings(root=repo_root)
    pipeline, _path = _load_pipeline(repo_root)
    registry = load_registry(settings=settings, repo_root=repo_root)
    executor = PipelineExecutor(registry=registry, settings=settings)
    result = executor.run(
        pipeline,
        repo_root=repo_root,
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
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Print pipeline step ids and predicate vocabulary."""
    repo_root = _target_dir(cwd)
    pipeline, path = _load_pipeline(repo_root)
    console.print(f"pipeline: {path}")
    for step_id in pipeline.step_ids():
        console.print(f"  - {step_id}")
    console.print(
        "predicates: changed_paths matches, risk_band >=, languages includes, "
        "analyzer_findings.severity >=, decision.<id> is trivial|not_trivial"
    )


__all__ = ["app"]
