"""Changed-line coverage: did every changed hunk reach the reviewer?

A review can reach a verdict without every changed hunk ever reaching the reviewer, and
nothing recorded that. This module accounts for it, as structural evidence.

* **The universe** is every changed hunk of the authoritative PR diff, read with
  :func:`mergecraft.analyzers.scope.parse_diff_scope` (deleted-only hunks included,
  binary headers excluded).
* **Covered** means mediated evidence only: the hunk was in the diff the reviewer was
  handed, or an observed mediated read covered part of it. Absence of evidence is
  *uncovered*, never *unknown* — the opposite of the trajectory auditor's silence
  rule, on purpose, because this check gates the verdict.
* **Unknown ranges** are never coverable: a file GitHub sent line counts for but no
  ``patch``, and the files beyond the files-API page cap, are listed by path and stay
  uncovered, because no lines exist to read.
* **Policy exclusions** (generated, minified and vendored files) are listed as
  ``excluded_generated`` and do not count against completeness.

What this proves is delivery, not comprehension: a driver's native file reads never
cross mergeCraft's wire, so a hunk inside the delivered diff is covered whether or not
the reviewer read it closely.

Exports:
    Hunk: One changed hunk (path and new-side line range).
    coverage_universe: Every changed hunk of a unified diff.
    account_coverage: Pure accounting over a diff and the evidence of delivery.
    coverage_section_for_state: The run's coverage section, read from its state.
    coverage_summary_line: The one line the checks and the record show.
    coverage_gate_reason: The outcome reason for an incomplete run, per policy.
    coverage_policy: ``review.coverage.onIncomplete`` from the pinned settings.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from loguru import logger

from mergecraft.analyzers.scope import changed_paths_from_scope, parse_diff_scope
from mergecraft.classify.generated_files import ChangeSet, finding_survives_generated_policy
from mergecraft.evidence.packet import CoverageSection, UncoveredCause, UncoveredRange

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Mapping, Sequence

    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import ToolState

OnIncomplete = Literal["inconclusive", "warn"]

# The rows a summary line names before it counts the rest.
_SUMMARY_RANGE_CAP: Final[int] = 10
_TRUNCATED_LISTING_PATH: Final[str] = "(files beyond the files-API page cap)"
_REVIEW_MODES: Final[frozenset[str]] = frozenset({"Review", "IncrementalReview"})


@dataclass(frozen=True, order=True, slots=True)
class Hunk:
    """One changed hunk: a path and an inclusive new-side line range."""

    path: str
    start_line: int
    end_line: int

    @property
    def lines(self) -> int:
        return max(self.end_line - self.start_line + 1, 1)


def coverage_universe(diff_text: str) -> list[Hunk]:
    """Return every changed hunk of ``diff_text``, in diff order."""
    scope = parse_diff_scope(diff_text)
    return [
        Hunk(path, start, end)
        for path, ranges in scope.hunk_ranges.items()
        for start, end in ranges
    ]


def _excluded_by_policy(hunk: Hunk, change: ChangeSet) -> bool:
    return not finding_survives_generated_policy(hunk.path, change=change)


def _hunk_was_read(hunk: Hunk, covered: Mapping[str, Sequence[tuple[int, int]]]) -> bool:
    """True when an observed read covered any line of ``hunk``."""
    for start, end in covered.get(hunk.path, ()):
        if start <= hunk.end_line and hunk.start_line <= end:
            return True
    return False


def _uncovered_known(
    universe: Sequence[Hunk],
    *,
    delivered: Collection[Hunk],
    covered_lines: Mapping[str, Sequence[tuple[int, int]]],
    reads_observed: bool,
) -> list[Hunk]:
    """Return the hunks nothing vouches for.

    A hunk is covered when it reached the reviewer in the delivered diff, or when
    an observed read covered lines inside it. ``reads_observed`` is the extra
    condition this rebuild adds: a run whose read tracking produced nothing at
    all cannot claim completeness, whatever was delivered. The read evidence is
    :mod:`mergecraft.evidence.diff_coverage`'s line ranges — the same layer the
    auditor and the pre-submit nudge use.
    """
    if not reads_observed:
        return list(universe)
    return [
        hunk
        for hunk in universe
        if hunk not in delivered and not _hunk_was_read(hunk, covered_lines)
    ]


def account_coverage(
    *,
    authoritative_diff: str,
    delivered_diff: str | None = None,
    unreviewable_paths: Iterable[str] = (),
    diff_truncated: bool = False,
    reads_observed: bool = True,
    covered_lines: Mapping[str, Sequence[tuple[int, int]]] | None = None,
) -> CoverageSection:
    """Account for which changed hunks reached the reviewer.

    Args:
        authoritative_diff: The PR diff the universe is built from.
        delivered_diff: The diff the reviewer was handed; ``None`` means the whole
            authoritative diff was.
        unreviewable_paths: Files with line changes but no inline patch.
        diff_truncated: The files listing hit its page cap, so later files were never seen.
        reads_observed: Whether any read in scope was observed at all. ``False``
            means the run's read tracking produced nothing to vouch for the
            delivered hunks; absence of evidence is uncovered, not unknown,
            because this check gates the verdict.
    """
    universe = coverage_universe(authoritative_diff)
    delivered = set(universe if delivered_diff is None else coverage_universe(delivered_diff))
    scope = parse_diff_scope(authoritative_diff)
    change: ChangeSet = {"changed_paths": changed_paths_from_scope(scope)}
    uncovered_hunks = set(
        _uncovered_known(
            universe,
            delivered=delivered,
            covered_lines=covered_lines or {},
            reads_observed=reads_observed,
        )
    )

    rows: list[UncoveredRange] = []
    covered_hunks = 0
    lines_total = 0
    lines_covered = 0
    for hunk in universe:
        lines_total += hunk.lines
        if hunk not in uncovered_hunks:
            covered_hunks += 1
            lines_covered += hunk.lines
            continue
        cause: UncoveredCause
        if _excluded_by_policy(hunk, change):
            cause = "excluded_generated"
        elif hunk in delivered:
            # Delivered, but the run's reads were never observed.
            cause = "not_observed"
        else:
            cause = "not_delivered"
        rows.append(
            UncoveredRange(
                path=hunk.path, start_line=hunk.start_line, end_line=hunk.end_line, cause=cause
            )
        )

    unknown_rows = 0
    for path in dict.fromkeys(unreviewable_paths):
        rows.append(UncoveredRange(path=path, start_line=0, end_line=0, cause="no_inline_patch"))
        unknown_rows += 1
    if diff_truncated:
        rows.append(
            UncoveredRange(
                path=_TRUNCATED_LISTING_PATH, start_line=0, end_line=0, cause="diff_truncated"
            )
        )
        unknown_rows += 1

    return CoverageSection(
        hunks_total=len(universe) + unknown_rows,
        hunks_covered=covered_hunks,
        lines_total=lines_total,
        lines_covered=lines_covered,
        uncovered=rows,
        complete=all(row.cause == "excluded_generated" for row in rows),
    )


# ── run state ────────────────────────────────────────────────────────────────


def _delivered_diff(state: ToolState) -> str:
    from mergecraft.mcp.tool_state import primary_repo_state

    raw = primary_repo_state(state).diff_path
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError as err:
        logger.debug("coverage: cannot read the delivered diff {} — {}", path, err)
        return ""


def _read_evidence(
    state: ToolState, authoritative: str
) -> tuple[bool, dict[str, list[tuple[int, int]]]]:
    """Return whether any read was observed, and the lines each read covered.

    The evidence comes from :mod:`mergecraft.evidence.diff_coverage`, the same
    line-range layer the auditor and the pre-submit nudge use — one read-tracking
    system, not two. It is computed over the *authoritative* diff so a read of a
    file the delivered diff omitted still counts.
    """
    from mergecraft.evidence.diff_coverage import compute_diff_coverage

    if not authoritative:
        return False, {}
    reads = getattr(state, "tool_calls", None) or []
    breakdown = compute_diff_coverage(authoritative, reads, diff_path=None)
    covered = {
        file.path: [(item.start, item.end) for item in file.covered]
        for file in breakdown.files
        if file.covered
    }
    return breakdown.observed, covered


def coverage_section_for_state(state: ToolState) -> CoverageSection | None:
    """Return the run's coverage section, or ``None`` when there is nothing to account for."""
    record = state.coverage
    delivered = _delivered_diff(state)
    authoritative = (
        record.authoritative_diff if record.authoritative_diff is not None else delivered
    )
    unreviewable = list(record.unreviewable_paths)
    from mergecraft.review_policy.ignore_paths import ReviewIgnore, filter_diff, rename_sources

    ignore = getattr(state, "review_ignore", None)
    if isinstance(ignore, ReviewIgnore) and ignore.active:
        # Files ignored by config are out of scope, not unread (#1109): whatever diff
        # established scope, their hunks never enter the universe.
        # Same change set ``checkout_pr`` judged against: a generated file stays in scope
        # when its generator config changed too, so the check needs every changed path.
        # The record is not trusted as already filtered, because a caller-supplied scope
        # never went through the checkout.
        changed = [*filter_diff(authoritative, None).changed_paths, *unreviewable]
        sources = rename_sources(authoritative)
        filtered_authoritative = filter_diff(authoritative, ignore, changed_paths=changed).text
        filtered_unreviewable = [
            path
            for path in unreviewable
            if not ignore.all_ignored(
                [path, sources[path]] if path in sources else [path], changed_paths=changed
            )
        ]
        # Never filter down to an empty scope: nothing left to account for would read
        # as no gate at all. An all-ignored change is the triage skip's job instead.
        if filtered_authoritative.strip() or filtered_unreviewable or not authoritative.strip():
            authoritative = filtered_authoritative
            delivered = filter_diff(delivered, ignore, changed_paths=changed).text
            unreviewable = filtered_unreviewable
    if not authoritative and not unreviewable and not record.diff_truncated:
        return None
    observed, covered = _read_evidence(state, authoritative)
    return account_coverage(
        authoritative_diff=authoritative,
        delivered_diff=delivered,
        unreviewable_paths=unreviewable,
        diff_truncated=record.diff_truncated,
        reads_observed=observed,
        covered_lines=covered,
    )


