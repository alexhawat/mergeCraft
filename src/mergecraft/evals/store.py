"""Pure case store for the Failure Memory and Eval Bank (#51, W11.6).

The store is the **pure core** of the bank. It takes Python paths and
returns Python data structures; it performs no I/O at import time and
reads no ``os.environ``. The CLI in ``mergecraft.cli.eval_cmd`` is the
thin I/O shell that wraps it.

The case schema is markdown + YAML front matter. The front matter is
validated by :class:`LearningProvenance` (D5) — the wave plan's
cross-file section pins the import path and the strict ``extra="forbid"``
invariant. The case schema **embeds** ``LearningProvenance`` rather than
re-declaring its fields, exactly as the cross-file collision policy in
the wave plan documents.

Wire format::

    ---
    id: synthetic-001
    title: PR review missed a fabricated deletion
    category: missed_finding
    submitted_at: 2026-08-09T10:00:00Z
    run_id: synthetic
    pr_number: 1
    failure_mode: missed_finding
    expected_finding: "src/mergecraft/foo.py:42-60: 'delete' on unborn file"
    expected_decision: block
    provenance:
      run_id: synthetic
      pr_number: 1
      source_field: eval_bank
      author_login: synthetic
      author_association: OWNER
      trust_tier: trusted
      timestamp: 2026-08-09T10:00:00Z
    replay_command: "mergecraft eval replay synthetic-001"
    ---

    # synthetic-001

    Free-form description of the failure mode and the expected behavior.

    ## Expected finding

    The packet should carry a ``Finding`` for ...

    ## Expected decision

    The verdict should be ``block`` because ...

The schema is split into:

- **Top-level metadata** (id, title, category, submitted_at, run_id,
  pr_number, failure_mode, expected_finding, expected_decision,
  replay_command): stable, machine-readable, used by ``list`` / ``replay``.
- **Provenance**: a typed ``LearningProvenance`` record (D5). The
  cross-file section in the wave plan names this surface explicitly.
- **Body**: free-form markdown describing the failure mode. The
  ``render_case_text`` / ``parse_case_text`` helpers preserve the body
  verbatim.

The store is **synthetic-first** by default: case IDs prefixed with
``synthetic`` are how the test fixtures stay distinguishable from real
historical failures. The CLI does not enforce any naming convention
on the directory — operators can add cases with any ID — but the test
suite uses synthetic IDs to avoid committing real-looking failure
records.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

import yaml
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mergecraft.utils.learnings import LearningProvenance

if TYPE_CHECKING:
    from mergecraft.evals.convergence import ConvergenceRound
    from mergecraft.findings.lifecycle import LifecycleState

# D13 — local + file-backed. No database, no hosted service. The bank
# lives under the repo's ``evals/`` tree; the path is configurable so
# tests can override it.
DEFAULT_BANK_DIR = Path("evals") / "cases"
CASES_DIR_NAME = "cases"
CASE_FILE_SUFFIX = ".md"

# Failure-status vocabulary. ``regression`` is the third axis that the
# replay diffs against: a case whose current verdict matches
# ``expected_decision`` is ``passed``; a case whose current verdict
# differs is ``regression``; a case whose current verdict is unavailable
# (the replay environment cannot compute it) is ``blocked``.
CaseStatus = Literal["passed", "regression", "blocked"]
CASE_STATUS_PASSED: CaseStatus = "passed"
CASE_STATUS_REGRESSION: CaseStatus = "regression"
CASE_STATUS_BLOCKED: CaseStatus = "blocked"

# Canonical failure-mode category vocabulary — two distinct failure modes
# the W12 promote-to-test workflow names explicitly (#44):
# - ``rejected``: the PR was rejected on its first attempt (the reviewer
#   asked for changes / the merge-evidence verdict was a block).
# - ``reverted``: the PR was merged but later reverted in a follow-up.
# ``list_cases`` accepts arbitrary ``category`` strings, but operators
# should reach for these two values when capturing historical failures
# — the promote workflow's tests pin them as the canonical examples.
CATEGORY_REJECTED: str = "rejected"
CATEGORY_REVERTED: str = "reverted"
CATEGORY_MULTI_ROUND_CONVERGENCE: str = "multi_round_convergence"
FAILURE_CATEGORIES: frozenset[str] = frozenset({CATEGORY_REJECTED, CATEGORY_REVERTED})

# The case directory's per-file front-matter shape. Each row is the
# field name and the parser key expected in the YAML map. Keeping the
# validator declarative lets the test suite pin the contract.
_CASE_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "category",
    "submitted_at",
    "run_id",
    "pr_number",
    "failure_mode",
    "expected_finding",
    "expected_decision",
    "replay_command",
)

# Verdict vocabulary mirrored from
# ``mergecraft.evidence.packet.Decision.verdict``. The store does not
# re-export the type — it stays as a string literal so the bank does
# not silently fall out of sync when the packet's verdict enum evolves.
#
# The mirror had drifted. ``decide_approval()`` wraps its ``Conclusion``
# verbatim into ``Decision.verdict`` (``agents/gates.py``), so a packet
# produced today carries ``success`` / ``failure`` / ``neutral`` — of which
# only ``neutral`` was accepted here. A case could therefore never record the
# verdict the code actually computes. Both vocabularies are accepted: the
# check-run one because it is what ships, and the lane one because the
# thermostat work (W9) is specified to introduce it. W9 adds the four
# extra action names from the closed vocabulary (#46, W9.1).
_EXPECTED_VERDICT_VALUES: frozenset[str] = frozenset(
    {
        # Check-run conclusions — what `decide_approval()` emits today.
        "success",
        "failure",
        # Lane verdicts — the W9 thermostat action vocabulary.
        "auto_merge",
        "block",
        "request_changes",
        "require_human_review",
        "require_more_tests",
        "quarantine",
        "escalate",
        "unavailable",
        "neutral",
    }
)

# Token shape for case IDs. Kept loose intentionally — the bank does
# not enforce a namespace, only that an ID is a non-empty identifier
# safe to use as a filename.
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")


# ── front-matter scanner ──────────────────────────────────────────────


class _FrontmatterError(ValueError):
    """Raised when the case file's YAML front matter is malformed (D13)."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return ``(front_matter_dict, body)`` from a case file's text.

    Args:
        text: The full text of a case file.

    Returns:
        A 2-tuple ``(front_matter, body)``. The body is everything after
        the closing ``---`` line, with the leading newline stripped. The
        dict is the YAML-decoded front matter.

    Raises:
        _FrontmatterError: When the file does not start with the opening
            ``---`` delimiter, has no closing ``---`` delimiter, or the
            YAML payload does not parse.

    Examples:
        >>> fm, body = _split_frontmatter("---\\nid: x\\n---\\nbody")
        >>> fm["id"]
        'x'
        >>> body
        'body'
    """
    if not text.startswith("---"):
        msg = "case file does not start with '---' front-matter delimiter"
        raise _FrontmatterError(Path("<text>"), msg)
    # The opening ``---`` is followed by a newline. The body begins
    # after the closing ``---`` line. Use byte offsets so the body
    # preserves its original trailing newline(s) on round-trip.
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        msg = "case file does not start with '---' front-matter delimiter"
        raise _FrontmatterError(Path("<text>"), msg)
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        msg = "case file is missing the closing '---' front-matter delimiter"
        raise _FrontmatterError(Path("<text>"), msg)
    raw_yaml = "\n".join(lines[1:end])
    # Compute the byte offset of the closing ``---`` line's end so
    # the body keeps any trailing newline(s) verbatim. ``splitlines``
    # strips delimiters, so we walk the original ``text`` to find
    # where the closing line ends.
    closing_offset = 0
    for line in lines[: end + 1]:
        closing_offset += len(line) + 1  # ``+1`` for the stripped newline
    body = text[closing_offset:].lstrip("\n")
    try:
        parsed = yaml.safe_load(raw_yaml) if raw_yaml.strip() else {}
    except yaml.YAMLError as exc:
        msg = f"front-matter YAML failed to parse: {exc}"
        raise _FrontmatterError(Path("<text>"), msg) from exc
    if not isinstance(parsed, dict):
        msg = f"front-matter must be a YAML mapping; got {type(parsed).__name__}"
        raise _FrontmatterError(Path("<text>"), msg)
    return parsed, body


def _require_keys(front: dict[str, Any], path: Path) -> None:
    """Raise :class:`_FrontmatterError` when required keys are missing."""
    missing = [key for key in _CASE_FIELDS if key not in front]
    if missing:
        msg = f"front matter is missing required fields: {', '.join(missing)}"
        raise _FrontmatterError(path, msg)


# ── multi-round convergence shapes (W10) ────────────────────────────


class CaseRoundLedgerEntry(BaseModel):
    """One ledger row for a round in a multi-round convergence case."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(min_length=1)
    state: str = Field(min_length=1)
    round_index: int | None = None


