"""``mergecraft workflow`` — consumer workflow authoring for providers/models (#484)."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
import yaml

from mergecraft.cli.agents_cmd import validate_registered_model_slug
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.errors import cli_bail
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE
from mergecraft.cli.provider_cmd import (
    _config_path,
    _load_config_dict,
    _provider_entries,
    _write_config_dict,
    _write_env_label,
    indexed_credential_keys,
    load_provider_registry,
    resolve_provider_harness,
)
from mergecraft.cli.tracing_logfire_wf_yaml import _is_action_uses
from mergecraft.cli.workflow_wf_yaml import (
    DEFAULT_WORKFLOW_RELATIVE_PATH,
    WorkflowChange,
    WorkflowYamlError,
    apply_model_prioritize,
    apply_model_wiring,
    apply_provider_env_wiring,
    render_workflow_diff,
)
from mergecraft.config.provider_registry import (
    allocate_env_index,
    list_supported_harnesses,
    validate_http_url,
)

app = typer.Typer(
    help="Author provider and model wiring in the consumer GitHub Actions workflow.",
    no_args_is_help=True,
)

provider_app = typer.Typer(
    help="Provider env wiring for mergeCraft workflow steps.", no_args_is_help=True
)
model_app = typer.Typer(help="Model wiring for mergeCraft workflow steps.", no_args_is_help=True)
agents_app = typer.Typer(
    help="Agent model wiring for mergeCraft workflow steps.", no_args_is_help=True
)

app.add_typer(provider_app, name="provider")
app.add_typer(model_app, name="model")
app.add_typer(agents_app, name="agents")


def _workflow_option() -> Path:
    return Path(DEFAULT_WORKFLOW_RELATIVE_PATH)


def _resolve_workflow_path(workflow: Path, repo_root: Path) -> Path:
    """Anchor a relative ``--workflow`` to ``--cwd``.

    ``--cwd`` scopes the registry config, so a relative workflow path left
    against the process cwd would let one invocation read config from one
    repository and rewrite the workflow of another.
    """
    if workflow.is_absolute():
        return workflow
    return repo_root / workflow


def _emit_workflow_change(
    workflow: Path,
    change: WorkflowChange,
    *,
    apply: bool,
) -> None:
    if change.was_modified:
        console.print(render_workflow_diff(workflow, change))
    else:
        console.print(
            f"[dim]{workflow} already matches the requested wiring; no changes needed.[/dim]"
        )

    if not apply:
        console.print("[dim]dry-run (re-run with --apply to write)[/dim]")
        raise typer.Exit(CLI_SUCCESS_EXIT_CODE)

    try:
        _atomic_write_text(workflow, change.new_text)
    except OSError as exc:
        cli_bail(f"could not write {workflow}: {exc}")
    console.print(f"[green]wrote[/green] {workflow}")


def _atomic_write_text(path: Path, text: str) -> None:
    """Replace *path* via a sibling temp file and rename.

    An in-place write truncates first, so a crash mid-write would leave the
    consumer workflow corrupt. The rename is atomic: the file is either the old
    content or the new one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.is_file() else None
    tmp_fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            tmp_path.chmod(mode)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def _restore_workflow(workflow: Path, previous: str | None) -> None:
    """Put *workflow* back to *previous* after a failed config write."""
    try:
        if previous is None:
            workflow.unlink(missing_ok=True)
        else:
            workflow.write_text(previous, encoding="utf-8")
    except OSError as exc:
        console.print(f"[red]could not restore {workflow} after a failed config write: {exc}[/red]")


