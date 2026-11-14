"""Re-approval: carry a trusted mergeCraft pass forward when only changelog prose moved.

A pull request that mergeCraft already passed often comes back with nothing new to
review: a merge of the base branch whose only conflict was the changelog, or a one-line
changelog fix. The full review then re-reads every file to conclude what the previous
run already concluded. This module decides, from evidence alone and before any agent
exists, whether the new head is that case.

The evidence is three comparisons and the file modes on each side:

* ``reviewed`` — the pull request's own changes as of the passed head ``P``
  (``base...P``), i.e. what the prior review approved;
* ``current`` — the pull request's own changes at the new head ``H`` (``base...H``);
* ``interdiff`` — every path that changed from ``P`` to ``H`` (``P...H``), whose
  merge base must be ``P`` itself, so ``H`` descends from the reviewed head.

Every path in ``interdiff`` is accounted for, or the answer is a full review:

* a **qualifying** path (``review.fastPath.reapproval.paths``, the root
  ``CHANGELOG.md`` by default) whose PR-authored change at ``H`` is proven prose;
* a path **inherited from the base**: not part of the pull request at ``P`` or at
  ``H``, so ``H`` holds the base's version of it.

A PR-authored path that changed since ``P`` is never accounted for. Every
non-qualifying entry of ``current`` must equal its ``reviewed`` entry exactly — status,
rename source, post-image blob and patch. An identical patch applied to an identical
post-image has an identical pre-image, so this also proves the base side of every
reviewed file is untouched: a clean merge whose upstream edit overlaps a reviewed file
changes that file's patch or blob and gets the normal review. File modes, which the
compare API omits, must match on both sides of both comparisons.

The prior pass is a ``mergecraft-approval`` check run that concluded ``success`` on
``P`` from a trusted GitHub App, and it carries a :class:`ReviewStamp` naming the pull
request, target branch and review-policy digest it was decided under. All three must
match this run. The I/O shell (:mod:`mergecraft.reapproval`) reads the evidence; this
module only decides.

Exports:
    ReviewStamp: The pull request, target branch and policy a verdict was decided under.
    parse_review_stamp: Read a stamp from a check-run summary, or ``None``.
    PriorPass: The trusted check run that passed the reviewed head.
    ChangedFile: One compare-API file entry.
    Comparison: One compare-API answer (merge base and files).
    ReapprovalEvidence: Everything the decision reads.
    ReapprovalRecord: What a re-approval publishes.
    ReapprovalVerdict: The decision, with the record or the reason it was refused.
    decide_reapproval: The pure decision.
    REAPPROVAL_RECOGNIZER: The triage recognizer name a re-approval records.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from mergecraft.classify.triage import recognize_prose_only

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

REAPPROVAL_RECOGNIZER: Final[str] = "reapproval"
APPROVAL_CHECK_NAME: Final[str] = "mergecraft-approval"
# Work a re-approval does not repeat. Stated on the check so a reused verdict is never
# read as a fresh review.
SKIPPED_WORK: Final[tuple[str, ...]] = (
    "LLM review",
    "specialist and verifier agents",
    "analyzers",
    "static checks",
    "full-diff reads",
)
REGULAR_FILE_MODES: Final[frozenset[str]] = frozenset({"100644", "100755"})

_SHA: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}")
_STAMP_PULL: Final[re.Pattern[str]] = re.compile(r"Pull request: #([1-9][0-9]*)")
_STAMP_BASE: Final[re.Pattern[str]] = re.compile(r"Target branch: (\S+)")
_STAMP_MERGE_BASE: Final[re.Pattern[str]] = re.compile(r"Reviewed merge base: ([0-9a-f]{40})")
_STAMP_POLICY: Final[re.Pattern[str]] = re.compile(r"Review policy: sha256:([0-9a-f]{64})")


@dataclass(frozen=True, slots=True)
class ReviewStamp:
    """The pull request, target branch and review policy a verdict was decided under.

    Written into the ``mergecraft-approval`` summary by the orchestrator, never by an
    agent, so a later run can prove the prior pass applies to it.
    """

    pull_number: int
    base_ref: str
    policy_digest: str
    merge_base: str | None = None

    def lines(self) -> list[str]:
        """The summary lines :func:`parse_review_stamp` reads back."""
        lines = [
            f"Pull request: #{self.pull_number}",
            f"Target branch: {self.base_ref}",
            f"Review policy: sha256:{self.policy_digest}",
        ]
        if self.merge_base is not None:
            lines.append(f"Reviewed merge base: {self.merge_base}")
        return lines


def _single(pattern: re.Pattern[str], lines: list[str]) -> str | None:
    """The one line ``pattern`` fully matches; ``None`` when absent or repeated."""
    matches = [found for line in lines if (found := pattern.fullmatch(line)) is not None]
    return matches[0].group(1) if len(matches) == 1 else None


def parse_review_stamp(summary: str) -> ReviewStamp | None:
    """Read a :class:`ReviewStamp` from a check-run summary.

    Each stamp line must appear exactly once as a whole line; a missing or repeated
    line is ambiguous evidence and yields ``None``.
    """
    lines = [line.strip() for line in summary.split("\n")]
    pull = _single(_STAMP_PULL, lines)
    base = _single(_STAMP_BASE, lines)
    policy = _single(_STAMP_POLICY, lines)
    if pull is None or base is None or policy is None:
        return None
    return ReviewStamp(
        pull_number=int(pull),
        base_ref=base,
        policy_digest=policy,
        merge_base=_single(_STAMP_MERGE_BASE, lines),
    )


@dataclass(frozen=True, slots=True)
class PriorPass:
    """The trusted ``mergecraft-approval`` check run that passed the reviewed head.

    Attributes:
        check_id: The check run's id.
        head_sha: The commit the check run was published on (the reviewed head ``P``).
        app_slug: The GitHub App that published it.
        url: Link to the prior review: the run's ``details_url``, else its ``html_url``.
        stamp: The review stamp read from its summary, or ``None``.
    """

    check_id: int
    head_sha: str
    app_slug: str
    url: str
    stamp: ReviewStamp | None


@dataclass(frozen=True, slots=True)
class ChangedFile:
    """One compare-API file entry.

    ``patch`` is ``None`` when GitHub sent none (binary, too large, or a mode-only
    change); ``changes`` is the entry's ``additions + deletions``.
    """

    path: str
    status: str
    blob_sha: str
    previous_path: str = ""
    patch: str | None = None
    changes: int = 0

    def names(self) -> tuple[str, ...]:
        """The paths this entry touches: the rename or copy source and the target."""
        return (self.previous_path, self.path) if self.previous_path else (self.path,)

    def same_change(self, other: ChangedFile) -> bool:
        """Whether ``other`` is the same change: status, source, post-image and patch."""
        return (
            self.path == other.path
            and self.status == other.status
            and self.previous_path == other.previous_path
            and self.blob_sha == other.blob_sha
            and self.patch == other.patch
        )


@dataclass(frozen=True, slots=True)
class Comparison:
    """One compare-API answer: the merge base it used and the files it listed."""

    merge_base: str
    files: tuple[ChangedFile, ...] = ()


@dataclass(frozen=True, slots=True)
class ReapprovalEvidence:
    """Everything :func:`decide_reapproval` reads; the I/O shell fills it in.

    Attributes:
        pull_number: The pull request this run is for.
        base_ref: Its current target branch.
        head_sha: Its current head ``H``.
        policy_digest: The review-policy digest of this run's base-side config.
        prior: The trusted prior pass on ``P``.
        reviewed: ``base...P``.
        current: ``base...H``.
        interdiff: ``P...H``.
        modes: File modes per revision (``P``, ``H``, and both merge bases) for the
            paths the decision asks about; ``None`` means the path is absent there.
        head_files: Head-side text of the qualifying paths at ``H``.
    """

    pull_number: int
    base_ref: str
    head_sha: str
    policy_digest: str
    prior: PriorPass
    reviewed: Comparison
    current: Comparison
    interdiff: Comparison
    modes: Mapping[str, Mapping[str, str | None]] = field(default_factory=dict)
    head_files: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReapprovalRecord:
    """What a re-approval publishes on the new head.

    Attributes:
        prior_url: Link to the prior review run.
        prior_check_id: The prior ``mergecraft-approval`` check run's id.
        prior_head_sha: The reviewed head ``P``.
        head_sha: The new head ``H`` the result is published on.
        prior_merge_base: The merge base the reviewed changes were compared from.
        merge_base: The merge base of the new head.
        qualifying_paths: Paths whose PR-authored change was proven prose.
        preserved_paths: PR-authored paths byte-identical to the reviewed version.
        inherited_paths: Paths that changed only because the base branch did.
        skipped: Work this run did not repeat.
    """

    prior_url: str
    prior_check_id: int
    prior_head_sha: str
    head_sha: str
    prior_merge_base: str
    merge_base: str
    qualifying_paths: tuple[str, ...]
    preserved_paths: tuple[str, ...]
    inherited_paths: tuple[str, ...]
    skipped: tuple[str, ...] = SKIPPED_WORK

    def reason(self) -> str:
        """One sentence for the run record and the triage reason."""
        paths = ", ".join(self.qualifying_paths)
        return (
            f"re-approved: the mergeCraft pass on {self.prior_head_sha[:12]} carries over; "
            f"the only PR-authored change since then is prose in {paths}"
        )

    def summary_lines(self) -> list[str]:
        """The lines the ``mergecraft`` and ``mergecraft-approval`` checks state."""
        return [
            "Tier: skip (reapproval) — no LLM review ran; the prior mergeCraft pass carries over",
            f"Prior review: {self.prior_url} (mergecraft-approval on {self.prior_head_sha})",
            f"Compared: {self.prior_head_sha}..{self.head_sha}",
            f"Merge base: {self.prior_merge_base} -> {self.merge_base}",
            "Qualifying path: " + ", ".join(self.qualifying_paths) + " (prose only)",
            (
                f"Accounted for: {len(self.qualifying_paths)} qualifying, "
                f"{len(self.preserved_paths)} reviewed and unchanged, "
                f"{len(self.inherited_paths)} inherited from the base branch"
            ),
            (
                "Run on this head: re-approval proof (prior pass, review stamp, "
                "path accounting, file modes, prose proof)"
            ),
            "Reused from the prior review: the mergecraft-approval verdict",
            "Skipped: " + ", ".join(self.skipped),
            "Other required checks are not reused; they must pass on this head.",
        ]


@dataclass(frozen=True, slots=True)
class ReapprovalVerdict:
    """The re-approval decision: a record to publish, or the reason it was refused."""

    record: ReapprovalRecord | None
    reason: str

    @property
    def eligible(self) -> bool:
        """Whether the prior pass carries over to the new head."""
        return self.record is not None


def _refuse(reason: str) -> ReapprovalVerdict:
    return ReapprovalVerdict(record=None, reason=reason)


class _RefusedError(Exception):
    """Raised inside the decision for a refusal; :func:`decide_reapproval` returns it."""


def _index(comparison: Comparison, label: str, *, need_patches: bool) -> dict[str, ChangedFile]:
    """Index a comparison's files by path; an ambiguous listing is a refusal.

    ``need_patches`` refuses an entry with line changes but no patch: the pull
    request's own changes are compared by patch. Paths that changed since the review
    are only accounted for by name, so their patches are not needed.
    """
    indexed: dict[str, ChangedFile] = {}
    for entry in comparison.files:
        if not entry.path or entry.path in indexed:
            msg = f"the {label} file listing names {entry.path or 'an empty path'} ambiguously"
            raise _RefusedError(msg)
        if need_patches and entry.patch is None and entry.changes > 0:
            msg = f"GitHub sent no patch for {entry.path} in the {label} comparison"
            raise _RefusedError(msg)
        indexed[entry.path] = entry
    return indexed


def _section(entry: ChangedFile) -> str:
    """The ``diff --git`` section for one entry, the way the triage parser reads it."""
    return f"diff --git a/{entry.path} b/{entry.path}\n{entry.patch or ''}\n"


def _stamp_problem(evidence: ReapprovalEvidence) -> str | None:
    stamp = evidence.prior.stamp
    if stamp is None:
        return "the prior pass carries no review stamp (pull request, target branch, policy)"
    if stamp.pull_number != evidence.pull_number:
        return f"the prior pass was for pull request #{stamp.pull_number}"
    if stamp.base_ref != evidence.base_ref:
        return f"the target branch changed from {stamp.base_ref} to {evidence.base_ref}"
    if stamp.policy_digest != evidence.policy_digest:
        return "the review policy changed since the prior pass"
    return None


def _identity_problem(evidence: ReapprovalEvidence) -> str | None:
    prior = evidence.prior.head_sha
    shas = (
        prior,
        evidence.head_sha,
        evidence.reviewed.merge_base,
        evidence.current.merge_base,
        evidence.interdiff.merge_base,
    )
    if not all(_SHA.fullmatch(sha) for sha in shas):
        return "a compared revision is not a full commit SHA"
    if prior == evidence.head_sha:
        return "the head is the reviewed head; there is nothing to carry over"
    if evidence.interdiff.merge_base != prior:
        return f"the new head does not descend from the reviewed head {prior[:12]}"
    return _stamp_problem(evidence)


def _mode_problem(
    evidence: ReapprovalEvidence,
    paths: Collection[str],
    pairs: tuple[tuple[str, str], ...],
) -> str | None:
    """Compare each path's mode on both revisions of every pair."""
    for path in sorted(paths):
        for left, right in pairs:
            left_modes, right_modes = evidence.modes.get(left), evidence.modes.get(right)
            if left_modes is None or right_modes is None:
                return f"no file-mode evidence for {left[:12]} or {right[:12]}"
            if path not in left_modes or path not in right_modes:
                return f"no file-mode evidence for {path}"
            if left_modes[path] != right_modes[path]:
                return f"the file mode of {path} differs between {left[:12]} and {right[:12]}"
            if left_modes[path] is not None and left_modes[path] not in REGULAR_FILE_MODES:
                return f"{path} is not a regular file"
    return None