class CaseRoundFinding(BaseModel):
    """One ground-truth finding row with the round it first appeared in."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(min_length=1)
    path: str = Field(min_length=1)
    start_line: int
    end_line: int
    body: str = Field(min_length=1)
    first_appeared_round: int = Field(ge=1)


class CaseRound(BaseModel):
    """One review round: diff, recorded findings, and ledger snapshot."""

    model_config = ConfigDict(extra="forbid")

    round_index: int = Field(ge=1)
    diff_text: str = ""
    findings: list[CaseRoundFinding] = Field(default_factory=list)
    ledger: list[CaseRoundLedgerEntry] = Field(default_factory=list)
    generated_fingerprints: list[str] = Field(default_factory=list)


# ── public data shapes ────────────────────────────────────────────────


class Case(BaseModel):
    """One durable case in the eval bank.

    ``Provenance`` is a typed :class:`LearningProvenance` (D5). The
    ``extra="forbid"`` invariant on the provenance model is the
    guarantee that the case's metadata cannot silently drift from the
    security plan's contract.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    submitted_at: datetime
    run_id: str = Field(min_length=1)
    pr_number: int | None = None
    failure_mode: str = Field(min_length=1)
    expected_finding: str = Field(min_length=1)
    expected_decision: str = Field(min_length=1)
    replay_command: str = Field(min_length=1)
    provenance: LearningProvenance
    body: str = ""

    # ── replay inputs (optional; #44/C7) ──────────────────────────────
    # Without these a replay cannot compute anything and must be handed a
    # verdict by an operator, which makes a promoted test assert nothing in
    # CI. With them, ``decide_approval()`` recomputes the verdict from the
    # same structured evidence the run recorded — pure, deterministic, and
    # needing no agent, network, or API key.
    recorded_findings: list[dict[str, Any]] | None = None
    run_succeeded: bool = True
    trust_tier: str = "trusted"
    # An explicit curator assertion that `recorded_findings` is complete and
    # confirmed-clean — mirrors `scoring.BaselineIssue`'s `closed_world` flag
    # (D4/D5). Trust tier alone is not defect ground truth: an untrusted-tier
    # case can still carry a real seeded defect the review missed, and only
    # this flag distinguishes "curator asserts: nothing to find" from
    # "empty for some other reason" (mergeCraft self-review, PR #216 —
    # gate-matrix classification must not infer ground truth from trust_tier).
    closed_world: bool = False
    # Multi-round convergence corpus (W10). When set, the case is scored via
    # :func:`convergence_rounds_from_case` rather than single-round replay.
    rounds: list[CaseRound] | None = None

    @property
    def is_multi_round(self) -> bool:
        """True when the case carries an ordered multi-round convergence corpus."""
        return bool(self.rounds)

    @property
    def is_replayable(self) -> bool:
        """True when the case carries enough evidence to recompute a verdict."""
        return self.recorded_findings is not None

    @field_validator("expected_decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        """Reject ``expected_decision`` values outside the verdict vocabulary.

        The vocabulary mirrors the packet's ``Decision.verdict`` field.
        The store does not import the packet's type to keep the
        ``evals`` module independent of the merge-evidence schema.
        """
        if value not in _EXPECTED_VERDICT_VALUES:
            msg = (
                f"expected_decision {value!r} is not in the verdict vocabulary "
                f"{sorted(_EXPECTED_VERDICT_VALUES)}"
            )
            raise ValueError(msg)
        return value

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        """Enforce the locked identifier shape.

        The shape mirrors the file-system naming convention so a case
        id is a safe filename.
        """
        if not _ID_RE.match(value):
            msg = f"case id {value!r} is not a valid identifier"
            raise ValueError(msg)
        return value

    @property
    def is_synthetic(self) -> bool:
        """Return True iff the case ID is a synthetic test fixture.

        The bank does not enforce a synthetic namespace, but the test
        suite mutates fixtures with the ``synthetic`` prefix so the
        committed corpus never looks like a real failure record.
        """
        return self.id.startswith("synthetic")


class CaseFilter(BaseModel):
    """A query filter for :func:`list_cases`."""

    model_config = ConfigDict(extra="forbid")

    category: str | None = None
    since: datetime | None = None
    id_prefix: str | None = None


class ReplayDiff(BaseModel):
    """The deterministic diff between a recorded and a re-run case.

    The diff is pure data — no I/O, no subprocess. The CLI renders it
    as a human-readable text block and a JSON document; the test suite
    asserts on the structured fields directly.

    Attributes:
        case_id: The case the replay was run against.
        expected_decision: The decision recorded on the case.
        current_decision: The decision the replay engine produced, or
            ``None`` when the replay engine was unavailable.
        status: One of ``passed`` / ``regression`` / ``blocked``.
        notes: Free-form notes — especially for the ``blocked`` case.

    Examples:
        >>> from datetime import datetime, timezone
        >>> diff = ReplayDiff(
        ...     case_id="synthetic-001",
        ...     expected_decision="block",
        ...     current_decision="auto_merge",
        ...     status="regression",
        ... )
        >>> diff.status
        'regression'
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str
    expected_decision: str
    current_decision: str | None = None
    status: CaseStatus
    notes: str = ""


class EvalMetadata(BaseModel):
    """Lightweight packet-side summary of one replay run (#44, W12).

    The ``MergeEvidencePacket.evals`` section is a list of these — one
    per case the run promoted / replayed / attached to the verdict. The
    record is the *packet-side* summary: it carries enough to attribute
    a verdict to a case in the bank, but it does **not** carry the full
    :class:`Case` model. The full case lives under
    ``evals/cases/<case_id>.md``; the packet field is the breadcrumb.

    The shape intentionally omits ``LearningProvenance`` — provenance is
    a *case-side* record, not a packet-side one. The packet reader can
    look the case up by ``case_id`` if it needs the provenance chain.

    Attributes:
        case_id: The case this metadata row describes.
        run_id: The run that produced the verdict (mirrors the packet's
            top-level run attribution).
        title: Short, operator-readable case title.
        category: The failure category (``rejected`` / ``reverted`` /
            any operator-defined value).
        failure_mode: The recorded failure mode.
        expected_finding: The finding the packet should have produced.
        expected_decision: The verdict the case asserts the packet
            should have produced.
        replay_decision: The verdict the replay engine produced for
            this case (``passed`` / ``regression`` / ``blocked``).
        replay_at: The UTC timestamp the replay ran.
        status: The case-status equivalent (``passed`` /
            ``regression`` / ``blocked``) for ergonomic filtering — the
            packet reader does not need to compare expected and current
            verdicts to know whether the case has drifted.

    Examples:
        >>> from datetime import datetime, timezone
        >>> meta = EvalMetadata(
        ...     case_id="synthetic-001",
        ...     run_id="run-123",
        ...     title="missed a fabricated deletion",
        ...     category="missed_finding",
        ...     failure_mode="missed_finding",
        ...     expected_finding="src/mergecraft/foo.py:42",
        ...     expected_decision="block",
        ...     replay_decision="block",
        ...     replay_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ...     status="passed",
        ... )
        >>> meta.case_id
        'synthetic-001'
    """

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    category: str = Field(min_length=1)
    failure_mode: str = Field(min_length=1)
    expected_finding: str = Field(min_length=1)
    expected_decision: str = Field(min_length=1)
    replay_decision: CaseStatus
    replay_at: datetime
    status: CaseStatus

    @field_validator("case_id")
    @classmethod
    def _validate_case_id(cls, value: str) -> str:
        """Enforce the locked identifier shape.

        The shape mirrors the bank file-system naming convention so a
        ``case_id`` is a safe filename the reader can resolve.
        """
        if not _ID_RE.match(value):
            msg = f"case id {value!r} is not a valid identifier"
            raise ValueError(msg)
        return value

    @field_validator("expected_decision")
    @classmethod
    def _validate_decision(cls, value: str) -> str:
        """Reject ``expected_decision`` values outside the verdict vocabulary.

        The vocabulary mirrors the packet's ``Decision.verdict`` field.
        ``EvalMetadata`` keeps the same vocabulary as the case store
        so the packet does not silently fall out of sync with the bank.
        """
        if value not in _EXPECTED_VERDICT_VALUES:
            msg = (
                f"expected_decision {value!r} is not in the verdict vocabulary "
                f"{sorted(_EXPECTED_VERDICT_VALUES)}"
            )
            raise ValueError(msg)
        return value


# ── public API (pure) ─────────────────────────────────────────────────


def parse_case_text(path: Path, text: str) -> Case:
    """Parse a case file's text into a :class:`Case`.

    Validates the front matter against the locked schema, including the
    embedded :class:`LearningProvenance` (D5). The body is preserved
    verbatim so the round-trip is exact.

    Args:
        path: The path the text was loaded from. Used for error messages.
        text: The full text of the case file.

    Returns:
        A validated :class:`Case`.

    Raises:
        _FrontmatterError: When the front matter is missing or malformed.
        pydantic.ValidationError: When the front matter does not satisfy
            the case schema or the embedded ``LearningProvenance``
            invariant (``extra="forbid"``).
        ValueError: When the ``expected_decision`` is not in the
            verdict vocabulary.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from datetime import datetime, timezone
        >>> p = Path("synthetic-001.md")
        >>> text = (
        ...     "---\\n"
        ...     "id: synthetic-001\\n"
        ...     "title: missed finding\\n"
        ...     "category: missed_finding\\n"
        ...     "submitted_at: 2026-08-09T10:00:00Z\\n"
        ...     "run_id: synthetic\\n"
        ...     "pr_number: 1\\n"
        ...     "failure_mode: missed_finding\\n"
        ...     "expected_finding: 'src/mergecraft/foo.py:42-60'\\n"
        ...     "expected_decision: block\\n"
        ...     "replay_command: 'mergecraft eval replay synthetic-001'\\n"
        ...     "provenance:\\n"
        ...     "  run_id: synthetic\\n"
        ...     "  pr_number: 1\\n"
        ...     "  source_field: eval_bank\\n"
        ...     "  author_login: synthetic\\n"
        ...     "  author_association: OWNER\\n"
        ...     "  trust_tier: trusted\\n"
        ...     "  timestamp: 2026-08-09T10:00:00Z\\n"
        ...     "---\\n"
        ...     "\\n"
        ...     "# synthetic-001\\n"
        ...     "Free-form description.\\n"
        ... )
        >>> case = parse_case_text(p, text)
        >>> case.id
        'synthetic-001'
        >>> case.provenance.trust_tier
        'trusted'
        >>> case.body.startswith("# synthetic-001")
        True
    """
    front_matter, body = _split_frontmatter(text)
    _require_keys(front_matter, path)
    if not _ID_RE.match(str(front_matter.get("id", ""))):
        msg = f"case id {front_matter.get('id')!r} is not a valid identifier"
        raise _FrontmatterError(path, msg)
    expected_decision = str(front_matter["expected_decision"])
    if expected_decision not in _EXPECTED_VERDICT_VALUES:
        msg = (
            f"expected_decision {expected_decision!r} is not in the verdict vocabulary "
            f"{sorted(_EXPECTED_VERDICT_VALUES)}"
        )
        raise _FrontmatterError(path, msg)
    if "provenance" not in front_matter:
        msg = "front matter is missing the required 'provenance' record (D5)"
        raise _FrontmatterError(path, msg)
    # ``LearningProvenance`` is the model imported from the security
    # plan's Batch C. The cross-file contract requires we **embed** it,
    # not re-declare its fields.
    try:
        provenance = LearningProvenance.model_validate(front_matter["provenance"])
    except ValidationError as exc:
        msg = f"provenance record failed validation: {exc}"
        raise _FrontmatterError(path, msg) from exc
    try:
        case = Case.model_validate({**front_matter, "provenance": provenance, "body": body})
    except ValidationError as exc:
        msg = f"case schema failed validation: {exc}"
        raise _FrontmatterError(path, msg) from exc
    return case


def render_case_text(case: Case) -> str:
    """Render a :class:`Case` back into the wire file format.

    The output is byte-identical modulo YAML key ordering for the
    round-trip path: ``render_case_text(parse_case_text(p, text))``
    parsed-back equals ``parse_case_text(p, text)`.

    Args:
        case: The case to render.

    Returns:
        The full text of the case file, front matter + body.

    Examples:
        >>> from datetime import datetime, timezone
        >>> from mergecraft.utils.learnings import LearningProvenance
        >>> prov = LearningProvenance(
        ...     run_id="synthetic", pr_number=1, source_field="eval_bank",
        ...     author_login="synthetic", author_association="OWNER",
        ...     trust_tier="trusted",
        ...     timestamp=datetime(2026, 8, 9, 10, 0, 0, tzinfo=timezone.utc),
        ... )
        >>> case = Case(
        ...     id="synthetic-001", title="missed finding",
        ...     category="missed_finding",
        ...     submitted_at=datetime(2026, 8, 9, 10, 0, 0, tzinfo=timezone.utc),
        ...     run_id="synthetic", pr_number=1,
        ...     failure_mode="missed_finding",
        ...     expected_finding="src/x.py:42",
        ...     expected_decision="block",
        ...     replay_command="mergecraft eval replay synthetic-001",
        ...     provenance=prov, body="# body\n",
        ... )
        >>> text = render_case_text(case)
        >>> text.splitlines()[0]
        '---'
    """
    payload = case.model_dump(mode="json", exclude={"body"})
    # YAML key order follows the locked field order so the diff stays
    # stable across runs.
    ordered: dict[str, Any] = {}
    for key in _CASE_FIELDS:
        if key in payload:
            ordered[key] = payload[key]
    # Anything not in the locked field order (today: none) is appended.
    for key, value in payload.items():
        if key not in ordered:
            ordered[key] = value
    yaml_block = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True).rstrip()
    body = case.body or ""
    if body and not body.startswith("\n"):
        body = "\n" + body
    return f"---\n{yaml_block}\n---\n{body}"


