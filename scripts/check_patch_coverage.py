#!/usr/bin/env python3
"""Patch coverage gate: changed ``src/`` lines must be covered by the unit run.

The global floor and the delta gate say how much of the *whole* tree is covered.
Neither notices a PR that adds a several-hundred-line module nobody exercises, as
long as the rest of the tree stays above the floor (audit TST-F4). This gate reads
the unified diff against the merge base and the combined ``coverage.json`` the
coverage gate already produced, and fails when fewer than ``--threshold`` percent of
the *executable* lines the diff added or changed were executed.

Only lines coverage.py considers executable count (blank lines, comments, docstring
bodies and ``# pragma: no cover`` blocks are not in ``executed_lines`` or
``missing_lines``). A diff with no executable ``src/`` lines passes.

Usage:
    python3 scripts/check_patch_coverage.py coverage.json --base origin/main
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

DEFAULT_THRESHOLD_PCT = 80.0
DEFAULT_PREFIX = "src/mergecraft/"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_EPS = 1e-9


class PatchCoverage(NamedTuple):
    """Executable changed lines, and how many of them ran."""

    executable: int
    covered: int
    uncovered: dict[str, list[int]]

    @property
    def percent(self) -> float:
        """Percent of executable changed lines that were executed (100 when none)."""
        if self.executable == 0:
            return 100.0
        return 100.0 * self.covered / self.executable


def parse_changed_lines(diff: str, *, prefix: str = DEFAULT_PREFIX) -> dict[str, set[int]]:
    """Map each added or changed file under ``prefix`` to its new-side line numbers.

    ``diff`` is ``git diff --unified=0`` output. Deleted files and pure deletions
    contribute nothing.
    """
    changed: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target == "/dev/null":
                current = None
            else:
                name = target.removeprefix("b/")
                current = name if name.startswith(prefix) and name.endswith(".py") else None
            continue
        if current is None:
            continue
        match = _HUNK.match(line)
        if match is None:
            continue
        start = int(match.group(1))
        count = 1 if match.group(2) is None else int(match.group(2))
        if count:
            changed.setdefault(current, set()).update(range(start, start + count))
    return changed


def _report_entry(files: Mapping[str, Any], path: str) -> Mapping[str, Any] | None:
    """Find ``path`` in a coverage report whose keys may carry a different root."""
    if path in files:
        return files[path]  # type: ignore[no-any-return]
    tail = path.removeprefix("src/")
    for key, value in files.items():
        normalized = key.replace("\\", "/")
        if normalized.endswith("/" + tail) or normalized == tail:
            return value  # type: ignore[no-any-return]
    return None


def evaluate(changed: Mapping[str, set[int]], report: Mapping[str, Any]) -> PatchCoverage:
    """Intersect changed lines with the report's executed and missing lines."""
    files: Mapping[str, Any] = report.get("files", {})
    executable = 0
    covered = 0
    uncovered: dict[str, list[int]] = {}
    for path in sorted(changed):
        entry = _report_entry(files, path)
        if entry is None:
            # A new module the unit run never imported has no report entry. Every
            # changed line in it is unexecuted, but only count the ones coverage
            # would have treated as code: without the entry that is unknowable, so
            # fall back to every added line and let the author see the file named.
            lines = sorted(changed[path])
            executable += len(lines)
            uncovered[path] = lines
            continue
        executed = set(entry.get("executed_lines", ()))
        missing = set(entry.get("missing_lines", ()))
        touched = changed[path]
        hit = touched & executed
        miss = touched & missing
        executable += len(hit) + len(miss)
        covered += len(hit)
        if miss:
            uncovered[path] = sorted(miss)
    return PatchCoverage(executable, covered, uncovered)


def _ranges(lines: Sequence[int]) -> str:
    """Render ``[3, 4, 5, 9]`` as ``3-5, 9``."""
    out: list[str] = []
    start = prev = None
    for number in lines:
        if start is None:
            start = prev = number
        elif number == (prev or 0) + 1:
            prev = number
        else:
            out.append(str(start) if start == prev else f"{start}-{prev}")
            start = prev = number
    if start is not None:
        out.append(str(start) if start == prev else f"{start}-{prev}")
    return ", ".join(out)


def _git_diff(base: str, prefix: str) -> str:
    merge_base = subprocess.run(
        ["git", "merge-base", base, "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    anchor = merge_base.stdout.strip() if merge_base.returncode == 0 else base
    result = subprocess.run(
        [
            "git",
            "diff",
            "--unified=0",
            "--no-color",
            "--diff-filter=AM",
            anchor,
            "HEAD",
            "--",
            prefix,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = f"git diff against {anchor} failed: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout


def _summary_lines(result: PatchCoverage, threshold: float) -> list[str]:
    lines = [
        "### Patch coverage",
        "",
        f"{result.covered}/{result.executable} changed executable lines covered "
        f"({result.percent:.1f}%, threshold {threshold:.0f}%).",
    ]
    for path, missing in result.uncovered.items():
        lines.append(f"- `{path}`: {_ranges(missing)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("coverage_json", nargs="?", default="coverage.json", type=Path)
    parser.add_argument("--base", required=True, help="Base ref, for example origin/main")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_PCT)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    args = parser.parse_args(argv)

    try:
        report = json.loads(args.coverage_json.read_text(encoding="utf-8"))
        changed = parse_changed_lines(_git_diff(args.base, args.prefix), prefix=args.prefix)
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"patch coverage error: {exc}", file=sys.stderr)
        return 2

    result = evaluate(changed, report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(_summary_lines(result, args.threshold)) + "\n")

    if result.executable == 0:
        print("patch coverage OK: the diff adds no executable lines under " + args.prefix)
        return 0
    message = (
        f"patch coverage {result.percent:.1f}% "
        f"({result.covered}/{result.executable} changed executable lines)"
    )
    if result.percent + _EPS < args.threshold:
        print(f"{message} is below {args.threshold:.0f}%", file=sys.stderr)
        for path, missing in result.uncovered.items():
            print(f"  {path}: uncovered lines {_ranges(missing)}", file=sys.stderr)
        print(
            "Add tests that execute the lines above, or mark genuinely unreachable "
            "code with `# pragma: no cover`.",
            file=sys.stderr,
        )
        return 1
    print(f"{message} meets {args.threshold:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
