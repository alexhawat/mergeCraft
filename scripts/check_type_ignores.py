#!/usr/bin/env python3
"""Fail when ``type: ignore`` / ``cast(`` in allowed src lack a one-line reason.

Every ``type: ignore`` under ``src/mergecraft/`` (except morning-plan D6
files) must be ``type: ignore[<code>]`` with a following em-dash (U+2014)
reason on the same line. Every ``cast(`` call needs a ``#`` reason on the
same line or the previous line. D6 files are counted then ignored.

This ratchet exits 1 while allowed-tree sites lack a reason (W8 RED).
W9 justifies or removes those sites.

Module: scripts.check_type_ignores
Depends: argparse, pathlib, re, sys, typing

Exports:
    D6_SRC_PATHS — morning-plan src files excluded from the fail condition.
    is_d6_src — True when a repo-relative path is a D6 src file.
    scan_tree — inventory ``type: ignore`` and ``cast(`` sites.
    check_type_ignores — return 0 iff allowed-tree unjustified count is 0.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple, TextIO

REPO = Path(__file__).resolve().parents[1]
MERGECRAFT_SRC = Path("src") / "mergecraft"

# Morning-plan src files this program must not audit (D6). Inventory may
# still count them; they do not fail the gate.
D6_SRC_PATHS: frozenset[str] = frozenset(
    {
        "src/mergecraft/agents/_stream_consumer.py",
        "src/mergecraft/agents/codex.py",
        "src/mergecraft/agents/ensemble.py",
        "src/mergecraft/agents/structured_handoff.py",
        "src/mergecraft/analyzers/adapters.py",
        "src/mergecraft/analyzers/parsers/osv_json.py",
        "src/mergecraft/analyzers/scope.py",
        "src/mergecraft/cli/auth_cmd.py",
        "src/mergecraft/cli/gha_cmd.py",
        "src/mergecraft/evals/live_run.py",
        "src/mergecraft/mcp/check_runs.py",
        "src/mergecraft/mcp/git.py",
        "src/mergecraft/mcp/labels.py",
        "src/mergecraft/mcp/server.py",
        "src/mergecraft/mcp/upload.py",
        "src/mergecraft/mcp/verdict.py",
    }
)

_EM_DASH = "\u2014"
_TYPE_IGNORE = re.compile(r"#\s*type:\s*ignore(?P<bracket>\[(?P<code>[^\]]*)\])?(?P<rest>.*)$")
_CAST_CALL = re.compile(r"\bcast\s*\(")


class Violation(NamedTuple):
    """One unjustified ``type: ignore`` or ``cast(`` site."""

    path: str
    line_no: int
    kind: str
    detail: str

    @property
    def d6(self) -> bool:
        """Return True when this site is on a D6-forbidden src path."""
        return is_d6_src(self.path)


class TypeIgnoreInventory(NamedTuple):
    """Scanned ignore/cast sites plus D6 / allowed splits."""

    violations: tuple[Violation, ...]
    ignore_count: int
    cast_count: int
    d6_ignore_count: int
    d6_cast_count: int

    @property
    def total_violations(self) -> int:
        """Return the number of unjustified sites including D6."""
        return len(self.violations)

    @property
    def d6_violations(self) -> tuple[Violation, ...]:
        """Return unjustified sites on D6 paths (counted, not failing)."""
        return tuple(item for item in self.violations if item.d6)

    @property
    def allowed_violations(self) -> tuple[Violation, ...]:
        """Return unjustified sites this program must fix (W9)."""
        return tuple(item for item in self.violations if not item.d6)

    @property
    def d6_count(self) -> int:
        """Return the D6-excluded unjustified count."""
        return len(self.d6_violations)

    @property
    def allowed_count(self) -> int:
        """Return the allowed-tree unjustified count (the fail condition)."""
        return len(self.allowed_violations)

    @property
    def allowed_ignore_count(self) -> int:
        """Return allowed-tree ignore sites (justified or not)."""
        return self.ignore_count - self.d6_ignore_count

    @property
    def allowed_cast_count(self) -> int:
        """Return allowed-tree cast sites (justified or not)."""
        return self.cast_count - self.d6_cast_count


def is_d6_src(rel_path: str) -> bool:
    """Return True when ``rel_path`` is a D6-forbidden src file.

    Args:
        rel_path: Repo-relative posix path.

    Returns:
        True when the path is in ``D6_SRC_PATHS``.
    """
    return rel_path.replace("\\", "/") in D6_SRC_PATHS


def _rel(repo_root: Path, path: Path) -> str:
    """Return repo-relative posix path for ``path``."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _code_before_comment(line: str) -> str:
    """Return the code portion of ``line`` (before a ``#`` comment)."""
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return ""
    if "#" not in line:
        return line
    return line.split("#", 1)[0]


def _inline_or_full_line_comment(line: str) -> str:
    """Return the ``#`` comment body of ``line``, or empty if none."""
    stripped = line.strip()
    if stripped.startswith("#"):
        return stripped[1:].strip()
    if "#" not in line:
        return ""
    return line.split("#", 1)[1].strip()


def _has_hash_reason(line: str) -> bool:
    """Return True when ``line`` carries a non-empty ``#`` comment body."""
    return _inline_or_full_line_comment(line) != ""


def _ignore_detail(match: re.Match[str]) -> str | None:
    """Return a violation detail for a ``type: ignore``, or None if justified."""
    code = (match.group("code") or "").strip()
    if match.group("bracket") is None or not code:
        return "missing error code"
    rest = match.group("rest") or ""
    if _EM_DASH not in rest:
        return f"missing {_EM_DASH} reason"
    if rest.split(_EM_DASH, 1)[1].strip() == "":
        return f"missing {_EM_DASH} reason"
    return None


def _scan_lines(rel_path: str, lines: list[str]) -> tuple[list[Violation], int, int]:
    """Scan ``lines`` of one file. Return (violations, ignore_count, cast_count)."""
    violations: list[Violation] = []
    ignore_count = 0
    cast_count = 0
    for line_no, line in enumerate(lines, start=1):
        ignore_match = _TYPE_IGNORE.search(line)
        if ignore_match is not None:
            ignore_count += 1
            detail = _ignore_detail(ignore_match)
            if detail is not None:
                violations.append(
                    Violation(
                        path=rel_path,
                        line_no=line_no,
                        kind="ignore",
                        detail=detail,
                    )
                )
        if _CAST_CALL.search(_code_before_comment(line)):
            cast_count += 1
            previous = lines[line_no - 2] if line_no > 1 else ""
            if not _has_hash_reason(line) and not _has_hash_reason(previous):
                violations.append(
                    Violation(
                        path=rel_path,
                        line_no=line_no,
                        kind="cast",
                        detail="missing # reason",
                    )
                )
    return violations, ignore_count, cast_count


def scan_tree(repo_root: Path) -> TypeIgnoreInventory:
    """Inventory ``type: ignore`` and ``cast(`` sites under ``src/mergecraft/``.

    Args:
        repo_root: Repository root containing ``src/mergecraft/``.

    Returns:
        Inventory of sites and unjustified violations, D6-tagged.

    Raises:
        FileNotFoundError: When ``src/mergecraft`` is missing.
        OSError: When a source file cannot be read.
    """
    src = repo_root / MERGECRAFT_SRC
    if not src.is_dir():
        msg = f"missing source tree: {src}"
        raise FileNotFoundError(msg)

    violations: list[Violation] = []
    ignore_count = 0
    cast_count = 0
    d6_ignore_count = 0
    d6_cast_count = 0
    for path in sorted(src.rglob("*.py")):
        rel_path = _rel(repo_root, path)
        text = path.read_text(encoding="utf-8")
        file_violations, file_ignores, file_casts = _scan_lines(rel_path, text.splitlines())
        violations.extend(file_violations)
        ignore_count += file_ignores
        cast_count += file_casts
        if is_d6_src(rel_path):
            d6_ignore_count += file_ignores
            d6_cast_count += file_casts
    return TypeIgnoreInventory(
        violations=tuple(violations),
        ignore_count=ignore_count,
        cast_count=cast_count,
        d6_ignore_count=d6_ignore_count,
        d6_cast_count=d6_cast_count,
    )


def check_type_ignores(inventory: TypeIgnoreInventory, *, stream: TextIO | None = None) -> int:
    """Return 0 when allowed-tree unjustified count is 0; 1 otherwise.

    Args:
        inventory: Scanned ignore/cast set.
        stream: Output stream (default ``sys.stderr``).

    Returns:
        Process exit code (0 ok, 1 allowed-tree unjustified sites remain).
    """
    out: TextIO = sys.stderr if stream is None else stream
    allowed = inventory.allowed_violations
    summary = (
        f"{inventory.allowed_count} allowed-tree unjustified "
        f"({inventory.ignore_count} ignores, {inventory.cast_count} casts; "
        f"{inventory.d6_count} D6-excluded violations)"
    )
    if not allowed:
        print(f"type-ignore-check OK: {summary}", file=out)
        return 0

    print(f"type-ignore-check FAILED: {summary}", file=out)
    for item in allowed:
        print(f"  {item.path}:{item.line_no} {item.kind} {item.detail}", file=out)
    return 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry: scan ``src/mergecraft/`` and ratchet missing reasons.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        0 when allowed-tree is clean; 1 when unjustified sites remain; 2 on IO error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO,
        help="Repo root containing src/mergecraft (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)

    try:
        inventory = scan_tree(Path(args.repo_root))
    except OSError as exc:
        print(f"type-ignore-check error: {exc}", file=sys.stderr)
        return 2

    return check_type_ignores(inventory)


if __name__ == "__main__":
    raise SystemExit(main())