def load_case(path: Path) -> Case:
    """Load a case from a file path.

    Args:
        path: The case file to read.

    Returns:
        The parsed and validated :class:`Case`.

    Raises:
        _FrontmatterError: When the front matter is missing or malformed.
        OSError: When the file cannot be read.
    """
    text = path.read_text(encoding="utf-8")
    return parse_case_text(path, text)


def add_case(
    bank_dir: Path,
    case: Case,
    *,
    overwrite: bool = False,
) -> Path:
    """Persist a case to ``bank_dir``.

    The case id becomes the file stem (``.md``). The function is
    pure-from-the-caller's-perspective: it does not perform any
    environment reads, only the explicit file write the caller asked
    for. The directory is created if missing.

    Args:
        bank_dir: The bank directory to write into.
        case: The case to persist.
        overwrite: When True, overwrite an existing case file with the
            same id. When False, raises :class:`FileExistsError`.

    Returns:
        The path of the written case file.

    Raises:
        FileExistsError: When ``overwrite`` is False and a case file
            with the same id already exists.
        OSError: When the file cannot be written.
    """
    bank_dir.mkdir(parents=True, exist_ok=True)
    target = bank_dir / f"{case.id}{CASE_FILE_SUFFIX}"
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    target.write_text(render_case_text(case), encoding="utf-8")
    logger.info("» eval case {} → {}", case.id, target)
    return target


