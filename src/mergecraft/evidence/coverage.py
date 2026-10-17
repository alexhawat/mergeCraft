"""Changed-line coverage: did every changed hunk reach the reviewer?

A review can reach a verdict without every changed hunk ever reaching the reviewer, and
nothing recorded that. This module accounts for it, as structural evidence.

* **The universe** is every changed hunk of the authoritative PR diff, read with
  :func:`mergecraft.analyzers.scope.parse_diff_scope` (deleted-only hunks included,
  binary headers excluded).
* **Covered** means mediated evidence only: the hunk was in the diff the reviewer was
  handed, a mediated tool call read its file, or a follow-up turn handed it back.
  Absence of evidence is *uncovered*, never *unknown* — the opposite of the trajectory
  auditor's silence rule, on purpose, because this check gates the verdict.
* **Unknown ranges** are never coverable: a file GitHub sent line counts for but no
  ``patch``, and the files beyond the files-API page cap, are listed by path and stay
  uncovered, because no lines exist to hand back.
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
    plan_coverage_followup: The one bounded follow-up, when due.
    mark_followup_sent: Record that a follow-up handed hunks back.
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
    from collections.abc import Collection, Iterable, Sequence

    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import ToolState

OnIncomplete = Literal["inconclusive", "warn"]

# The rows a summary line names before it counts the rest.
_SUMMARY_RANGE_CAP: Final[int] = 10
# A follow-up prompt carries hunk text up to this many characters; hunks that do not
# fit are not handed back, so they stay uncovered rather than pretending to be sent.
_FOLLOWUP_CHAR_BUDGET: Final[int] = 120_000
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


def _uncovered_known(
    universe: Sequence[Hunk],
    *,
    delivered: Collection[Hunk],
    read_paths: Collection[str],
    followed_up: Collection[Hunk],
) -> list[Hunk]:
    return [
        hunk
        for hunk in universe
        if hunk not in delivered and hunk.path not in read_paths and hunk not in followed_up
    ]


def account_coverage(
    *,
    authoritative_diff: str,
    delivered_diff: str | None = None,
    unreviewable_paths: Iterable[str] = (),
    diff_truncated: bool = False,
    read_paths: Collection[str] = (),
    followup_hunks: Collection[Hunk] = (),
    budget_exhausted: bool = False,
) -> CoverageSection:
    """Account for which changed hunks reached the reviewer.

    Args:
        authoritative_diff: The PR diff the universe is built from.
        delivered_diff: The diff the reviewer was handed; ``None`` means the whole
            authoritative diff was.
        unreviewable_paths: Files with line changes but no inline patch.
        diff_truncated: The files listing hit its page cap, so later files were never seen.
        read_paths: Paths a mediated tool call read.
        followup_hunks: Hunks a follow-up turn handed back.
        budget_exhausted: The run had no budget left for a follow-up; what stayed
            uncovered says so.
    """
    universe = coverage_universe(authoritative_diff)
    delivered = set(universe if delivered_diff is None else coverage_universe(delivered_diff))
    scope = parse_diff_scope(authoritative_diff)
    change: ChangeSet = {"changed_paths": changed_paths_from_scope(scope)}
    uncovered_hunks = set(
        _uncovered_known(
            universe,
            delivered=delivered,
            read_paths=set(read_paths),
            followed_up=set(followup_hunks),
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
        elif budget_exhausted:
            cause = "budget_exhausted"
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


def _mediated_read_paths(state: ToolState) -> set[str]:
    """Paths a successful mediated read call named (``shell`` / ``git`` reads)."""
    from mergecraft.evidence.trajectory import ToolCallRecord

    paths: set[str] = set()
    for raw in getattr(state, "tool_calls", None) or []:
        try:
            call = ToolCallRecord.model_validate(raw)
        except Exception:  # a malformed row proves nothing, and never fails the run
            continue
        if call.intent == "read" and call.ok and call.outcome_ok is not False:
            paths.update(call.paths)
    return paths


def coverage_section_for_state(state: ToolState) -> CoverageSection | None:
    """Return the run's coverage section, or ``None`` when there is nothing to account for."""
    record = state.coverage
    delivered = _delivered_diff(state)
    authoritative = (
        record.authoritative_diff if record.authoritative_diff is not None else delivered
    )
    if not authoritative and not record.unreviewable_paths and not record.diff_truncated:
        return None
    return account_coverage(
        authoritative_diff=authoritative,
        delivered_diff=delivered,
        unreviewable_paths=record.unreviewable_paths,
        diff_truncated=record.diff_truncated,
        read_paths=_mediated_read_paths(state),
        followup_hunks={Hunk(*row) for row in record.followup_hunks},
        budget_exhausted=record.budget_blocked,
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


# ── the one bounded follow-up ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CoverageFollowup:
    """The follow-up turn: its prompt and the hunks whose text it carries."""

    prompt: str
    hunks: tuple[Hunk, ...]


def _hunk_texts(diff_text: str) -> dict[Hunk, str]:
    """Map each hunk of ``diff_text`` to its diff text (header lines included)."""
    texts: dict[Hunk, str] = {}
    for chunk in diff_text.split("diff --git ")[1:]:
        lines = ("diff --git " + chunk).splitlines()
        first = next((i for i, line in enumerate(lines) if line.startswith("@@")), None)
        if first is None:
            continue
        header, body = lines[:first], lines[first:]
        starts = [i for i, line in enumerate(body) if line.startswith("@@")]
        for n, begin in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(body)
            segment = body[begin:end]
            for hunk in coverage_universe("\n".join([*header, *segment]) + "\n"):
                texts[hunk] = "\n".join(segment)
    return texts


def plan_coverage_followup(state: ToolState) -> CoverageFollowup | None:
    """Return the follow-up due before finalizing, or ``None``.

    Due once, only for a review run that holds a verdict, only when known hunks remain
    uncovered, and only while budget remains. With no budget it records why and returns
    ``None`` — what stays uncovered is then named ``budget_exhausted``.
    """
    record = state.coverage
    if record.followup_sent or state.selected_mode not in _REVIEW_MODES:
        return None
    if state.terminal_submission is None and not state.final_summary_written:
        return None
    delivered = _delivered_diff(state)
    authoritative = (
        record.authoritative_diff if record.authoritative_diff is not None else delivered
    )
    universe = coverage_universe(authoritative)
    scope_change: ChangeSet = {
        "changed_paths": changed_paths_from_scope(parse_diff_scope(authoritative))
    }
    pending = [
        hunk
        for hunk in _uncovered_known(
            universe,
            delivered=set(coverage_universe(delivered)),
            read_paths=_mediated_read_paths(state),
            followed_up={Hunk(*row) for row in record.followup_hunks},
        )
        if not _excluded_by_policy(hunk, scope_change)
    ]
    if not pending:
        return None
    tracker = record.budget_tracker
    if tracker is not None and getattr(tracker, "last_exhausted", None) is not None:
        record.budget_blocked = True
        logger.warning(
            "coverage: {} changed hunk(s) never reached the reviewer and the run has no "
            "budget left for the follow-up turn",
            len(pending),
        )
        return None
    texts = _hunk_texts(authoritative)
    sections: list[str] = []
    handed: list[Hunk] = []
    spent = 0
    for hunk in pending:
        text = texts.get(hunk)
        if text is None or spent + len(text) > _FOLLOWUP_CHAR_BUDGET:
            continue
        spent += len(text)
        handed.append(hunk)
        sections.append(f"### {hunk.path}:{hunk.start_line}-{hunk.end_line}\n```diff\n{text}\n```")
    if not handed:
        return None
    prompt = "\n\n".join(
        [
            "COVERAGE FOLLOW-UP — these changed hunks of the pull request never reached "
            "you during this review. Read each one now and judge it like the rest of "
            "the diff. Your recorded verdict stands unless you submit a replacement: if "
            "these hunks change your assessment, call `submit_review_verdict` again with "
            "the complete corrected verdict; otherwise stop.",
            *sections,
        ]
    )
    return CoverageFollowup(prompt=prompt, hunks=tuple(handed))


def mark_followup_sent(state: ToolState, followup: CoverageFollowup) -> None:
    """Record that the follow-up went out, so it never fires again and its hunks count."""
    record = state.coverage
    record.followup_sent = True
    record.followup_open = True
    record.followup_hunks.extend((h.path, h.start_line, h.end_line) for h in followup.hunks)
    logger.info("coverage: follow-up turn handed back {} uncovered hunk(s)", len(followup.hunks))


__all__ = [
    "CoverageFollowup",
    "Hunk",
    "OnIncomplete",
    "account_coverage",
    "coverage_gate_reason",
    "coverage_policy",
    "coverage_section_for_state",
    "coverage_summary_line",
    "coverage_universe",
    "mark_followup_sent",
    "plan_coverage_followup",
]
