"""``mergecraft describe`` — output-only PR summary (#351 / D10 / D13).

Exports: ``run``
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import typer

from mergecraft.analyzers.scope import changed_paths_from_scope, parse_diff_scope
from mergecraft.classify.change_clustering import cluster_changes
from mergecraft.cli.global_surface import emit_cli_json, wants_json_output
from mergecraft.config.settings import load_repo_settings
from mergecraft.pr import (
    DescribeOutput,
    TodoFinding,
    build_describe_output,
    classify_effort_band,
    generate_pr_suggestions,
    scan_todo_additions,
    suggest_labels,
)
from mergecraft.pr.similar import (
    SimilarChange,
    SimilarIssue,
    find_similar_changes,
    find_similar_issues,
)
from mergecraft.review.split_advisor import recommend_pr_split
from mergecraft.utils.git_hardening import git_argv


def _read_diff(repo_root: Path) -> str:
    if not (repo_root / ".git").exists():
        return ""
    try:
        completed = subprocess.run(
            git_argv(["diff", "HEAD"]),
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def _line_counts(diff: str) -> tuple[int, int]:
    added = 0
    deleted = 0
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            deleted += 1
    return added, deleted


def _split_groups(paths: list[str]) -> list[dict[str, object]]:
    intents = {path: path.split("/", 1)[0] for path in paths}
    clustered = cluster_changes({"changed_paths": paths}, intents=intents)
    groups: list[dict[str, object]] = [
        {"id": group.id, "paths": group.paths, "intent": group.intent}
        for group in clustered.independent_groups
    ]
    if groups:
        return groups
    if paths:
        return [{"id": "all", "paths": paths, "intent": None}]
    return []


def _render_text(
    *,
    described: DescribeOutput,
    labels: list[str],
    todos: list[TodoFinding],
    effort_band: str,
    effort_rationale: str,
    changelog: str,
    docs: str,
    tests: str,
    split_summary: str,
    similar_issues: list[SimilarIssue],
    similar_changes: list[SimilarChange],
) -> str:
    todo_lines = (
        [f"- `{item.path}:{item.line}` {item.text} ({item.risk_level})" for item in todos]
        if todos
        else ["- none"]
    )
    issue_lines = [f"- {item.title}" for item in similar_issues] if similar_issues else ["- none"]
    change_lines = (
        [f"- {item.title or item.sha or 'overlap'}" for item in similar_changes]
        if similar_changes
        else ["- none"]
    )
    return "\n".join(
        [
            f"# Title\n\n{described.title}",
            "",
            f"## Summary\n\n{described.body}",
            "",
            f"## Walkthrough\n\n{described.walkthrough}",
            "",
            f"## Risk\n\n{described.risk_summary}",
            "",
            f"## Tests\n\n{described.test_summary}",
            "",
            f"## Labels\n\n{', '.join(labels) if labels else 'none'}",
            "",
            "## TODOs\n\n" + "\n".join(todo_lines),
            "",
            f"## Effort\n\n{effort_band}: {effort_rationale}",
            "",
            f"## Changelog suggestion\n\n{changelog or 'none'}",
            "",
            f"## Docs suggestion\n\n{docs or 'none'}",
            "",
            f"## Test suggestion\n\n{tests or 'none'}",
            "",
            f"## Split advice\n\n{split_summary}",
            "",
            "## Similar issues\n\n" + "\n".join(issue_lines),
            "",
            "## Similar changes\n\n" + "\n".join(change_lines),
            "",
        ]
    )


def run(
    ctx: typer.Context,
    repo_root: Path = typer.Option(
        Path("."),
        "--repo-root",
        help="Repository root to describe (read-only; nothing is written).",
    ),
) -> None:
    """Print a PR title, summary, walkthrough, risk areas, and testing notes."""
    root = repo_root.expanduser().resolve()
    load_repo_settings(root=root, load_learnings_files=False)

    diff = _read_diff(root)
    metadata: dict[str, object] = {"title": root.name}
    described = build_describe_output(diff=diff, pr_metadata=metadata, repo_root=root)
    labels = asyncio.run(
        suggest_labels(
            diff=diff,
            pr_metadata=metadata,
            github=None,
            owner="",
            repo="",
        )
    )
    todos = scan_todo_additions(diff)
    paths = changed_paths_from_scope(parse_diff_scope(diff))
    added, deleted = _line_counts(diff)
    effort = classify_effort_band(
        diff=diff,
        pr_metadata=metadata,
        change_signals={
            "files_changed": len(paths),
            "lines_added": added,
            "lines_deleted": deleted,
        },
    )
    suggestions = generate_pr_suggestions(
        diff=diff,
        pr_metadata=metadata,
        kinds=("changelog", "docs", "tests"),
        repo_root=root,
    )
    split = recommend_pr_split(_split_groups(paths))
    similar_issues = find_similar_issues(title=described.title)
    similar_changes = find_similar_changes(paths=paths, repo_root=root)

    payload = {
        "title": described.title,
        "summary": described.body,
        "walkthrough": described.walkthrough,
        "risk": described.risk_summary,
        "tests": described.test_summary,
        "labels": labels.suggested,
        "todos": [item.model_dump(mode="json") for item in todos],
        "effort": {"band": effort.band, "rationale": effort.rationale},
        "changelog": suggestions.changelog,
        "docs": suggestions.docs,
        "test_suggestion": suggestions.tests,
        "split": split.summary,
        "similar_issues": [item.model_dump(mode="json") for item in similar_issues],
        "similar_changes": [item.model_dump(mode="json") for item in similar_changes],
    }
    if wants_json_output(ctx, json_flag=False):
        emit_cli_json(payload)
        return
    typer.echo(
        _render_text(
            described=described,
            labels=labels.suggested,
            todos=todos,
            effort_band=effort.band,
            effort_rationale=effort.rationale,
            changelog=suggestions.changelog,
            docs=suggestions.docs,
            tests=suggestions.tests,
            split_summary=split.summary,
            similar_issues=similar_issues,
            similar_changes=similar_changes,
        )
    )


__all__ = ["run"]