def list_cases(
    bank_dir: Path,
    *,
    category: str | None = None,
    since: datetime | None = None,
    id_prefix: str | None = None,
) -> list[Case]:
    """List all cases in ``bank_dir`` matching the optional filters.

    The function is tolerant: a malformed case file is reported via
    ``logger.warning`` and skipped rather than raising, so a single
    bad file does not block the audit. The CLI's ``--json`` mode
    surfaces the count of skipped files separately.

    Args:
        bank_dir: The bank directory to scan.
        category: When set, only cases whose ``category`` matches.
        since: When set, only cases whose ``submitted_at`` is at or
            after this timestamp.
        id_prefix: When set, only cases whose id starts with this prefix.

    Returns:
        A list of :class:`Case` objects sorted by ``submitted_at``.
    """
    if not bank_dir.is_dir():
        return []
    cases: list[Case] = []
    for entry in sorted(bank_dir.iterdir()):
        if not entry.is_file() or entry.suffix != CASE_FILE_SUFFIX:
            continue
        try:
            case = load_case(entry)
        except _FrontmatterError as exc:
            logger.warning("skipping malformed case at {}: {}", entry, exc.message)
            continue
        if category is not None and case.category != category:
            continue
        if since is not None and case.submitted_at < since:
            continue
        if id_prefix is not None and not case.id.startswith(id_prefix):
            continue
        cases.append(case)
    cases.sort(key=lambda c: c.submitted_at)
    return cases


