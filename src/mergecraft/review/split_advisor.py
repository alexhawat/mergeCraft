"""Advisory PR split recommendations from change clusters (DG2, G6).

Split advice is text-only — convention 3 forbids writes to the reviewed tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(slots=True)
class SuggestedPR:
    """One suggested pull request in a split recommendation."""

    paths: list[str] = field(default_factory=list)
    intent: str | None = None
    label: str | None = None


@dataclass(slots=True)
class SplitAdvice:
    """Advisory split recommendation — never mutates the repository."""

    recommend_split: bool
    suggested_prs: list[SuggestedPR] = field(default_factory=list)
    summary: str = ""
    advisory_only: bool = True


def recommend_pr_split(
    independent_groups: list[dict[str, Any]],
    *,
    output_path: Path | None = None,
) -> SplitAdvice:
    """Recommend splitting unrelated change groups into separate pull requests.

    Args:
        independent_groups: Cluster dicts with ``paths`` and optional ``intent``.
        output_path: Ignored for writes — split advice is advisory only.

    Returns:
        :class:`SplitAdvice` with human-readable summary text.
    """
    if output_path is not None:
        # Convention 3: never write to the reviewed tree.
        _ = output_path

    if len(independent_groups) < 2:
        return SplitAdvice(
            recommend_split=False,
            summary="Changes appear cohesive; no split recommended.",
            advisory_only=True,
        )

    suggested: list[SuggestedPR] = []
    labels: list[str] = []
    for group in independent_groups:
        paths = list(group.get("paths") or [])
        intent = group.get("intent")
        group_id = str(group.get("id") or intent or paths[0])
        suggested.append(SuggestedPR(paths=paths, intent=intent, label=group_id))
        labels.append(group_id)

    summary = (
        "Recommend splitting this pull request into "
        f"{len(suggested)} independent PRs: {', '.join(labels)}."
    )
    return SplitAdvice(
        recommend_split=True,
        suggested_prs=suggested,
        summary=summary,
        advisory_only=True,
    )


__all__ = ["SplitAdvice", "SuggestedPR", "recommend_pr_split"]
