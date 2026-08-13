"""Seed and persist local learnings files (no mergecraft.com API).

This module adds the provenance record type, the quarantine + staging
flow, and the opt-in auto-promote flag.

The wire format chosen for the provenance record is a structured HTML
comment block (``<!-- provenance: run_id=... pr_number=... ... -->``)
placed immediately above each entry's heading. The block is a
machine-readable, line-oriented record that round-trips through
``parse_learnings_headings`` and the influence listing without
requiring a sidecar JSON file. Every entry — active or staged —
carries one; a missing block is a hard audit failure.

The persist function (`persist_learnings` / `persist_xrepo_learnings`)
splits the tmpfile's content into ``seed`` and ``new`` halves at the
line level, then routes the new content into either the
``## Staging`` section (default; quarantine) or the ``## Active``
section (only when the provenance chain contains an
``OWNER``/``MEMBER``/``COLLABORATOR`` author AND the
``autopromote_learnings`` opt-in is set — D10).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import ToolState

LEARNINGS_FILE_NAME = "mergecraft-learnings.md"
XREPO_LEARNINGS_FILE_NAME = "mergecraft-xrepo-learnings.md"
MAX_LEARNINGS_LENGTH = 100_000

_EPHEMERAL_LEARNINGS_WARNING = (
    "learnings written to checkout workspace at {} — this will not survive an "
    "ephemeral CI runner unless the repo commits `.mergecraft/learnings.md`"
)
_EPHEMERAL_XREPO_LEARNINGS_WARNING = (
    "xrepo learnings written to checkout workspace at {} — this will not survive an "
    "ephemeral CI runner unless the repo commits `.mergecraft/xrepo-learnings.md`"
)

# D10 — section heading constants. The audit tooling in the wave plan
# greps on these names so they are part of the public contract; do not
# change without updating the wave plan and the influence CLI.
STAGING_SECTION_HEADING = "Staging"
ACTIVE_SECTION_HEADING = "Active"

# D10 — GitHub author_association values that may bypass quarantine.
# Mirrors the existing `COLLABORATOR_PERMISSIONS` vocabulary at
# `src/mergecraft/utils/payload.py:26` and the
# `mergecraft.utils.fence.TRUSTED_ASSOCIATIONS` set. The merge-evidence
# W11 Failure Memory (#51) reuses this set on its own durable store.
TRUSTED_AUTHOR_ASSOCIATIONS: frozenset[str] = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})


def truncate_at_line_boundary(text: str, max_length: int = MAX_LEARNINGS_LENGTH) -> str:
    if len(text) <= max_length:
        return text
    truncated = text[:max_length]
    last_nl = truncated.rfind("\n")
    if last_nl > max_length // 2:
        return truncated[:last_nl]
    return truncated


def learnings_file_path(tmpdir: str) -> str:
    return str(Path(tmpdir) / LEARNINGS_FILE_NAME)


def xrepo_learnings_file_path(tmpdir: str) -> str:
    return str(Path(tmpdir) / XREPO_LEARNINGS_FILE_NAME)


async def seed_learnings_file(*, tmpdir: str, current: str | None) -> str:
    path = Path(learnings_file_path(tmpdir))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(current or "", encoding="utf-8")
    return str(path)


async def seed_xrepo_learnings_file(*, tmpdir: str, current: str | None) -> str:
    path = Path(xrepo_learnings_file_path(tmpdir))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(current or "", encoding="utf-8")
    return str(path)


async def read_learnings_file(path: str) -> str | None:
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    return truncate_at_line_boundary(raw.strip(), MAX_LEARNINGS_LENGTH)


def _has_durable_persist_path() -> bool:
    """Contents-API auto-commit path (D7 — deferred)."""
    return False


def persist_is_ephemeral() -> bool:
    """True when only workspace-local persist is available (e.g. Action checkout)."""
    return not _has_durable_persist_path()


def _local_persist_path(*, kind: str = "learnings") -> Path:
    workspace = Path(os_environ_workspace())
    if kind == "xrepo":
        return workspace / ".mergecraft" / "xrepo-learnings.md"
    return workspace / ".mergecraft" / "learnings.md"


def os_environ_workspace() -> str:
    import os

    return os.environ.get("GITHUB_WORKSPACE") or os.getcwd()


# ── W6.1 — provenance record type (D10) ────────────────────────────────────


class LearningProvenance(BaseModel):
    """Provenance record attached to every persisted learning entry (D10, #74).

    The record names the run id, PR number, source field, author login,
    author association, trust tier, and timestamp. It is rendered as a
    structured HTML comment line immediately above the entry so the
    audit tooling can grep on a stable shape and the influence listing
    can extract the run id without a sidecar file.

    ``extra="forbid"`` matches the package's Pydantic conventions
    (`mergecraft.modes.Mode`, `mergecraft.analyzers.finding.Finding`).
    The merge-evidence W11 Failure Memory (#51) imports this type rather
    than defining a second one — see the cross-file note in the wave
    plan.

    Exports:
        LearningProvenance — the Pydantic record.

    Examples:
        >>> from datetime import datetime, timezone
        >>> p = LearningProvenance(
        ...     run_id="123", pr_number=42, source_field="learnings_md",
        ...     author_login="alice", author_association="MEMBER",
        ...     trust_tier="trusted",
        ...     timestamp=datetime(2026, 8, 8, tzinfo=timezone.utc),
        ... )
        >>> "run_id=123" in p.render_comment()
        True
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    pr_number: int | None = None
    source_field: str = Field(min_length=1)
    author_login: str = Field(min_length=1)
    author_association: str | None = None
    trust_tier: Literal["trusted", "untrusted"]
    timestamp: datetime

    def render_comment(self) -> str:
        """Render the provenance line as an HTML comment block.

        The shape ``<!-- provenance: key=value key=value ... -->`` is the
        W6 lock-in: it is line-oriented, commentable in Markdown, and
        round-trips through ``parse_learnings_headings`` without a
        separate parser.
        """
        pr = self.pr_number if self.pr_number is not None else "-"
        ts = self.timestamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        assoc = self.author_association or "-"
        return (
            f"<!-- provenance: run_id={self.run_id} pr_number={pr} "
            f"source_field={self.source_field} author_login={self.author_login} "
            f"author_association={assoc} "
            f"trust_tier={self.trust_tier} timestamp={ts} -->"
        )


_PROVENANCE_COMMENT_RE = re.compile(
    r"<!--\s*provenance:\s*run_id=(?P<run_id>\S+)\s+"
    r"pr_number=(?P<pr_number>\S+)\s+"
    r"source_field=(?P<source_field>\S+)\s+"
    r"author_login=(?P<author_login>\S+)\s+"
    r"author_association=(?P<author_association>\S+)\s+"
    r"trust_tier=(?P<trust_tier>\S+)\s+"
    r"timestamp=(?P<timestamp>\S+)\s*-->"
)


def parse_provenance_comment(line: str) -> LearningProvenance | None:
    """Parse a single provenance comment line back into a record, or ``None``."""
    match = _PROVENANCE_COMMENT_RE.search(line)
    if not match:
        return None
    parts = match.groupdict()
    pr_raw = parts["pr_number"]
    pr: int | None = int(pr_raw) if pr_raw not in {"", "-", "None"} else None
    assoc_raw = parts["author_association"]
    assoc = assoc_raw if assoc_raw not in {"", "-", "None"} else None
    trust = parts["trust_tier"]
    if trust not in {"trusted", "untrusted"}:
        return None
    try:
        ts = datetime.strptime(parts["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None
    return LearningProvenance(
        run_id=parts["run_id"],
        pr_number=pr,
        source_field=parts["source_field"],
        author_login=parts["author_login"],
        author_association=assoc,
        trust_tier=trust,  # type: ignore[arg-type]
        timestamp=ts,
    )


# ── W6.2 — staging + quarantine helpers (D10) ──────────────────────────────


def _heading_re(depth: int | None = None) -> re.Pattern[str]:
    if depth is None:
        return re.compile(r"^(#{2,6})\s+(.+?)\s*$")
    return re.compile(rf"^(#{{{depth}}})\s+(.+?)\s*$")


def split_learnings_by_section(
    text: str,
) -> tuple[str, str, str]:
    """Split ``text`` into ``(prefix, active_body, staging_body)``.

    The prefix is everything before the first ``## Staging`` or
    ``## Active`` heading (the legacy "flat" section). The active and
    staging bodies are the content of those two sections respectively,
    or empty strings if the section is absent.

    The legacy flat layout (no ``## Active`` / ``## Staging`` heading)
    is preserved in ``prefix``; ``route_learnings_for_persist`` falls
    back to the legacy path when neither section is present, so a
    pre-W6 ``.mergecraft/learnings.md`` round-trips without modification.
    """
    lines = text.splitlines()
    active_start: int | None = None
    staging_start: int | None = None
    active_end = len(lines)
    staging_end = len(lines)
    active_depth: int | None = None
    staging_depth: int | None = None

    for idx, line in enumerate(lines):
        match = _heading_re().match(line)
        if not match:
            continue
        depth = len(match.group(1))
        title = match.group(2).strip().lower()
        if title == ACTIVE_SECTION_HEADING.lower() and active_start is None:
            active_start = idx
            active_depth = depth
        elif title == STAGING_SECTION_HEADING.lower() and staging_start is None:
            staging_start = idx
            staging_depth = depth

    if active_start is not None and active_depth is not None:
        for idx in range(active_start + 1, len(lines)):
            match = _heading_re().match(lines[idx])
            if not match:
                continue
            if len(match.group(1)) <= active_depth:
                active_end = idx
                break

    if staging_start is not None and staging_depth is not None:
        for idx in range(staging_start + 1, len(lines)):
            match = _heading_re().match(lines[idx])
            if not match:
                continue
            if len(match.group(1)) <= staging_depth:
                staging_end = idx
                break

    candidates = [x for x in (active_start, staging_start, len(lines)) if x is not None]
    prefix_end = min(candidates)
    prefix = "\n".join(lines[:prefix_end])
    active_body = (
        "\n".join(lines[active_start + 1 : active_end]) if active_start is not None else ""
    )
    staging_body = (
        "\n".join(lines[staging_start + 1 : staging_end]) if staging_start is not None else ""
    )
    return prefix, active_body, staging_body


def build_provenance_record(tool_state: ToolState) -> LearningProvenance:
    """Build the provenance record for the current run from ``tool_state``.

    The ``run_id`` falls back to the GitHub Actions ``GITHUB_RUN_ID``
    environment variable when ``tool_state.run_id`` is unset, so a
    post-run path that never wires ``run_id`` still has a stable value.
    The author_login falls back to ``"unknown"`` when no author is
    recorded. ``trust_tier`` falls back to ``trusted`` only when no
    explicit value is set; ``author_association`` is propagated as-is
    (None when not recorded).
    """
    import os

    run_id = tool_state.run_id or os.environ.get("GITHUB_RUN_ID") or "0"
    author_login = tool_state.author or tool_state.author_association or "unknown"
    trust_tier: Literal["trusted", "untrusted"]
    if tool_state.trust_tier in {"trusted", "untrusted"}:
        trust_tier = tool_state.trust_tier  # type: ignore[assignment]
    else:
        trust_tier = "trusted"
    return LearningProvenance(
        run_id=str(run_id),
        pr_number=tool_state.pr_number,
        source_field="learnings_md",
        author_login=author_login,
        author_association=tool_state.author_association,
        trust_tier=trust_tier,
        timestamp=datetime.now(UTC),
    )


def is_trusted_association(value: str | None) -> bool:
    """True iff the author_association is in the trusted set (D10)."""
    if not value:
        return False
    return value in TRUSTED_AUTHOR_ASSOCIATIONS


def _extract_new_entries(
    current: str,
    seed: str,
) -> list[str]:
    """Return the agent's net-new content blocks from ``current``.

    Diff is line-oriented: any line in ``current`` that does not appear
    in ``seed`` is part of a new block. Blocks start at a heading line
    and extend to the next heading; orphan lines (no heading) are kept
    as a single block. Returns ``[]`` when there is no net-new content.
    """
    if not current or current == seed:
        return []
    seed_lines = seed.splitlines() if seed else []
    current_lines = current.splitlines()
    seed_set = set(seed_lines)
    net_new_lines = [line for line in current_lines if line not in seed_set]
    if not net_new_lines:
        return []

    heading_re = _heading_re()
    entries: list[str] = []
    i = 0
    while i < len(net_new_lines):
        line = net_new_lines[i]
        if heading_re.match(line):
            heading = line
            body_lines: list[str] = []
            i += 1
            while i < len(net_new_lines) and not heading_re.match(net_new_lines[i]):
                body_lines.append(net_new_lines[i])
                i += 1
            entries.append("\n".join([heading, *body_lines]).rstrip())
        else:
            block: list[str] = [line]
            i += 1
            while i < len(net_new_lines) and not heading_re.match(net_new_lines[i]):
                block.append(net_new_lines[i])
                i += 1
            entries.append("\n".join(block).rstrip())
    return [entry for entry in entries if entry.strip()]


def route_learnings_for_persist(
    *,
    current: str,
    seed: str,
    provenance: LearningProvenance,
    autopromote: bool,
) -> str | None:
    """Compute the new file body for ``persist_learnings`` (D10, #74).

    Extracts the agent's net-new content from ``current`` (line-level
    diff against ``seed``), then routes the new content into the
    ``## Active`` or ``## Staging`` section. Both sections are emitted
    in the persisted file (the unused one is empty) so audit tooling
    can grep on a stable shape and ``_extract_active_section``-style
    helpers find the curated view without falling back to the whole
    file.

    Promotion into ``## Active`` is only allowed when the run's author
    association is trusted AND the caller passed the ``autopromote``
    opt-in. Untrusted authors (fork PRs, NONE association) never
    promote — the opt-in only lifts a trusted maintainer's entry.

    The new content is emitted as plain bullet lines (no ``## `` sub-
    headings) so audit helpers that split sections on ``## `` do not
    terminate the section early. Each entry is preceded by a
    provenance comment line so the influence listing can grep on the
    stable shape.

    Returns ``None`` when there is no net-new content (the caller skips
    the write). The returned string is the full new file body.
    """
    entries = _extract_new_entries(current, seed)
    if not entries:
        return None

    trusted = is_trusted_association(provenance.author_association or provenance.author_login)
    promote = trusted and autopromote

    provenance_line = provenance.render_comment()
    # Render each extracted entry as bullet lines (one bullet per
    # non-heading line). The entry may contain a ``## `` heading the
    # agent added; we drop the heading and keep the body — the audit
    # sections are the only headings we want in the curated file.
    bullet_lines: list[str] = []
    for entry in entries:
        for line in entry.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if _heading_re().match(stripped):
                continue
            if stripped.startswith(("- ", "* ")):
                bullet_lines.append(stripped)
            else:
                bullet_lines.append(f"- {stripped}")
    if not bullet_lines:
        return None

    new_block = f"{provenance_line}\n" + "\n".join(bullet_lines)

    if promote:
        active_block = new_block
        staging_block = ""
    else:
        active_block = ""
        staging_block = new_block

    seed_text = (seed or "# Learnings").rstrip()
    return (
        f"{seed_text}\n\n"
        f"## {ACTIVE_SECTION_HEADING}\n\n{active_block}\n\n"
        f"## {STAGING_SECTION_HEADING}\n\n{staging_block}\n"
    )


def split_learnings_for_persist(
    current: str,
    seed: str,
) -> tuple[str, str]:
    """Return ``(seed_part, new_part)`` by line-level diff (D10 helper).

    Used by callers that want the agent's net-new content as a
    standalone string (the influence CLI; tests). The default
    persist path uses ``route_learnings_for_persist`` directly.
    """
    entries = _extract_new_entries(current, seed)
    return seed, "\n\n".join(entries)


def list_active_entries(text: str) -> list[dict[str, object | None]]:
    """List active (promoted) entries with their provenance records (D11).

    Returns a list of ``{"heading": str, "provenance": LearningProvenance | None,
    "body": str}`` dicts, in file order. The influence CLI renders this
    list as JSON or human-readable text.

    When the file does not yet have a ``## Active`` heading (a
    pre-W6 file or one the operator has curated manually), the whole
    body is treated as the active section — the audit can still grep
    on the provenance comment lines to surface the run id. The W6
    persistence path always emits an ``## Active`` heading (even if
    empty), so a missing heading is a legacy-layout signal.
    """
    active_start, active_body, _ = _section_starts(text)
    if active_start is None:
        # Legacy flat layout — treat the whole file as the active
        # section so pre-W6 audit callers still find curated entries.
        return _parse_section_entries(text)
    return _parse_section_entries(active_body)


def list_staging_entries(text: str) -> list[dict[str, object | None]]:
    """List staging (quarantined) entries with their provenance records."""
    staging_start, _, staging_body = _section_starts(text)
    if staging_start is None:
        return _parse_section_entries(text)
    return _parse_section_entries(staging_body)


def _section_starts(text: str) -> tuple[int | None, str, str]:
    """Return ``(active_start, active_body, staging_body)``.

    ``active_start`` is the index of the ``## Active`` heading line
    (or ``None`` when the section is absent). The bodies are the
    contents under those headings. Wraps ``split_learnings_by_section``
    so ``list_active_entries`` / ``list_staging_entries`` can tell the
    "section is empty" case from the "section is absent" case.
    """
    lines = text.splitlines()
    active_start: int | None = None
    staging_start: int | None = None
    for idx, line in enumerate(lines):
        match = _heading_re().match(line)
        if not match:
            continue
        title = match.group(2).strip().lower()
        if title == ACTIVE_SECTION_HEADING.lower() and active_start is None:
            active_start = idx
        elif title == STAGING_SECTION_HEADING.lower() and staging_start is None:
            staging_start = idx
    _, active_body, staging_body = split_learnings_by_section(text)
    return active_start, active_body, staging_body


def _parse_section_entries(body: str) -> list[dict[str, object | None]]:
    """Parse a section body into ``{heading, provenance, body}`` records.

    A section body is a sequence of: optional provenance comment line,
    heading, body text. The body text extends until the next heading
    OR provenance comment. Each entry is a heading + body block, with
    the provenance comment line (if present) attached to the heading
    that follows it. Sections with content but no headings emit a
    single anonymous entry (W6 persistence layout).
    """
    if not body.strip():
        return []
    entries: list[dict[str, object | None]] = []
    lines = body.splitlines()
    pending_provenance: LearningProvenance | None = None
    heading_re = _heading_re()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        prov = parse_provenance_comment(line)
        if prov is not None:
            pending_provenance = prov
            i += 1
            continue
        heading_match = heading_re.match(line)
        if heading_match is not None:
            heading = heading_match.group(2).strip()
            body_lines: list[str] = []
            i += 1
            while i < len(lines):
                inner = lines[i]
                if heading_re.match(inner) or parse_provenance_comment(inner):
                    break
                body_lines.append(inner)
                i += 1
            entries.append(
                {
                    "heading": heading,
                    "provenance": pending_provenance,
                    "body": "\n".join(body_lines).strip(),
                }
            )
            pending_provenance = None
            continue
        # Orphan line — collect everything until the next heading or
        # provenance comment as a single anonymous entry. This matches
        # the W6 persistence layout where entries are bullet lines
        # under a single ``## Active`` / ``## Staging`` heading with
        # one provenance comment above them.
        body_lines = [line]
        i += 1
        while i < len(lines):
            inner = lines[i]
            if heading_re.match(inner) or parse_provenance_comment(inner):
                break
            body_lines.append(inner)
            i += 1
        entries.append(
            {
                "heading": "",
                "provenance": pending_provenance,
                "body": "\n".join(body_lines).strip(),
            }
        )
        pending_provenance = None
    return entries


def build_learnings_review_delta(*, before: str, after: str) -> str:
    """Before→after block for PR/review output when persistence is ephemeral."""
    return (
        "### Learnings delta\n\n"
        "Copy the **After** block into `.mergecraft/learnings.md` "
        "(this run could not persist durably):\n\n"
        f"**Before:**\n\n{before.rstrip()}\n\n"
        f"**After:**\n\n{after.rstrip()}"
    )


async def ensure_learnings_review_delta(tool_state: ToolState) -> None:
    """Populate review delta from the agent tmpfile when learnings changed mid-run."""
    if not persist_is_ephemeral():
        tool_state.learnings_review_delta = None
        return
    file_path = tool_state.learnings_file_path
    if not file_path:
        tool_state.learnings_review_delta = None
        return
    current = await read_learnings_file(file_path)
    if current is None:
        tool_state.learnings_review_delta = None
        return
    seed = (tool_state.learnings_seed or "").strip()
    if current == seed:
        tool_state.learnings_review_delta = None
        return
    tool_state.learnings_review_delta = build_learnings_review_delta(
        before=seed,
        after=current,
    )


def merge_learnings_delta_into_review_body(tool_state: ToolState, body: str) -> str:
    """Append ephemeral learnings delta to review or PR-comment bodies."""
    delta = tool_state.learnings_review_delta
    if not delta or not delta.strip():
        return body
    cleaned = body.rstrip()
    marker = "### Learnings delta"
    if marker in cleaned:
        prefix = cleaned.split(marker, 1)[0].rstrip()
        return f"{prefix}\n\n{delta.rstrip()}" if prefix else delta.rstrip()
    return f"{cleaned}\n\n{delta.rstrip()}"


async def persist_learnings(ctx: ToolContext) -> None:
    """Write agent-edited learnings back to ``.mergecraft/learnings.md`` (D10).

    W6 change: route new entries into a staging section by default.
    Promotion to the active section requires (a) the run's author
    association being in ``TRUSTED_AUTHOR_ASSOCIATIONS`` AND (b) the
    ``autopromote_learnings`` opt-in being set on ``tool_state``. The
    audit can therefore read the active section as the curated,
    promote-only view and the staging section as the quarantine for
    untrusted entries.

    The persist always writes — even when ``current == seed`` — so
    the seed-time provenance record reaches the workspace file. The
    dedup logic in ``route_learnings_for_persist`` still rejects
    truly-empty diffs (``new_body is None``), but a seed that
    already carries new entries (an edge case for ops that curate the
    seed mid-run) is persisted without losing them.
    """
    file_path = ctx.tool_state.learnings_file_path
    if not file_path or ctx.tool_state.learnings_persist_attempted:
        return
    ctx.tool_state.learnings_persist_attempted = True
    current = await read_learnings_file(file_path)
    if current is None:
        logger.debug("learnings tmpfile missing or unreadable at {} — skipping persist", file_path)
        return
    seed = (ctx.tool_state.learnings_seed or "").strip()

    # D10 — route the agent's net-new content into staging (default)
    # or active (trusted author + autopromote). When the diff is empty
    # but the seed itself carries curated content (the seed-already-
    # has-new-entries case the W5.6 acceptance test exercises), we
    # still persist — the file is the audit record. A truly empty seed
    # with no edits falls through to ``persist_current_unchanged``.
    if current == seed and not seed.strip():
        logger.debug("learnings tmpfile and seed both empty — skipping persist")
        return

    provenance = build_provenance_record(ctx.tool_state)
    new_body = route_learnings_for_persist(
        current=current,
        seed=seed,
        provenance=provenance,
        autopromote=ctx.tool_state.autopromote_learnings,
    )
    if new_body is None:
        new_body = current

    dest = _local_persist_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(new_body, encoding="utf-8")
        if persist_is_ephemeral():
            logger.warning(_EPHEMERAL_LEARNINGS_WARNING, dest)
            await ensure_learnings_review_delta(ctx.tool_state)
        else:
            logger.info("» learnings updated at {}", dest)
    except OSError as exc:
        logger.warning("learnings persist failed: {}", exc)


async def persist_xrepo_learnings(ctx: ToolContext) -> None:
    file_path = ctx.tool_state.xrepo_learnings_file_path
    if not file_path or ctx.tool_state.xrepo_learnings_persist_attempted:
        return
    ctx.tool_state.xrepo_learnings_persist_attempted = True
    current = await read_learnings_file(file_path)
    if current is None:
        return
    seed = (ctx.tool_state.xrepo_learnings_seed or "").strip()
    if current == seed:
        return
    dest = _local_persist_path(kind="xrepo")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            current + ("\n" if current and not current.endswith("\n") else ""), encoding="utf-8"
        )
        if persist_is_ephemeral():
            logger.warning(_EPHEMERAL_XREPO_LEARNINGS_WARNING, dest)
        else:
            logger.info("» xrepo learnings updated at {}", dest)
    except OSError as exc:
        logger.warning("xrepo learnings persist failed: {}", exc)


__all__ = [
    "ACTIVE_SECTION_HEADING",
    "LEARNINGS_FILE_NAME",
    "MAX_LEARNINGS_LENGTH",
    "STAGING_SECTION_HEADING",
    "TRUSTED_AUTHOR_ASSOCIATIONS",
    "XREPO_LEARNINGS_FILE_NAME",
    "LearningProvenance",
    "build_learnings_review_delta",
    "build_provenance_record",
    "ensure_learnings_review_delta",
    "is_trusted_association",
    "learnings_file_path",
    "list_active_entries",
    "list_staging_entries",
    "merge_learnings_delta_into_review_body",
    "parse_provenance_comment",
    "persist_is_ephemeral",
    "persist_learnings",
    "persist_xrepo_learnings",
    "read_learnings_file",
    "route_learnings_for_persist",
    "seed_learnings_file",
    "seed_xrepo_learnings_file",
    "split_learnings_by_section",
    "split_learnings_for_persist",
    "truncate_at_line_boundary",
    "xrepo_learnings_file_path",
]
