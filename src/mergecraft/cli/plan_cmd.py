"""``mergecraft plan`` — local run preview without provider calls (CC2)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import typer
from rich.table import Table

from mergecraft.analyzers.registry import detect_enabled, load_catalog
from mergecraft.cli.consoles import err_console as console
from mergecraft.cli.exits import (
    CLI_CONFIGURATION_EXIT_CODE,
)
from mergecraft.cli.profiles import ReviewProfile, resolve_profile
from mergecraft.config.settings import load_repo_settings
from mergecraft.mcp.shared import REVIEWER_ALLOWED_TOOL_CLASSES
from mergecraft.offline_review import build_offline_review_prompt
from mergecraft.utils.agent_resolve import (
    ModelFallbackPolicyError,
    effective_model_slugs,
    resolve_model,
    resolve_runtime_agent,
)
from mergecraft.utils.git_hardening import git_argv
from mergecraft.utils.offline_diff import materialize_diff
from mergecraft.utils.run_bounds import resolve_run_bounds
from mergecraft.utils.source_resolve import SourceResolverSpec, resolve_workspace


def _git_changed_files(repo_root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            git_argv(["diff", "--name-only", "HEAD"]),
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _estimate_tokens(text: str) -> int:
    # Rough heuristic — good enough for operator preview, not billing.
    return max(1, len(text) // 4)


def _profile_model_chain(
    profile: ReviewProfile | None, settings_model_chain: list[str]
) -> list[str]:
    if profile is None or profile.model_chain is None:
        return settings_model_chain
    return list(profile.model_chain)


def _profile_analyzers(
    *,
    profile: ReviewProfile | None,
    repo_root: Path,
    changed: list[str],
) -> list[str]:
    manifests = detect_enabled(repo_root=repo_root, changed_files=changed)
    if profile is not None and profile.analyzers_security_only:
        security_ids = {
            manifest.id for manifest in load_catalog() if manifest.category == "security"
        }
        return [manifest.id for manifest in manifests if manifest.id in security_ids]
    return [manifest.id for manifest in manifests]


def build_plan_report(
    *,
    cwd: Path,
    profile_name: str | None = None,
    model_override: str | None = None,
) -> dict[str, object]:
    """Assemble the structured plan preview for a workspace."""
    profile = resolve_profile(profile_name)
    root = cwd.resolve()
    spec = SourceResolverSpec(cwd=root, invocation_root=root)
    workspace = resolve_workspace(spec)
    repo_root = workspace.cwd
    settings = load_repo_settings(root=repo_root, load_learnings_files=False)
    model_slugs = _profile_model_chain(profile, effective_model_slugs(settings))
    if model_override:
        model_slugs = [model_override, *model_slugs]
    resolved_model = resolve_model(slug=model_slugs[0] if model_slugs else None)
    agent_label: str
    try:
        agent_label = resolve_runtime_agent(model=resolved_model, settings=settings).name
    except (ValueError, ModelFallbackPolicyError):
        if resolved_model and "/" in resolved_model:
            agent_label = resolved_model.partition("/")[0]
        else:
            agent_label = resolved_model or "unknown"
    changed = _git_changed_files(repo_root) or ["."]
    enabled = _profile_analyzers(profile=profile, repo_root=repo_root, changed=changed)
    bounds = resolve_run_bounds(settings=settings)
    toolset = sorted(cls.value for cls in REVIEWER_ALLOWED_TOOL_CLASSES)
    with tempfile.TemporaryDirectory(prefix="mergecraft-plan-") as tmp:
        materialization = materialize_diff(cwd=repo_root, out_dir=Path(tmp))
        prompt = build_offline_review_prompt(
            diff_path=materialization.path,
            base_ref=materialization.base_ref,
            extra=None,
            json_mode=False,
        )
        base_ref = materialization.base_ref
        # PR #242 review finding ``e8bc195570ae6f1cc8ab5bc6`` — the
        # ``TemporaryDirectory`` closes as soon as the ``with`` block ends,
        # so the raw ``materialization.path`` would point at a missing file.
        # Persist the materialized diff to a path the consumer of the
        # report can read after return (sibling to ``.mergecraft/`` per S1).
        diff_dir = repo_root / ".mergecraft"
        diff_dir.mkdir(parents=True, exist_ok=True)
        stable_diff = diff_dir / "plan-review.diff"
        stable_diff.write_text(materialization.path.read_text(encoding="utf-8"), encoding="utf-8")
        diff_path = str(stable_diff)
    return {
        "model_chain": model_slugs,
        "agent": agent_label,
        "toolset": toolset,
        "analyzers": enabled,
        "token_estimate": _estimate_tokens(prompt),
        "diff_path": diff_path,
        "base_ref": base_ref,
        "profile": profile.name if profile is not None else None,
        "token_budget": bounds.token_budget,
        "cost_budget_usd": bounds.cost_budget_usd,
        "tool_call_budget": bounds.tool_call_budget,
    }


def run(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root to plan against."),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Named profile bundle (fast, deep, security).",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Model slug override (wins over the profile bundle).",
    ),
) -> None:
    """Preview model chain, toolset, analyzers, and token estimate without provider calls."""
    from mergecraft.cli.profiles import apply_profile_env

    try:
        resolve_profile(profile)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(CLI_CONFIGURATION_EXIT_CODE) from exc

    with apply_profile_env(resolve_profile(profile)):
        report = build_plan_report(cwd=cwd, profile_name=profile, model_override=model)
    model_chain = report["model_chain"]
    toolset = report["toolset"]
    analyzers = report["analyzers"]
    assert isinstance(model_chain, list)
    assert isinstance(toolset, list)
    assert isinstance(analyzers, list)
    table = Table(title="mergecraft plan", show_header=True, header_style="bold")
    table.add_column("section", style="cyan")
    table.add_column("value")
    table.add_row("model chain", ", ".join(str(item) for item in model_chain))
    table.add_row("agent", str(report["agent"]))
    table.add_row("toolset", ", ".join(str(item) for item in toolset))
    table.add_row("analyzers", ", ".join(str(item) for item in analyzers) or "(none)")
    table.add_row("token estimate", str(report["token_estimate"]))
    if report.get("profile"):
        table.add_row("profile", str(report["profile"]))
    table.add_row("token budget", str(report["token_budget"]))
    table.add_row("cost budget (USD)", str(report["cost_budget_usd"]))
    table.add_row("tool-call budget", str(report["tool_call_budget"]))
    table.add_row("base ref", str(report["base_ref"]))
    console.print(table)


__all__ = ["build_plan_report", "run"]