def required_mode_paths(
    reviewed: Comparison, current: Comparison, qualifying: Collection[str]
) -> dict[str, tuple[str, ...]]:
    """The paths whose modes the decision compares, grouped by revision role.

    ``preserved`` (every non-qualifying path of ``current``) is compared at ``P`` / ``H``
    and at both merge bases; ``qualifying`` at ``H`` and its merge base. The I/O shell
    reads exactly these.
    """
    allowed = set(qualifying)
    preserved = sorted(
        {name for entry in current.files if entry.path not in allowed for name in entry.names()}
        | {name for entry in reviewed.files if entry.path not in allowed for name in entry.names()}
    )
    touched = sorted({entry.path for entry in current.files if entry.path in allowed})
    return {"preserved": tuple(preserved), "qualifying": tuple(touched)}


def _pull_request_changes(
    reviewed: dict[str, ChangedFile], current: dict[str, ChangedFile], allowed: set[str]
) -> tuple[list[str], list[ChangedFile]]:
    """Match the PR's own changes to the reviewed ones; return preserved paths and prose.

    Every non-qualifying change at the new head must be the reviewed change exactly; a
    qualifying path's change must be an in-place edit.
    """
    preserved: list[str] = []
    prose: list[ChangedFile] = []
    for path, entry in sorted(current.items()):
        if allowed.intersection(entry.names()):
            if entry.path not in allowed or entry.previous_path or entry.status != "modified":
                raise _RefusedError(f"{path} is not an in-place edit of a qualifying path")
            if entry.patch is None:
                raise _RefusedError(f"GitHub sent no patch for {path}")
            prose.append(entry)
            continue
        before = reviewed.get(path)
        if before is None:
            raise _RefusedError(f"{path} is a PR-authored change made since the review")
        if not entry.same_change(before):
            raise _RefusedError(f"the PR-authored change to {path} differs from the reviewed one")
        if entry.patch is None and entry.status != "added":
            # Without a patch the pre-image is unproven: the base side of a binary or
            # mode-only change may have moved under it.
            raise _RefusedError(f"the base side of {path} cannot be proven unchanged")
        preserved.append(path)
    for path, entry in sorted(reviewed.items()):
        if path not in allowed and path not in current:
            raise _RefusedError(f"the reviewed change to {path} is no longer in the pull request")
        if path in allowed and (entry.previous_path or entry.status != "modified"):
            raise _RefusedError(f"the reviewed change to {path} was not an in-place edit")
    return preserved, prose


