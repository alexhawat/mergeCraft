"""``mergecraft plan`` — local run preview without provider calls (CC2)."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from mergecraft.analyzers.registry import detect_enabled
from mergecraft.config.settings import load_repo_settings
from mergecraft.mcp.shared import REVIEWER_ALLOWED_TOOL_CLASSES
from mergecraft.offline_review import build_offline_review_prompt
from mergecraft.utils.agent_resolve import (
    effective_model_slugs,
    resolve_model,
    resolve_runtime_agent,
)
from mergecraft.utils.offline_diff import materialize_diff
from mergecraft.utils.source_resolve import SourceResolverSpec, resolve_workspace

console = Console()


def _git_changed_files(repo_root: Path) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
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


def build_plan_report(*, cwd: Path) -> dict[str, object]:
    """Assemble the structured plan preview for a workspace."""
    root = cwd.resolve()
    spec = SourceResolverSpec(cwd=root, invocation_root=root)
    workspace = resolve_workspace(spec)
    repo_root = workspace.cwd
    settings = load_repo_settings(root=repo_root, load_learnings_files=False)
    model_slugs = effective_model_slugs(settings)
    resolved_model = resolve_model(slug=model_slugs[0] if model_slugs else None)
    agent = resolve_runtime_agent(model=resolved_model, settings=settings)
    changed = _git_changed_files(repo_root) or ["."]
    enabled = [
        manifest.id for manifest in detect_enabled(repo_root=repo_root, changed_files=changed)
    ]
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
        diff_path = str(materialization.path)
    return {
        "model_chain": model_slugs,
        "agent": agent.name,
        "toolset": toolset,
        "analyzers": enabled,
        "token_estimate": _estimate_tokens(prompt),
        "diff_path": diff_path,
        "base_ref": base_ref,
    }


def run(
    cwd: Path = typer.Option(Path("."), "--cwd", help="Repository root to plan against."),
) -> None:
    """Preview model chain, toolset, analyzers, and token estimate without provider calls."""
    report = build_plan_report(cwd=cwd)
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
    table.add_row("base ref", str(report["base_ref"]))
    console.print(table)


__all__ = ["build_plan_report", "run"]