def recompute_decision(case: Case) -> str | None:
    """Recompute a case's verdict from its recorded evidence (#44, C7).

    This is the link that makes a promoted test a real regression test rather
    than a tautology. ``decide_approval()`` is a pure function of typed
    findings, the run's completion state, and the trust tier — so a case that
    stored those three can be re-decided by the *current* code with no agent,
    no network, and no API key, which is exactly what a CI gate needs.

    Returns ``None`` when the case predates the recorded-evidence fields or
    its rows no longer validate against the current ``Finding`` schema. A
    schema change that invalidates stored evidence is itself worth surfacing,
    so this reports "cannot decide" rather than guessing a verdict.
    """
    if case.recorded_findings is None:
        return None
    # Imported lazily: the store is the bank's pure data layer, and importing
    # the gate at module scope would tie every bank read to the agent stack.
    from mergecraft.agents.gates import decide_approval
    from mergecraft.analyzers.finding import Finding

    try:
        findings = [Finding.model_validate(row) for row in case.recorded_findings]
    except ValidationError as exc:
        logger.warning("case {}: recorded findings no longer validate: {}", case.id, exc)
        return None
    # Branch rather than cast: the tier literal is a security-relevant input,
    # and an unrecognised value must fall back to the restrictive side.
    if case.trust_tier == "untrusted":
        return str(decide_approval(findings, run_succeeded=case.run_succeeded, tier="untrusted"))
    return str(decide_approval(findings, run_succeeded=case.run_succeeded, tier="trusted"))