def _since_review(
    interdiff: dict[str, ChangedFile],
    pr_names: set[str],
    allowed: set[str],
    authored: set[str],
) -> tuple[set[str], set[str]]:
    """Account for every path changed since the review: qualifying, or inherited.

    A path is qualifying only when the pull request authors a change to it at the new
    head (``authored``, every one of which is prose-proven). A qualifying-named path
    the PR does not change at the new head holds the base's version there, so it is
    inherited, never reported as a PR-authored prose edit.
    """
    qualifying: set[str] = set()
    inherited: set[str] = set()
    for path, entry in sorted(interdiff.items()):
        names = entry.names()
        if authored.intersection(names):
            if entry.path not in allowed or entry.previous_path or entry.status != "modified":
                msg = f"{path} changed since the review other than by an in-place edit"
                raise _RefusedError(msg)
            qualifying.add(path)
            continue
        touched = pr_names.difference(allowed).intersection(names)
        if touched:
            msg = f"the PR-authored path {sorted(touched)[0]} changed since the review"
            raise _RefusedError(msg)
        inherited.update(names)
    if not qualifying:
        raise _RefusedError("no PR-authored change to a qualifying path since the review")
    return qualifying, inherited


def _check_modes(evidence: ReapprovalEvidence, allowed: set[str]) -> None:
    """File modes, which the compare API omits, match on both sides of both comparisons."""
    prior, head = evidence.prior.head_sha, evidence.head_sha
    old_base, new_base = evidence.reviewed.merge_base, evidence.current.merge_base
    wanted = required_mode_paths(evidence.reviewed, evidence.current, allowed)
    problem = _mode_problem(
        evidence, wanted["preserved"], ((prior, head), (old_base, new_base))
    ) or _mode_problem(evidence, wanted["qualifying"], ((new_base, head),))
    if problem is not None:
        raise _RefusedError(problem)
    for path in wanted["qualifying"]:
        if evidence.modes.get(head, {}).get(path) != "100644":
            raise _RefusedError(f"{path} is not a regular non-executable file at the new head")