# ── the line, the policy, the gate ───────────────────────────────────────────


def _range_label(row: UncoveredRange) -> str:
    if row.start_line <= 0:
        return row.path
    if row.end_line == row.start_line:
        return f"{row.path}:{row.start_line}"
    return f"{row.path}:{row.start_line}-{row.end_line}"


def coverage_summary_line(section: CoverageSection, *, on_incomplete: OnIncomplete | None) -> str:
    """Return ``Coverage: X/Y hunks, N uncovered → inconclusive (ranges)``.

    ``on_incomplete=None`` omits the policy arrow (the record states the gap only).
    """
    counted = [row for row in section.uncovered if row.cause != "excluded_generated"]
    excluded = len(section.uncovered) - len(counted)
    head = f"Coverage: {section.hunks_covered}/{section.hunks_total} hunks"
    if not counted:
        return f"{head}, {excluded} excluded generated" if excluded else head
    line = f"{head}, {len(counted)} uncovered"
    if on_incomplete is not None:
        line += f" → {on_incomplete}"
    listed = ", ".join(_range_label(row) for row in counted[:_SUMMARY_RANGE_CAP])
    overflow = len(counted) - _SUMMARY_RANGE_CAP
    if overflow > 0:
        listed += f", +{overflow} more"
    line += f" ({listed})"
    if excluded:
        line += f"; {excluded} excluded generated"
    return line


def coverage_gate_reason(
    section: CoverageSection | None, *, on_incomplete: OnIncomplete
) -> str | None:
    """Return the outcome reason for an incomplete run, or ``None`` when it is not gated."""
    if section is None or section.complete or on_incomplete == "warn":
        return None
    return coverage_summary_line(section, on_incomplete="inconclusive")


def coverage_policy(ctx: ToolContext, *, fallback: RepoSettings | None = None) -> OnIncomplete:
    """Return ``review.coverage.onIncomplete`` from the pinned settings snapshot.

    ``fallback`` is the run's own resolved settings, used only when no snapshot was
    pinned (offline runs); the default is ``inconclusive``.
    """
    from mergecraft.config import default_settings
    from mergecraft.config.settings_snapshot import pinned_repo_settings_from_context

    settings = pinned_repo_settings_from_context(ctx) or fallback or default_settings()
    return settings.review.coverage.on_incomplete


__all__ = [
    "Hunk",
    "OnIncomplete",
    "account_coverage",
    "coverage_gate_reason",
    "coverage_policy",
    "coverage_section_for_state",
    "coverage_summary_line",
    "coverage_universe",
]