def _plan_provider_for_workflow(
    repo_root: Path,
    *,
    label: str,
    url: str | None,
    harness: str | None,
    persist: bool,
) -> tuple[dict[str, Any], int, Callable[[], None] | None]:
    """Resolve or register a provider, returning a deferred config write.

    The third element writes the config (and any ``.env`` label) when *persist*
    is set. It is deliberately not run here: the caller must invoke it only
    after the workflow file has been written, so a failure partway through
    cannot leave config pointing at one endpoint and the workflow at another.
    """
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    entries = _provider_entries(data)
    normalised_label = label.strip()
    if not normalised_label:
        cli_bail("label must not be empty")

    for entry in entries:
        if str(entry.get("label", "")).lower() == normalised_label.lower():
            env_index = int(entry["envIndex"])
            resolved_url = entry.get("url")
            if url is not None:
                try:
                    resolved_url = validate_http_url(url)
                except ValueError as exc:
                    cli_bail(str(exc))
            if resolved_url is None:
                cli_bail(f"provider {normalised_label!r} requires --url (absolute http(s) URL)")
            elif url is None:
                # A stored row is written into workflow YAML verbatim, so it has
                # to clear the same bar as a freshly supplied --url.
                try:
                    resolved_url = validate_http_url(str(resolved_url))
                except ValueError as exc:
                    cli_bail(f"provider {normalised_label!r} has an invalid stored url: {exc}")
            # Carry the validated override onto the row that gets wired and
            # persisted; returning the untouched entry would silently keep the
            # old endpoint after accepting --url.
            if resolved_url == entry.get("url"):
                return entry, env_index, None
            entry["url"] = resolved_url
            if not persist:
                return entry, env_index, None

            def _commit_url_change() -> None:
                data["providers"] = entries
                _write_config_dict(config_path, data)

            return entry, env_index, _commit_url_change

    try:
        resolved_harness = resolve_provider_harness(normalised_label, harness=harness)
    except ValueError as exc:
        cli_bail(str(exc))

    new_provider_url: str | None = None
    if url is not None:
        try:
            new_provider_url = validate_http_url(url)
        except ValueError as exc:
            cli_bail(str(exc))
    else:
        cli_bail(f"provider {normalised_label!r} requires --url (absolute http(s) URL)")

    env_index = allocate_env_index(entries)
    entry = {
        "label": normalised_label,
        "harness": resolved_harness,
        "envIndex": env_index,
        "url": new_provider_url,
    }
    if not persist:
        return entry, env_index, None

    def _commit_new_provider() -> None:
        entries.append(entry)
        data["providers"] = entries
        _write_config_dict(config_path, data)
        _write_env_label(env_index, normalised_label, repo_root)

    return entry, env_index, _commit_new_provider


def _primary_secret_name(entry: dict[str, Any]) -> str:
    keys = indexed_credential_keys(entry)
    for key in keys:
        if key.endswith("_API_KEY"):
            return key
    return keys[0] if keys else f"LLM_PROVIDER_{int(entry['envIndex'])}_API_KEY"


def _print_missing_secret_guidance(entry: dict[str, Any]) -> None:
    for secret_name in indexed_credential_keys(entry):
        console.print(
            f"[yellow]GitHub Actions secret still required:[/yellow] {secret_name} "
            f"(run [cyan]mergecraft provider auth {entry.get('label')}[/cyan] or "
            f"[cyan]gh secret set {secret_name}[/cyan])"
        )


def _resolve_registered_model(
    repo_root: Path,
    *,
    provider: str,
    model: str,
) -> str:
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    return validate_registered_model_slug(data, provider, model)


def _iter_mergecraft_steps(workflow_path: Path) -> list[dict[str, Any]]:
    try:
        text = workflow_path.read_text(encoding="utf-8")
    except OSError as exc:
        cli_bail(f"could not read {workflow_path}: {exc}")
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        cli_bail(f"could not parse {workflow_path}: {exc}")
    if not isinstance(parsed, dict):
        cli_bail(f"{workflow_path} must be a mapping at the top level")
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        return []
    rows: list[dict[str, Any]] = []
    for job_name, job_def in jobs.items():
        if not isinstance(job_def, dict):
            continue
        steps = job_def.get("steps")
        if not isinstance(steps, list):
            continue
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str) or not _is_action_uses(uses):
                continue
            rows.append(
                {
                    "job": job_name,
                    "index": i,
                    "id": step.get("id") or step.get("name") or f"job:{job_name}/step:{i}",
                    "model": (step.get("with") or {}).get("model")
                    if isinstance(step.get("with"), dict)
                    else None,
                    "env": step.get("env") if isinstance(step.get("env"), dict) else {},
                }
            )
    return rows