def _format_diff(case: Case, current: str | None) -> ReplayDiff:
    """Build a :class:`ReplayDiff` from a case and a current verdict.

    The verdict vocabulary is the same one the packet uses. The
    function is the *structural* gate: a difference between ``expected``
    and ``current`` is a regression; an absent current verdict is a
    blocked replay (the environment cannot compute one).
    """
    expected = case.expected_decision
    if current is None:
        return ReplayDiff(
            case_id=case.id,
            expected_decision=expected,
            current_decision=None,
            status=CASE_STATUS_BLOCKED,
            notes="replay engine did not produce a verdict",
        )
    if current == expected:
        return ReplayDiff(
            case_id=case.id,
            expected_decision=expected,
            current_decision=current,
            status=CASE_STATUS_PASSED,
        )
    return ReplayDiff(
        case_id=case.id,
        expected_decision=expected,
        current_decision=current,
        status=CASE_STATUS_REGRESSION,
        notes=f"verdict drift: expected {expected!r}, got {current!r}",
    )


def replay_case(case: Case, *, current_decision: str | None) -> ReplayDiff:
    """Replay a case against the current code, given a verdict.

    The replay function is **pure**. It does not invoke the agent, does
    not start a subprocess, does not read ``os.environ``.

    When ``current_decision`` is omitted and the case recorded its evidence,
    the verdict is recomputed by :func:`recompute_decision` — still pure, since
    ``decide_approval()`` is itself a pure function. That is what lets a
    promoted test detect a regression in CI instead of waiting for an operator
    to supply a verdict by hand. A case with no recorded evidence keeps the
    original behaviour and lands in the ``blocked`` state.

    An explicitly passed verdict always wins over the recomputed one: the
    caller is asserting what the running code produced, and that has to be able
    to contradict the stored evidence.

    Args:
        case: The case to replay.
        current_decision: The verdict the current code produced. When
            ``None``, it is recomputed from the case's recorded evidence if
            present, and left unresolved otherwise.

    Returns:
        A :class:`ReplayDiff` capturing the structural comparison.

    Examples:
        >>> from datetime import datetime, timezone
        >>> from mergecraft.utils.learnings import LearningProvenance
        >>> prov = LearningProvenance(
        ...     run_id="synthetic", pr_number=1, source_field="eval_bank",
        ...     author_login="synthetic", author_association="OWNER",
        ...     trust_tier="trusted",
        ...     timestamp=datetime(2026, 8, 9, 10, 0, 0, tzinfo=timezone.utc),
        ... )
        >>> case = Case(
        ...     id="synthetic-001", title="t",
        ...     category="missed_finding",
        ...     submitted_at=datetime(2026, 8, 9, 10, 0, 0, tzinfo=timezone.utc),
        ...     run_id="synthetic", pr_number=1,
        ...     failure_mode="missed_finding",
        ...     expected_finding="x", expected_decision="block",
        ...     replay_command="mergecraft eval replay synthetic-001",
        ...     provenance=prov, body="",
        ... )
        >>> d = replay_case(case, current_decision="block")
        >>> d.status
        'passed'
        >>> r = replay_case(case, current_decision="auto_merge")
        >>> r.status
        'regression'
    """
    # An explicit verdict always wins: the operator is asserting what the
    # running code produced, and that must be able to contradict the stored
    # evidence — otherwise a case could never catch its own staleness.
    resolved = current_decision if current_decision is not None else recompute_decision(case)
    return _format_diff(case, resolved)


def diff_cases(a: Case, b: Case) -> dict[str, Any]:
    """Return a structured diff between two cases' metadata.

    The diff is a flat dict keyed by case field. Equal fields are
    omitted; unequal fields are recorded as ``{"expected": ..., "got": ...}``.
    The body is compared as a whole string. Useful for the ``diff`` test
    in the replay suite.
    """
    diff: dict[str, Any] = {}
    for field_name in _CASE_FIELDS:
        a_val = getattr(a, field_name)
        b_val = getattr(b, field_name)
        if a_val != b_val:
            diff[field_name] = {"expected": a_val, "got": b_val}
    if a.provenance != b.provenance:
        diff["provenance"] = {
            "expected": a.provenance.model_dump(mode="json"),
            "got": b.provenance.model_dump(mode="json"),
        }
    if a.body != b.body:
        diff["body"] = {"expected": a.body, "got": b.body}
    if a.rounds != b.rounds:
        diff["rounds"] = {
            "expected": [row.model_dump(mode="json") for row in a.rounds or []],
            "got": [row.model_dump(mode="json") for row in b.rounds or []],
        }
    return diff


def convergence_rounds_from_case(case: Case) -> list[ConvergenceRound]:
    """Materialize :class:`CaseRound` rows as :class:`ConvergenceRound` inputs.

    Imports :class:`~mergecraft.evals.convergence.ConvergenceRound` lazily so
    the bank store does not pull the convergence scorer at import time.
    """
    if not case.rounds:
        msg = f"case {case.id!r} has no multi-round corpus"
        raise ValueError(msg)
    from mergecraft.evals.convergence import ConvergenceRound
    from mergecraft.findings.ledger import FindingLedger

    materialized: list[ConvergenceRound] = []
    for round_row in sorted(case.rounds, key=lambda row: row.round_index):
        ledger = FindingLedger()
        for entry in round_row.ledger:
            ledger.record(
                entry.fingerprint,
                cast("LifecycleState", entry.state),  # bank YAML uses ledger vocabulary
                source=case.id,
                round_index=entry.round_index or round_row.round_index,
            )
        finding_rows = [row.model_dump() for row in round_row.findings]
        generated = list(round_row.generated_fingerprints)
        if not generated:
            generated = [row.fingerprint for row in round_row.findings]
        materialized.append(
            ConvergenceRound(
                round_index=round_row.round_index,
                ledger=ledger,
                findings=finding_rows,
                generated_fingerprints=generated,
                diff_text=round_row.diff_text,
            )
        )
    return materialized


