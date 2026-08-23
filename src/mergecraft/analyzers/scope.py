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
_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")
_NEW_FILE_RE = re.compile(r"^new file mode ")
_DEV_NULL_RE = re.compile(r"^--- /dev/null")
_MIGRATION_PREFIXES: tuple[str, ...] = (
    "db/migrations/",
    "migrations/",
    "alembic/versions/",
)


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

    current_path: str | None = None
    new_line = 0
    hunk_end = 0
    is_new_file = False

    for raw_line in diff_text.splitlines():
        file_match = _DIFF_FILE_RE.match(raw_line)
        if file_match:
            current_path = file_match.group(2)
            is_new_file = False
            continue

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
    current_path: str | None = None
    new_line = 0

    for raw_line in diff_text.splitlines():
        file_match = _DIFF_FILE_RE.match(raw_line)
        if file_match:
            current_path = file_match.group(2)
            continue

        if current_path is None:
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match:
            new_line = int(hunk_match.group(1))
            continue

        if raw_line.startswith(("--- ", "+++ ")):
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
