"""Advisory label suggestions — never applied via GitHub APIs (DG8).

Library surface only — not wired into ``select_mode`` / dispatch yet (DG7/DG8 pairing).
"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from mergecraft.analyzers.scope import changed_paths_from_scope, parse_diff_scope


class GitHubLabelsClient(Protocol):
    async def add_labels(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        labels: list[str],
    ) -> dict[str, object]: ...

    async def create_label(
        self,
        owner: str,
        repo: str,
        name: str,
        **kwargs: object,
    ) -> dict[str, object]: ...


class LabelSuggestionsResult(BaseModel):
    """Suggested labels for human/application — advisory only."""

    model_config = ConfigDict(extra="forbid")

    suggested: list[str]
    applied: bool = False


def _existing_labels(pr_metadata: dict[str, object]) -> set[str]:
    raw = pr_metadata.get("labels")
    if not isinstance(raw, list):
        return set()
    return {label.strip().lower() for label in raw if isinstance(label, str) and label.strip()}


async def suggest_labels(
    *,
    diff: str,
    pr_metadata: dict[str, object],
    github: GitHubLabelsClient | Any,
    owner: str,
    repo: str,
) -> LabelSuggestionsResult:
    """Suggest labels from diff signals without calling GitHub label APIs."""
    _ = github
    _ = owner
    _ = repo

    paths = changed_paths_from_scope(parse_diff_scope(diff))
    existing = _existing_labels(pr_metadata)
    suggested: list[str] = []

    if any("auth" in path.lower() or "security" in path.lower() for path in paths):
        suggested.append("security")
    if any(path.endswith((".md", ".rst")) or "/docs/" in path for path in paths):
        suggested.append("documentation")
    if any("test" in path.lower() for path in paths):
        suggested.append("tests")
    if not suggested:
        suggested.append("enhancement")

    suggested = [label for label in suggested if label.lower() not in existing]
    if not suggested:
        suggested = ["needs-review"]

    return LabelSuggestionsResult(suggested=suggested, applied=False)


__all__ = ["GitHubLabelsClient", "LabelSuggestionsResult", "suggest_labels"]