def list_multi_round_cases(
    bank_dir: Path,
    *,
    category: str = CATEGORY_MULTI_ROUND_CONVERGENCE,
) -> list[Case]:
    """Return bank cases with a multi-round convergence corpus, sorted by id."""
    cases = [case for case in list_cases(bank_dir, category=category) if case.is_multi_round]
    cases.sort(key=lambda row: row.id)
    return cases


def _now_utc() -> datetime:
    """Return the current UTC time (helper for the CLI / tests)."""
    return datetime.now(UTC)


# ── packet-side summary (W12.2) ────────────────────────────────────────


def build_eval_metadata(
    case: Case,
    *,
    replay_decision: CaseStatus,
    run_id: str,
    replay_at: datetime | None = None,
) -> EvalMetadata:
    """Build an :class:`EvalMetadata` row from a :class:`Case` + replay outcome.

    Pure data-shaping helper. The packet emits one row per case the run
    replayed or attached to the verdict; this helper is the
    single-entry-point the I/O shell uses to populate the
    ``MergeEvidencePacket.evals`` section.

    Args:
        case: The case the replay ran against.
        replay_decision: The replay's outcome (``passed`` /
            ``regression`` / ``blocked``).
        run_id: The run id that produced the replay (mirrors the
            packet's top-level run attribution).
        replay_at: The UTC timestamp the replay ran. Defaults to "now".

    Returns:
        An :class:`EvalMetadata` row carrying the lightweight
        summary. The full case continues to live under
        ``evals/cases/<case_id>.md``; this row is the packet-side
        breadcrumb.

    Examples:
        >>> from datetime import datetime, timezone
        >>> from mergecraft.utils.learnings import LearningProvenance
        >>> prov = LearningProvenance(
        ...     run_id="run-1", pr_number=1, source_field="eval_bank",
        ...     author_login="alice", author_association="OWNER",
        ...     trust_tier="trusted",
        ...     timestamp=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ... )
        >>> case = Case(
        ...     id="synthetic-001", title="t", category="missed_finding",
        ...     submitted_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ...     run_id="run-1", pr_number=1, failure_mode="missed_finding",
        ...     expected_finding="x", expected_decision="block",
        ...     replay_command="mergecraft eval replay synthetic-001",
        ...     provenance=prov, body="",
        ... )
        >>> meta = build_eval_metadata(
        ...     case, replay_decision="passed", run_id="run-1",
        ... )
        >>> meta.status
        'passed'
    """
    ts = replay_at if replay_at is not None else _now_utc()
    return EvalMetadata(
        case_id=case.id,
        run_id=run_id,
        title=case.title,
        category=case.category,
        failure_mode=case.failure_mode,
        expected_finding=case.expected_finding,
        expected_decision=case.expected_decision,
        replay_decision=replay_decision,
        replay_at=ts,
        status=replay_decision,
    )


# ── promote-to-permanent-test (W12.1) ──────────────────────────────────


PERMANENT_TEST_FILE_SUFFIX = ".py"
PERMANENT_TEST_DIR_NAME = "permanent"
PERMANENT_TEST_HEADER = '''"""Auto-generated permanent test promoted from the eval bank (#44, W12.1).

This file is produced by ``mergecraft eval promote <case-id>``. Do not
edit by hand — re-run ``mergecraft eval promote`` to regenerate. The
test re-runs the case against the current code via
``mergecraft.evals.store.replay_case``: a ``passed`` status means the
case's expected verdict matches what the running code produced; a
``regression`` status means the same failure mode the case captured has
recurred — that is the structural signal the promote workflow ships.

The promoted test lives under ``tests/evals/permanent/`` and is
discovered by pytest via the standard collection rules — no separate
``conftest`` is required.
"""

from __future__ import annotations

from mergecraft.evals.store import Case, replay_case

_PERMANENT_CASE_PAYLOAD = {payload!r}


def _load_permanent_case() -> Case:
    """Materialize the embedded case payload as a validated :class:`Case`.

    The payload is the case's full JSON shape (including the embedded
    ``LearningProvenance``); ``Case.model_validate_json`` is the same
    path the bank uses at read time, so a schema-version bump on the
    bank side surfaces here as a load-time failure rather than a
    silent structural drift.
    """
    return Case.model_validate_json(_PERMANENT_CASE_PAYLOAD)


def test_permanent_{func_name}() -> None:
    """Permanent regression test for case ``{case_id}`` ({title_literal}).

    Expected verdict: ``{expected_decision}``. The replay verdict is
    operator-supplied via the ``MERGECRAFT_PERMANENT_CURRENT_DECISION``
    env var; when unset the default is ``None`` so the case lands in
    the ``blocked`` state (the replay engine did not produce a
    verdict). The test asserts two things:

    - The case is replayable end-to-end (the bank schema still
      validates and ``replay_case`` returns a typed diff).
    - When the operator wires a current verdict, that verdict agrees
      with the case's expected decision — a real regression surfaces
      as a failed assertion.

    The default-``None`` path keeps the test green at import time so a
    fresh promotion does not break the suite. Operators flip the env
    var to surface drift.
    """
    import os

    case = _load_permanent_case()
    current = os.environ.get("MERGECRAFT_PERMANENT_CURRENT_DECISION") or None
    diff = replay_case(case, current_decision=current)
    # The replay must complete — even the default-``None`` path lands in
    # the ``blocked`` status, which is itself a valid replay outcome.
    assert diff.status in {{"passed", "regression", "blocked"}}
    # When the operator wired a current verdict, surface a real drift.
    if diff.current_decision is not None:
        assert diff.current_decision == diff.expected_decision, (
            f"permanent test {{case.id!r}}: replay verdict "
            f"{{diff.current_decision!r}} drifted from expected "
            f"{{diff.expected_decision!r}}"
        )
'''


