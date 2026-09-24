"""Diff scoping, scope exceptions, and ``introduced_by_pr`` annotation (D6)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.review_policy.manifest_names import DEPENDENCY_MANIFEST_NAMES, LOCKFILE_NAMES
from mergecraft.review_taxonomy import WITHDRAWN_FINDINGS_HEADING, finding_fingerprint

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mergecraft.analyzers.finding import Finding

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_NEW_FILE_RE = re.compile(r"^new file mode ")
_DEV_NULL_RE = re.compile(r"^--- /dev/null")
_MIGRATION_PREFIXES: tuple[str, ...] = (
    "db/migrations/",
    "migrations/",
    "alembic/versions/",
)

# ── diff header parsing (AN-D7) ───────────────────────────────────────────────
# A ``diff --git`` header is not ``a/<old> b/<new>`` split on whitespace: Git
# C-quotes a path that contains a space, a quote, a backslash, a control
# character, or a non-ASCII byte. Splitting the raw header on `` b/`` therefore
# misreads a quoted or space-bearing path, attaching the next file's hunks to
# the previous file. Every path source is decoded the same way, and a header
# that cannot be read clears the current file so its hunks are dropped rather
# than misattributed.
_DIFF_GIT_PREFIX = "diff --git "
_RENAME_TO_PREFIX = "rename to "
_POSTIMAGE_PREFIX = "+++ "
_DEV_NULL_PATH = "/dev/null"
_A_PREFIX = "a/"
_B_PREFIX = "b/"

# Header-line kinds returned by :func:`_classify_header_line`.
_HEADER_FILE = "file"
_HEADER_RENAME = "rename"
_HEADER_POSTIMAGE = "postimage"

_C_ESCAPES: dict[str, int] = {
    "a": 0x07,
    "b": 0x08,
    "f": 0x0C,
    "n": 0x0A,
    "r": 0x0D,
    "t": 0x09,
    "v": 0x0B,
    '"': 0x22,
    "\\": 0x5C,
}
_OCTAL_DIGITS = frozenset("01234567")


def _unquote_git_path(token: str) -> str | None:
    """Decode a Git C-style quoted path, or return an unquoted token unchanged.

    Git wraps a path in double quotes and escapes it C-style (``\\t``, ``\\n``,
    ``\\"``, ``\\\\``, and octal ``\\NNN`` for a non-ASCII byte) when the path
    needs it. The decoded bytes are interpreted as UTF-8. Returns ``None`` for
    malformed quoting or bytes that are not valid UTF-8.
    """
    if not token.startswith('"'):
        return token
    if len(token) < 2 or not token.endswith('"'):
        return None
    body = token[1:-1]
    out = bytearray()
    index = 0
    length = len(body)
    while index < length:
        char = body[index]
        if char != "\\":
            out.extend(char.encode("utf-8"))
            index += 1
            continue
        index += 1
        if index >= length:
            return None
        escape = body[index]
        mapped = _C_ESCAPES.get(escape)
        if mapped is not None:
            out.append(mapped)
            index += 1
            continue
        if escape in _OCTAL_DIGITS:
            octal = body[index : index + 3]
            if len(octal) != 3 or any(digit not in _OCTAL_DIGITS for digit in octal):
                return None
            out.append(int(octal, 8) & 0xFF)
            index += 3
            continue
        return None
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _take_quoted_token(text: str) -> tuple[str | None, str]:
    """Split a leading C-quoted token from ``text`` and decode it."""
    if not text.startswith('"'):
        return None, text
    index = 1
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == '"':
            return _unquote_git_path(text[: index + 1]), text[index + 1 :]
        index += 1
    return None, text


def _strip_diff_prefix(path: str, prefix: str) -> str:
    """Drop a leading ``a/`` or ``b/`` diff prefix when present."""
    return path[len(prefix) :] if path.startswith(prefix) else path


def _split_diff_git_paths(body: str) -> tuple[str, str] | None:
    """Split ``a/<old> b/<new>`` into the two unquoted paths.

    Returns ``None`` when the body cannot be read as two prefixed paths.
    """
    if body.startswith('"'):
        old, rest = _take_quoted_token(body)
        if old is None:
            return None
        new, tail = _take_quoted_token(rest.lstrip(" "))
        if new is None or tail.strip():
            return None
        return _strip_diff_prefix(old, _A_PREFIX), _strip_diff_prefix(new, _B_PREFIX)
    separator = body.find(" b/")
    if separator == -1:
        return None
    old_raw = body[:separator]
    new_raw = body[separator + 1 :]
    if not old_raw.startswith(_A_PREFIX) or not new_raw.startswith(_B_PREFIX):
        return None
    return old_raw[len(_A_PREFIX) :], new_raw[len(_B_PREFIX) :]


def _path_from_rename(raw_line: str) -> str | None:
    """Return the post-image path named by a ``rename to`` line."""
    token = raw_line[len(_RENAME_TO_PREFIX) :].strip()
    if not token:
        return None
    return _unquote_git_path(token)


def _path_from_postimage(raw_line: str) -> str | None:
    """Return the post-image path named by a ``+++`` line, or ``None``."""
    token = raw_line[len(_POSTIMAGE_PREFIX) :].strip()
    if not token or token == _DEV_NULL_PATH:
        return None
    decoded = _unquote_git_path(token)
    if decoded is None:
        return None
    return _strip_diff_prefix(decoded, _B_PREFIX)


def _classify_header_line(raw_line: str, *, in_hunk: bool) -> tuple[str, str | None] | None:
    """Classify a diff header line as ``(kind, path)``, or ``None``.

    ``kind`` is ``"file"`` for a ``diff --git`` header (``path`` is ``None``
    when the header cannot be parsed, which clears the current file),
    ``"rename"`` for a ``rename to`` directive, or ``"postimage"`` for a
    ``+++`` line. A ``+++`` line is a path source only before the file's first
    hunk: inside a hunk, added content starting with ``++ `` renders as
    ``+++ `` and must not be read as a header.
    """
    if raw_line.startswith(_DIFF_GIT_PREFIX):
        paths = _split_diff_git_paths(raw_line[len(_DIFF_GIT_PREFIX) :])
        return (_HEADER_FILE, paths[1] if paths is not None else None)
    if raw_line.startswith(_RENAME_TO_PREFIX):
        return (_HEADER_RENAME, _path_from_rename(raw_line))
    if not in_hunk and raw_line.startswith(_POSTIMAGE_PREFIX):
        return (_HEADER_POSTIMAGE, _path_from_postimage(raw_line))
    return None


class _DiffPathTracker:
    """Resolve the current file path while walking a unified diff.

    Shared by :func:`parse_diff_scope` and :func:`iter_added_diff_lines` so the
    two cannot disagree about which file a hunk belongs to.
    """

    __slots__ = ("current_path", "in_hunk")

    def __init__(self) -> None:
        self.current_path: str | None = None
        self.in_hunk = False

    def consume(self, raw_line: str) -> bool:
        """Update the tracker from ``raw_line``; return True if it was a header."""
        header = _classify_header_line(raw_line, in_hunk=self.in_hunk)
        if header is None:
            return False
        kind, path = header
        if kind == _HEADER_FILE:
            self.current_path = path
            self.in_hunk = False
        elif path is not None:
            self.current_path = path
        return True

    def enter_hunk(self) -> None:
        """Mark that the first hunk of the current file has been seen."""
        self.in_hunk = True


@dataclass(frozen=True, slots=True)
class DiffScope:
    """Parsed diff metadata for scoping."""

    hunk_ranges: dict[str, list[tuple[int, int]]]
    added_files: frozenset[str]
    changed_lockfiles: frozenset[str]
    changed_workflows: frozenset[str]
    changed_migrations: frozenset[str]
    changed_dependency_manifests: frozenset[str]


def parse_diff_scope(diff_text: str) -> DiffScope:
    """Parse a unified diff into hunk ranges and explicit scope-exception paths."""
    hunk_ranges: dict[str, list[tuple[int, int]]] = {}
    added_files: set[str] = set()
    changed_lockfiles: set[str] = set()
    changed_workflows: set[str] = set()
    changed_migrations: set[str] = set()
    changed_dependency_manifests: set[str] = set()

    tracker = _DiffPathTracker()
    new_line = 0
    hunk_end = 0
    is_new_file = False

    for raw_line in diff_text.splitlines():
        if tracker.consume(raw_line):
            if raw_line.startswith(_DIFF_GIT_PREFIX):
                is_new_file = False
            continue

        current_path = tracker.current_path
        if current_path is None:
            continue

        if _NEW_FILE_RE.match(raw_line):
            is_new_file = True
            added_files.add(current_path)
            continue

        if raw_line.startswith("--- ") and _DEV_NULL_RE.match(raw_line):
            is_new_file = True
            added_files.add(current_path)
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match:
            new_line = int(hunk_match.group(1))
            count = int(hunk_match.group(2) or "1")
            hunk_end = new_line + max(count, 1) - 1
            tracker.enter_hunk()
            hunk_ranges.setdefault(current_path, []).append((new_line, hunk_end))
            _record_exception_paths(
                current_path,
                is_new_file=is_new_file,
                changed_lockfiles=changed_lockfiles,
                changed_workflows=changed_workflows,
                changed_migrations=changed_migrations,
                changed_dependency_manifests=changed_dependency_manifests,
            )
            continue

        if not hunk_match and current_path and raw_line[:1] in {" ", "+", "-"}:
            if raw_line.startswith("+"):
                if new_line <= hunk_end:
                    _record_exception_paths(
                        current_path,
                        is_new_file=is_new_file,
                        changed_lockfiles=changed_lockfiles,
                        changed_workflows=changed_workflows,
                        changed_migrations=changed_migrations,
                        changed_dependency_manifests=changed_dependency_manifests,
                    )
                new_line += 1
            elif raw_line.startswith(" "):
                new_line += 1

    return DiffScope(
        hunk_ranges=hunk_ranges,
        added_files=frozenset(added_files),
        changed_lockfiles=frozenset(changed_lockfiles),
        changed_workflows=frozenset(changed_workflows),
        changed_migrations=frozenset(changed_migrations),
        changed_dependency_manifests=frozenset(changed_dependency_manifests),
    )


def iter_added_diff_lines(diff_text: str) -> Iterator[tuple[str, int, str]]:
    """Yield ``(path, new-file line number, added line content)`` from a unified diff."""
    tracker = _DiffPathTracker()
    new_line = 0

    for raw_line in diff_text.splitlines():
        if tracker.consume(raw_line):
            continue

        current_path = tracker.current_path
        if current_path is None:
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match:
            new_line = int(hunk_match.group(1))
            tracker.enter_hunk()
            continue

        if not tracker.in_hunk and raw_line.startswith(("--- ", "+++ ")):
            continue

        prefix = raw_line[:1]
        if prefix == "+":
            yield current_path, new_line, raw_line[1:]
            new_line += 1
        elif prefix == " ":
            new_line += 1


def _record_exception_paths(
    path: str,
    *,
    is_new_file: bool,
    changed_lockfiles: set[str],
    changed_workflows: set[str],
    changed_migrations: set[str],
    changed_dependency_manifests: set[str],
) -> None:
    name = Path(path).name
    if is_new_file:
        changed_dependency_manifests.add(path)
    if name in LOCKFILE_NAMES:
        changed_lockfiles.add(path)
    if name in DEPENDENCY_MANIFEST_NAMES:
        changed_dependency_manifests.add(path)
    if path.startswith((".github/workflows/", ".github/actions/")):
        changed_workflows.add(path)
    if any(path.startswith(prefix) for prefix in _MIGRATION_PREFIXES):
        changed_migrations.add(path)


def _line_intersects_hunks(
    path: str, start_line: int | None, end_line: int | None, scope: DiffScope
) -> bool:
    ranges = scope.hunk_ranges.get(path)
    if not ranges:
        return False
    if start_line is None or end_line is None:
        return True
    return any(start_line <= hunk_end and end_line >= hunk_start for hunk_start, hunk_end in ranges)


_INFRASTRUCTURE_RULE_IDS = frozenset({"analyzers.sandbox-unavailable"})


def _matches_scope_exception(path: str, scope: DiffScope) -> bool:
    if path in scope.added_files:
        return True
    if path in scope.changed_lockfiles:
        return True
    if path in scope.changed_workflows:
        return True
    if path in scope.changed_migrations:
        return True
    return path in scope.changed_dependency_manifests


def filter_to_diff(findings: list[Finding], *, diff_text: str) -> list[Finding]:
    """Drop findings whose line ranges do not intersect any diff hunk."""
    scope = parse_diff_scope(diff_text)
    kept: list[Finding] = []
    for finding in findings:
        if _line_intersects_hunks(finding.path, finding.start_line, finding.end_line, scope):
            kept.append(finding)
    return kept


def apply_scope_exceptions(
    findings: list[Finding],
    *,
    diff_text: str,
    repo_root: Path | None = None,
    scope: DiffScope | None = None,
) -> list[Finding]:
    """Keep findings on changed hunks or on explicit PR-scope exception paths."""
    _ = repo_root
    scope = scope if scope is not None else parse_diff_scope(diff_text)
    kept: list[Finding] = []
    for finding in findings:
        # Project-level findings have no line; their path is often a config
        # file that is not in the diff (tsc → tsconfig.json on a .ts-only PR).
        if finding.start_line is None:
            kept.append(finding)
            continue
        if finding.rule_id in _INFRASTRUCTURE_RULE_IDS:
            kept.append(finding)
            continue
        on_hunk = _line_intersects_hunks(finding.path, finding.start_line, finding.end_line, scope)
        if on_hunk or _matches_scope_exception(finding.path, scope):
            kept.append(finding)
    return kept


def annotate_introduced_by_pr(
    findings: list[Finding],
    *,
    base_run_performed: bool,
    is_new_in_base: bool = False,
) -> list[Finding]:
    """Set ``introduced_by_pr`` per D6 — ``unknown`` unless a base run confirms novelty."""
    annotated: list[Finding] = []
    for finding in findings:
        if finding.introduced_by_pr in {"true", "false"}:
            annotated.append(finding)
            continue
        value = "unknown"
        if base_run_performed and is_new_in_base:
            value = "true"
        annotated.append(finding.model_copy(update={"introduced_by_pr": value}))
    return annotated


def base_comparison_available(*, base_comparison: str, offline: bool) -> bool:
    """Return whether full base-vs-head comparison may run (D6 amendment)."""
    if base_comparison != "full":
        return False
    return not offline


def introduced_by_base_diff(
    head_findings: list[Finding],
    base_findings: list[Finding],
) -> list[Finding]:
    """Mark findings present on head but absent on base as PR-introduced."""
    from mergecraft.analyzers.baseline_suppression import _baseline_identity

    base_identities = {_baseline_identity(finding) for finding in base_findings}
    result: list[Finding] = []
    for finding in head_findings:
        is_new = _baseline_identity(finding) not in base_identities
        result.append(
            finding.model_copy(update={"introduced_by_pr": "true" if is_new else "false"})
        )
    return result


def suppress_withdrawn_findings(
    findings: list[Finding],
    learnings_text: str,
) -> list[Finding]:
    """Drop findings whose fingerprint appears under ``WITHDRAWN_FINDINGS_HEADING`` (D11)."""
    withdrawn = withdrawn_fingerprints(learnings_text)
    if not withdrawn:
        return findings
    return [finding for finding in findings if finding.fingerprint not in withdrawn]


def withdrawn_fingerprints(learnings_text: str) -> frozenset[str]:
    """Return every finding fingerprint refuted under ``WITHDRAWN_FINDINGS_HEADING``.

    Public because agent-finding verification (C6) skips a finding the author
    already refuted, and it must read the same section, by the same rules, as
    analyzer suppression does — a second parser would drift.
    """
    if WITHDRAWN_FINDINGS_HEADING not in learnings_text:
        return frozenset()
    section = learnings_text.split(WITHDRAWN_FINDINGS_HEADING, 1)[1]
    next_heading = re.search(r"\n## ", section)
    if next_heading:
        section = section[: next_heading.start()]
    fingerprints: set[str] = set()
    for match in re.finditer(
        r"<!-- mergecraft-finding:v1:([0-9a-f]{24}) -->",
        section,
    ):
        fingerprints.add(match.group(1))
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fp = finding_fingerprint(path="", body=stripped)
        if len(fp) == 24:
            fingerprints.add(fp)
    return frozenset(fingerprints)


def changed_paths_from_scope(scope: DiffScope) -> list[str]:
    paths = set(scope.hunk_ranges.keys())
    paths.update(scope.added_files)
    paths.update(scope.changed_lockfiles)
    paths.update(scope.changed_workflows)
    paths.update(scope.changed_migrations)
    paths.update(scope.changed_dependency_manifests)
    return sorted(paths)


def filter_generated_scope(
    findings: list[Finding],
    *,
    diff_text: str,
    scope: DiffScope | None = None,
) -> list[Finding]:
    """Drop generated/minified/vendored findings policy excludes (D4)."""
    from mergecraft.classify.generated_files import ChangeSet, finding_survives_generated_policy

    scope = scope if scope is not None else parse_diff_scope(diff_text)
    change: ChangeSet = {"changed_paths": changed_paths_from_scope(scope)}
    kept: list[Finding] = []
    for finding in findings:
        if finding_survives_generated_policy(finding.path, change=change):
            kept.append(finding)
    return kept


def scope_findings(
    findings: list[Finding],
    *,
    diff_text: str,
    repo_root: Path | None = None,
    learnings_text: str = "",
    scope: DiffScope | None = None,
) -> list[Finding]:
    """Apply diff scoping, exceptions, generated policy, and withdrawn suppression."""
    parsed = scope if scope is not None else parse_diff_scope(diff_text)
    scoped = apply_scope_exceptions(
        findings,
        diff_text=diff_text,
        repo_root=repo_root,
        scope=parsed,
    )
    scoped = filter_generated_scope(scoped, diff_text=diff_text, scope=parsed)
    return suppress_withdrawn_findings(scoped, learnings_text)


def line_intersects_hunks(
    path: str, start_line: int | None, end_line: int | None, scope: DiffScope
) -> bool:
    """Return whether a line span intersects any diff hunk on ``path``."""
    return _line_intersects_hunks(path, start_line, end_line, scope)


__all__ = [
    "DiffScope",
    "annotate_introduced_by_pr",
    "apply_scope_exceptions",
    "base_comparison_available",
    "changed_paths_from_scope",
    "filter_generated_scope",
    "filter_to_diff",
    "introduced_by_base_diff",
    "iter_added_diff_lines",
    "line_intersects_hunks",
    "parse_diff_scope",
    "scope_findings",
    "suppress_withdrawn_findings",
    "withdrawn_fingerprints",
]