def _decide(evidence: ReapprovalEvidence, allowed: set[str]) -> ReapprovalRecord:
    problem = _identity_problem(evidence)
    if problem is not None:
        raise _RefusedError(problem)
    if not allowed:
        raise _RefusedError("review.fastPath.reapproval.paths names no path")
    reviewed = _index(evidence.reviewed, "reviewed", need_patches=True)
    current = _index(evidence.current, "current", need_patches=True)
    interdiff = _index(evidence.interdiff, "since-review", need_patches=False)
    preserved, prose = _pull_request_changes(reviewed, current, allowed)
    pr_names = {name for entry in (*current.values(), *reviewed.values()) for name in entry.names()}
    qualifying, inherited = _since_review(
        interdiff, pr_names, allowed, {entry.path for entry in prose}
    )
    # Every qualifying path is a PR-authored change at the new head, so ``prose`` is
    # never empty here and the proof always runs for what the record calls prose.
    diff_text = "".join(_section(entry) for entry in prose)
    if not recognize_prose_only(diff_text, head_files=evidence.head_files):
        changed = ", ".join(entry.path for entry in prose)
        raise _RefusedError(f"the change to {changed} is not proven prose")
    _check_modes(evidence, allowed)
    return ReapprovalRecord(
        prior_url=evidence.prior.url,
        prior_check_id=evidence.prior.check_id,
        prior_head_sha=evidence.prior.head_sha,
        head_sha=evidence.head_sha,
        prior_merge_base=evidence.reviewed.merge_base,
        merge_base=evidence.current.merge_base,
        qualifying_paths=tuple(sorted(qualifying)),
        preserved_paths=tuple(preserved),
        inherited_paths=tuple(sorted(inherited)),
    )