@app.command("list")
def list_cmd(
    workflow: Path = typer.Option(
        _workflow_option(),
        "--workflow",
        "-w",
        help=f"Path to the consumer workflow YAML (default: {DEFAULT_WORKFLOW_RELATIVE_PATH}).",
        exists=False,
    ),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """List provider/model wiring present in mergeCraft workflow steps."""
    repo_root = cwd.resolve()
    workflow = _resolve_workflow_path(workflow, repo_root)
    steps = _iter_mergecraft_steps(workflow)
    if not steps:
        console.print(f"[yellow]no uses: alexhawat/mergeCraft steps found in {workflow}[/yellow]")
        return

    registry = load_provider_registry(_config_path(repo_root))
    for row in steps:
        model = row.get("model")
        console.print(f"[bold]{row['id']}[/bold]  model={model!r}")
        env_map = row.get("env") or {}
        if not isinstance(env_map, dict):
            continue
        for key, value in env_map.items():
            if not isinstance(key, str):
                continue
            if key.startswith("MERGECRAFT_CUSTOM_PROVIDER_") or "API_KEY" in key:
                console.print(f"  env.{key}={value}")
        if model and isinstance(model, str) and "/" in model:
            provider_label, model_tail = model.split("/", 1)
            entry = registry.lookup(provider_label)
            if entry is not None:
                for secret_name in indexed_credential_keys(entry):
                    console.print(f"  secret: {secret_name}")
                console.print(f"  provider: {provider_label}  model: {model_tail}")


@provider_app.command("harnesses")
def provider_harnesses_cmd() -> None:
    """List supported agent harnesses (generated from code)."""
    for row in list_supported_harnesses():
        console.print(f"{row.name}  {row.description}")


@provider_app.command("add")
def provider_add_cmd(
    label: str = typer.Option(..., "--label", help="Stable provider handle."),
    url: str | None = typer.Option(None, "--url", help="OpenAI-compatible base URL."),
    harness: str | None = typer.Option(None, "--harness", help="Agent harness for this provider."),
    workflow: Path = typer.Option(
        _workflow_option(),
        "--workflow",
        "-w",
        help=f"Path to the consumer workflow YAML (default: {DEFAULT_WORKFLOW_RELATIVE_PATH}).",
        exists=False,
    ),
    step: str = typer.Option(
        "primary",
        "--step",
        help="Which mergeCraft step to wire (primary, all, or step id/name).",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write changes to disk. Default is dry-run.",
    ),
    force: bool = typer.Option(False, "--force", help="Overwrite differing owned env values."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Register a provider and wire indexed custom-provider env keys into the workflow."""
    repo_root = cwd.resolve()
    workflow = _resolve_workflow_path(workflow, repo_root)
    entry, env_index, commit_config = _plan_provider_for_workflow(
        repo_root,
        label=label,
        url=url,
        harness=harness,
        persist=apply,
    )
    secret_name = _primary_secret_name(entry)
    base_url = str(entry.get("url", ""))
    if not base_url:
        cli_bail(f"provider {label!r} has no base URL")

    try:
        change = apply_provider_env_wiring(
            workflow_path=workflow,
            env_index=env_index,
            label=str(entry.get("label", label)),
            base_url=base_url,
            secret_name=secret_name,
            step_selector=step,
            force=force,
        )
    except WorkflowYamlError as exc:
        cli_bail(str(exc))

    _print_missing_secret_guidance(entry)
    workflow_before = workflow.read_text(encoding="utf-8") if workflow.is_file() else None
    _emit_workflow_change(workflow, change, apply=apply)
    # Only now is the workflow on disk. Persisting earlier would strand config
    # on the new endpoint while Actions still ran the old one. Neither file can
    # be written atomically with the other, so roll the workflow back if the
    # config write then fails, leaving both sides on their previous state.
    if commit_config is not None:
        try:
            commit_config()
        except OSError as exc:
            _restore_workflow(workflow, workflow_before)
            cli_bail(f"could not write provider config: {exc}")


@model_app.command("add")
def model_add_cmd(
    provider: str = typer.Option(..., "--provider", help="Registered provider label."),
    model: str = typer.Argument(..., help="Model id to wire into the workflow."),
    workflow: Path = typer.Option(
        _workflow_option(),
        "--workflow",
        "-w",
        help=f"Path to the consumer workflow YAML (default: {DEFAULT_WORKFLOW_RELATIVE_PATH}).",
        exists=False,
    ),
    step: str = typer.Option("primary", "--step", help="Which mergeCraft step to update."),
    apply: bool = typer.Option(False, "--apply", help="Write changes to disk."),
    force: bool = typer.Option(False, "--force", help="Overwrite differing with.model values."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Wire a registered model into ``with.model`` on a mergeCraft workflow step."""
    repo_root = cwd.resolve()
    workflow = _resolve_workflow_path(workflow, repo_root)
    slug = _resolve_registered_model(repo_root, provider=provider, model=model)
    try:
        change = apply_model_wiring(
            workflow_path=workflow,
            model_slug=slug,
            step_selector=step,
            force=force,
        )
    except WorkflowYamlError as exc:
        cli_bail(str(exc))
    _emit_workflow_change(workflow, change, apply=apply)


@model_app.command("prioritize")
def model_prioritize_cmd(
    provider: str = typer.Option(..., "--provider", help="Registered provider label."),
    model: str = typer.Option(..., "--model", help="Model id to promote."),
    before: str = typer.Option(..., "--before", help="Existing model slug to deprioritize."),
    workflow: Path = typer.Option(
        _workflow_option(),
        "--workflow",
        "-w",
        help=f"Path to the consumer workflow YAML (default: {DEFAULT_WORKFLOW_RELATIVE_PATH}).",
        exists=False,
    ),
    apply: bool = typer.Option(False, "--apply", help="Write changes to disk."),
    force: bool = typer.Option(False, "--force", help="Overwrite differing with.model values."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Promote one model ahead of another in the workflow fallback chain."""
    repo_root = cwd.resolve()
    workflow = _resolve_workflow_path(workflow, repo_root)
    slug = _resolve_registered_model(repo_root, provider=provider, model=model)
    before_slug = before.strip()
    try:
        change = apply_model_prioritize(
            workflow_path=workflow,
            model_slug=slug,
            before_slug=before_slug,
            force=force,
        )
    except WorkflowYamlError as exc:
        cli_bail(str(exc))
    _emit_workflow_change(workflow, change, apply=apply)


@agents_app.command("setmodel")
def agents_setmodel_cmd(
    agent: str = typer.Option(..., "--agent", help="Agent role (e.g. reviewer)."),
    provider: str | None = typer.Option(None, "--provider", help="Registered provider label."),
    model: str | None = typer.Option(None, "--model", help="Model id on the provider."),
    workflow: Path = typer.Option(
        _workflow_option(),
        "--workflow",
        "-w",
        help=f"Path to the consumer workflow YAML (default: {DEFAULT_WORKFLOW_RELATIVE_PATH}).",
        exists=False,
    ),
    step: str = typer.Option(
        "primary",
        "--step",
        help="Which mergeCraft step to update (primary, all, or step id/name).",
    ),
    apply: bool = typer.Option(False, "--apply", help="Write changes to disk."),
    force: bool = typer.Option(False, "--force", help="Overwrite differing with.model values."),
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root."),
) -> None:
    """Wire an agent's primary model into a mergeCraft workflow step."""
    _ = agent  # config validation deferred to registry slug resolution
    repo_root = cwd.resolve()
    workflow = _resolve_workflow_path(workflow, repo_root)
    config_path = _config_path(repo_root)
    data = _load_config_dict(config_path)
    entries = _provider_entries(data)
    labels = [str(entry["label"]) for entry in entries if entry.get("label")]
    if not labels:
        cli_bail("no providers registered — run mergecraft provider add first")

    provider_label = provider or typer.prompt(f"provider ({', '.join(labels)})")
    model_id = model or typer.prompt("model id")
    slug = validate_registered_model_slug(data, provider_label, model_id)

    try:
        change = apply_model_wiring(
            workflow_path=workflow,
            model_slug=slug,
            step_selector=step,
            force=force,
        )
    except WorkflowYamlError as exc:
        cli_bail(str(exc))
    _emit_workflow_change(workflow, change, apply=apply)


__all__ = [
    "agents_app",
    "agents_setmodel_cmd",
    "app",
    "list_cmd",
    "model_add_cmd",
    "model_app",
    "model_prioritize_cmd",
    "provider_add_cmd",
    "provider_app",
    "provider_harnesses_cmd",
]
