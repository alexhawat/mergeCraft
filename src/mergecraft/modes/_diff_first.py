"""Hard scope-discipline instruction shared by every review mode.

mergeCraft already materialises the authoritative PR diff to disk and returns
it as ``diffPath`` (and, on a re-review, ``incrementalDiffPath``). A reviewer
that re-derives the change set with ``git diff``/``git grep``/``git log`` pays
for it twice: the calls are not recorded as file reads, so coverage cannot see
them, and on a shallow Actions checkout they can fail outright. This text is
rendered into Review and IncrementalReview at ``compute_modes`` time, so every
consumer gets it — not only this repository's workflow.

The instruction is untrusted-input-adjacent: it tells the agent what to read,
never what to conclude, and cannot change a gate. It contains no interpolation
except the mode renderer's normal `${t("...")}` tool reference.

Module: mergecraft.modes._diff_first
Depends: mergecraft.modes (rendering only)

Exports:
    DIFF_FIRST_INSTRUCTION — The rendered scope-discipline block.
"""

from __future__ import annotations

DIFF_FIRST_INSTRUCTION: str = (
    "### Scope discipline (hard rule)\n\n"
    "The diff mergeCraft materialises on disk is the authoritative change set. "
    'Read `${t("checkout_pr")}`\'s returned `diffPath` as your first action. '
    "When `incrementalDiffPath` is present, read that first and treat it as the review "
    "scope; use the full `diffPath` only to anchor line numbers — do not re-read the "
    "whole PR. Do **not** run `git diff`, `git grep`, or `git log` to reconstruct the "
    "change set: those re-derive a scope the diff already defines, pull in base-branch "
    "noise, and fail on shallow checkouts. Only after the diff is read, read the "
    "surrounding files a candidate finding actually needs. Batch every independent "
    "read/grep/glob into a single turn; keep dependent calls for the next turn after "
    "their inputs are available."
)

__all__ = ["DIFF_FIRST_INSTRUCTION"]