def decide_reapproval(
    evidence: ReapprovalEvidence, *, qualifying_paths: Collection[str]
) -> ReapprovalVerdict:
    """Decide whether the prior pass carries over to the new head.

    Pure: no I/O. Any missing, inconsistent or ambiguous evidence is a refusal, and a
    refusal means the normal review runs. The steps, each a refusal on failure:

    1. identity — full SHAs, a new head that descends from the reviewed one, and a
       review stamp naming this pull request, target branch and review policy;
    2. the PR's own changes — every non-qualifying change identical to the reviewed
       one, every qualifying change an in-place edit;
    3. accounting — every path changed since the review is qualifying (a change the
       PR authors at the new head) or inherited from the base, and at least one is
       qualifying;
    4. prose — the qualifying change at the new head is proven prose;
    5. modes — unchanged on both sides of both comparisons.
    """
    try:
        record = _decide(evidence, {path for path in qualifying_paths if path})
    except _RefusedError as refusal:
        return _refuse(str(refusal))
    return ReapprovalVerdict(record=record, reason=record.reason())


__all__ = [
    "APPROVAL_CHECK_NAME",
    "REAPPROVAL_RECOGNIZER",
    "REGULAR_FILE_MODES",
    "SKIPPED_WORK",
    "ChangedFile",
    "Comparison",
    "PriorPass",
    "ReapprovalEvidence",
    "ReapprovalRecord",
    "ReapprovalVerdict",
    "ReviewStamp",
    "decide_reapproval",
    "parse_review_stamp",
    "required_mode_paths",
]
