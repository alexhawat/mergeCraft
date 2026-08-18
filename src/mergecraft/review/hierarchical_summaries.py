"""Hierarchical diff summarization for large pull requests (DG2, G6).

Large diffs degrade into a navigable map, cluster summaries, and selected raw
hunks. High-risk regions keep verbatim tokens; reduced scope is always reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mergecraft.utils.run_bounds import ScopeReduction, _diff_file_blocks


@dataclass(slots=True)
class FileMapEntry:
    """One file in the navigable diff map."""

    path: str
    lines_changed: int


@dataclass(slots=True)
class ClusterSummary:
    """Abbreviated summary for one changed file or cluster."""

    path: str
    summary: str
    lines_changed: int


@dataclass(slots=True)
class DiffHunk:
    """A verbatim diff hunk retained in the context payload."""

    path: str
    raw: str


@dataclass(slots=True)
class HierarchicalContext:
    """Map → summaries → hunks context for a large diff."""

    map: list[FileMapEntry] = field(default_factory=list)
    summaries: list[ClusterSummary] = field(default_factory=list)
    hunks: list[DiffHunk] = field(default_factory=list)
    token_estimate: int = 0
    scope_reduction: ScopeReduction | None = None


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _line_count(block: str) -> int:
    if not block:
        return 0
    return block.count("\n") + (0 if block.endswith("\n") else 1)


def build_hierarchical_context(
    diff_text: str,
    *,
    token_budget: int,
    risk_regions: set[str] | None = None,
) -> HierarchicalContext:
    """Build hierarchical review context within a token budget.

    Args:
        diff_text: Unified diff text for the pull request.
        token_budget: Maximum estimated tokens for the rendered context.
        risk_regions: Paths that must retain verbatim diff hunks.

    Returns:
        :class:`HierarchicalContext` with map, summaries, hunks, and any
        recorded :class:`ScopeReduction`.
    """
    risk = risk_regions or set()
    blocks = _diff_file_blocks(diff_text)
    if not blocks:
        return HierarchicalContext()

    map_entries: list[FileMapEntry] = []
    summaries: list[ClusterSummary] = []
    for path, block in blocks:
        lines = _line_count(block)
        map_entries.append(FileMapEntry(path=path, lines_changed=lines))
        summaries.append(
            ClusterSummary(
                path=path,
                summary=f"{path}: {lines} line(s) changed",
                lines_changed=lines,
            )
        )

    map_tokens = sum(
        _estimate_tokens(f"{entry.path} ({entry.lines_changed} lines)") for entry in map_entries
    )
    summary_tokens = sum(_estimate_tokens(summary.summary) for summary in summaries)
    overhead = map_tokens + summary_tokens
    remaining = max(0, token_budget - overhead)

    hunks: list[DiffHunk] = []
    included_paths: set[str] = set()
    omitted_paths: list[str] = []

    risk_blocks = [(path, block) for path, block in blocks if path in risk]
    other_blocks = [(path, block) for path, block in blocks if path not in risk]

    for path, block in risk_blocks:
        cost = _estimate_tokens(block)
        hunks.append(DiffHunk(path=path, raw=block))
        included_paths.add(path)
        remaining = max(0, remaining - cost)

    for path, block in other_blocks:
        cost = _estimate_tokens(block)
        if cost <= remaining or not hunks:
            hunks.append(DiffHunk(path=path, raw=block))
            included_paths.add(path)
            remaining = max(0, remaining - cost)
        else:
            omitted_paths.append(path)

    if not hunks and blocks:
        path, block = blocks[0]
        hunks.append(DiffHunk(path=path, raw=block))
        included_paths.add(path)
        if path in omitted_paths:
            omitted_paths.remove(path)

    total_lines = sum(_line_count(block) for _, block in blocks)
    kept_lines = sum(_line_count(hunk.raw) for hunk in hunks)
    scope_reduction: ScopeReduction | None = None
    if omitted_paths:
        reason = (
            f"token budget reduced scope ({token_budget} tokens); "
            f"{len(omitted_paths)} file(s) summarized only"
        )
        scope_reduction = ScopeReduction(
            original_lines=total_lines,
            kept_lines=kept_lines,
            omitted_paths=sorted(omitted_paths),
            reason=reason,
        )

    rendered_parts = [
        *(f"{entry.path} ({entry.lines_changed} lines)" for entry in map_entries),
        *(summary.summary for summary in summaries),
        *(hunk.raw for hunk in hunks),
    ]
    token_estimate = sum(_estimate_tokens(part) for part in rendered_parts)

    if token_estimate > token_budget and hunks:
        while hunks and token_estimate > token_budget:
            dropped = hunks.pop()
            if dropped.path not in risk and dropped.path not in omitted_paths:
                omitted_paths.append(dropped.path)
            rendered_parts = [
                *(f"{entry.path} ({entry.lines_changed} lines)" for entry in map_entries),
                *(summary.summary for summary in summaries),
                *(hunk.raw for hunk in hunks),
            ]
            token_estimate = sum(_estimate_tokens(part) for part in rendered_parts)
        if omitted_paths and scope_reduction is None:
            scope_reduction = ScopeReduction(
                original_lines=total_lines,
                kept_lines=sum(_line_count(hunk.raw) for hunk in hunks),
                omitted_paths=sorted(set(omitted_paths)),
                reason=(
                    f"token budget reduced scope ({token_budget} tokens); "
                    f"{len(omitted_paths)} file(s) summarized only"
                ),
            )

    return HierarchicalContext(
        map=map_entries,
        summaries=summaries,
        hunks=hunks,
        token_estimate=token_estimate,
        scope_reduction=scope_reduction,
    )


__all__ = [
    "ClusterSummary",
    "DiffHunk",
    "FileMapEntry",
    "HierarchicalContext",
    "build_hierarchical_context",
]