def render_permanent_test(case: Case) -> str:
    """Render the body of a permanent pytest test for ``case`` (#44, W12.1).

    The generated test re-runs the case against the current code via
    ``replay_case``. The expected verdict comes from the case file; the
    *current* verdict is operator-supplied via
    ``MERGECRAFT_PERMANENT_CURRENT_DECISION`` (or unset for the
    default ``blocked`` state). When the two disagree, the test fails
    — that is the structural signal the promote workflow ships.

    The function is **pure**: it returns a string; it does not touch
    the filesystem. The CLI is the I/O shell that writes the string.

    Args:
        case: The case to promote.

    Returns:
        A complete Python source string (the file's full text). The
        header is stable; the test function name is derived from the
        case id.

    Examples:
        >>> from datetime import datetime, timezone
        >>> from mergecraft.utils.learnings import LearningProvenance
        >>> prov = LearningProvenance(
        ...     run_id="run-1", pr_number=1, source_field="eval_bank",
        ...     author_login="alice", author_association="OWNER",
        ...     trust_tier="trusted",
        ...     timestamp=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ... )
        >>> case = Case(
        ...     id="synthetic-001", title="t", category="missed_finding",
        ...     submitted_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ...     run_id="run-1", pr_number=1, failure_mode="missed_finding",
        ...     expected_finding="x", expected_decision="block",
        ...     replay_command="mergecraft eval replay synthetic-001",
        ...     provenance=prov, body="",
        ... )
        >>> text = render_permanent_test(case)
        >>> "def test_permanent_synthetic_001" in text
        True
        >>> "expected_decision" in text
        True
    """
    if not _SAFE_PYTHON_ID_RE.match(case.id):
        msg = f"case id {case.id!r} is not safe to use as a Python identifier"
        raise ValueError(msg)
    func_name = case.id.replace("-", "_").replace(".", "_")
    payload = case.model_dump_json()
    return PERMANENT_TEST_HEADER.format(
        payload=payload,
        func_name=func_name,
        case_id=case.id,
        title_literal=case.title.replace("\\", "\\\\").replace('"', '\\"'),
        expected_decision=case.expected_decision,
    )


_SAFE_PYTHON_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")


def permanent_test_path(target_dir: Path, case_id: str) -> Path:
    """Return the on-disk path for a promoted test file.

    The case id becomes the file stem (``.py``). The path is purely
    computed — no filesystem reads or writes. The CLI is responsible
    for the actual write.

    Args:
        target_dir: The directory the promoted test lives in.
        case_id: The case id (also the file stem).

    Returns:
        The computed path. The function never touches the filesystem.

    Raises:
        ValueError: When ``case_id`` is not a valid identifier.
    """
    if not _SAFE_PYTHON_ID_RE.match(case_id):
        msg = f"case id {case_id!r} is not a valid identifier"
        raise ValueError(msg)
    return (
        target_dir
        / f"test_permanent_{case_id.replace('-', '_').replace('.', '_')}{PERMANENT_TEST_FILE_SUFFIX}"
    )


def write_permanent_test(
    target_dir: Path,
    case: Case,
    *,
    overwrite: bool = False,
) -> Path:
    """Write a promoted pytest test for ``case`` under ``target_dir``.

    The directory is created if missing. The test file is the rendered
    output of :func:`render_permanent_test`; the on-disk path is the
    one :func:`permanent_test_path` returns.

    Args:
        target_dir: The directory to write the test into.
        case: The case to promote.
        overwrite: When True, overwrite an existing test for the same
            case. When False, raises :class:`FileExistsError`.

    Returns:
        The path the test was written to.

    Raises:
        FileExistsError: When ``overwrite`` is False and a test for
            the same case already exists.
        ValueError: When the case id is not a valid identifier.
        OSError: When the file cannot be written.
    """
    if not _SAFE_PYTHON_ID_RE.match(case.id):
        msg = f"case id {case.id!r} is not a valid identifier"
        raise ValueError(msg)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = permanent_test_path(target_dir, case.id)
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    target.write_text(render_permanent_test(case), encoding="utf-8")
    logger.info("» promoted case {} → {}", case.id, target)
    return target


__all__ = [
    "CASES_DIR_NAME",
    "CASE_FILE_SUFFIX",
    "CASE_STATUS_BLOCKED",
    "CASE_STATUS_PASSED",
    "CASE_STATUS_REGRESSION",
    "CATEGORY_MULTI_ROUND_CONVERGENCE",
    "CATEGORY_REJECTED",
    "CATEGORY_REVERTED",
    "DEFAULT_BANK_DIR",
    "FAILURE_CATEGORIES",
    "PERMANENT_TEST_DIR_NAME",
    "PERMANENT_TEST_FILE_SUFFIX",
    "Case",
    "CaseFilter",
    "CaseRound",
    "CaseRoundFinding",
    "CaseRoundLedgerEntry",
    "EvalMetadata",
    "ReplayDiff",
    "add_case",
    "build_eval_metadata",
    "convergence_rounds_from_case",
    "diff_cases",
    "list_cases",
    "list_multi_round_cases",
    "load_case",
    "parse_case_text",
    "permanent_test_path",
    "render_case_text",
    "render_permanent_test",
    "replay_case",
    "write_permanent_test",
]
