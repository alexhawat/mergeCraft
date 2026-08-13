"""Change-impact extraction from a diff - declaration-level reference leads.

Given a formatted PR diff and the checked-out files, produces a structured
artifact (``impactPath``) listing every declaration the diff *actually touches*
(within hunk ranges), grouped by language, with cross-file references.
Default off behind ``analyzers.impact``.

Design decisions documented at
``.ignorelocal/waves/evidence/s6-design-decisions.md``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

_LANG_PATTERNS: dict[str, dict[str, list[re.Pattern[str]]]] = {
    "Python": {
        ".py": [
            re.compile(r"^def\s+(?P<name>[a-zA-Z_]\w*)\s*\(", re.MULTILINE),
            re.compile(r"^class\s+(?P<name>[a-zA-Z_]\w*)\s*[(:]", re.MULTILINE),
        ],
    },
    "JavaScript/TypeScript": {
        ".js": [
            re.compile(r"^function\s+(?P<name>[a-zA-Z_$\w]+)", re.MULTILINE),
            re.compile(
                r"^(?:export\s+)?(?:async\s+)?function\s+(?P<name>[a-zA-Z_$\w]+)", re.MULTILINE
            ),
            re.compile(r"^class\s+(?P<name>[a-zA-Z_$\w]+)", re.MULTILINE),
            re.compile(
                r"^(?:export\s+)?(?:const|let|var)\s+(?P<name>[a-zA-Z_$\w]+)\s*[=(:]", re.MULTILINE
            ),
        ],
        ".ts": [
            re.compile(r"^function\s+(?P<name>[a-zA-Z_$\w]+)", re.MULTILINE),
            re.compile(
                r"^(?:export\s+)?(?:async\s+)?function\s+(?P<name>[a-zA-Z_$\w]+)", re.MULTILINE
            ),
            re.compile(r"^class\s+(?P<name>[a-zA-Z_$\w]+)", re.MULTILINE),
            re.compile(r"^interface\s+(?P<name>[a-zA-Z_$\w]+)", re.MULTILINE),
            re.compile(r"^type\s+(?P<name>[a-zA-Z_$\w]+)\s*=", re.MULTILINE),
            re.compile(
                r"^(?:export\s+)?(?:const|let|var)\s+(?P<name>[a-zA-Z_$\w]+)\s*[=(:)]", re.MULTILINE
            ),
            re.compile(r"^enum\s+(?P<name>[a-zA-Z_$\w]+)", re.MULTILINE),
        ],
    },
    "Go": {
        ".go": [
            re.compile(r"^func\s+(?P<name>[a-zA-Z_]\w+)\s*\(", re.MULTILINE),
            re.compile(r"^type\s+(?P<name>[a-zA-Z_]\w+)\s+(?:struct|interface)\b", re.MULTILINE),
        ],
    },
    "Java": {
        ".java": [
            re.compile(r"^(?:\w+\s+)*class\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE),
            re.compile(r"^(?:\w+\s+)*interface\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE),
            re.compile(r"^(?:\w+\s+)*\w+\s+(?P<name>[a-z_]\w*)\s*\(", re.MULTILINE),
            re.compile(r"^enum\s+(?P<name>[A-Za-z_]\w*)", re.MULTILINE),
        ],
    },
    "Rust": {
        ".rs": [
            re.compile(r"^fn\s+(?P<name>[a-zA-Z_]\w+)\s*\(", re.MULTILINE),
            re.compile(
                r"^(?:pub\s+)?(?:struct|trait|enum|union)\s+(?P<name>[a-zA-Z_]\w+)", re.MULTILINE
            ),
            re.compile(
                r"^(?:pub\s+)?(?:async\s+|unsafe\s+)?fn\s+(?P<name>[a-zA-Z_]\w+)", re.MULTILINE
            ),
            re.compile(r"^macro_rules!\s+(?P<name>[a-zA-Z_]\w+)", re.MULTILINE),
        ],
    },
    "C/C++": {
        ".c": [re.compile(r"^(?:\w+\s+)+\s*(?P<name>[a-zA-Z_]\w*)\s*\(", re.MULTILINE)],
        ".h": [
            re.compile(r"^(?:\w+\s+)+\s*(?P<name>[a-zA-Z_]\w*)\s*\(", re.MULTILINE),
            re.compile(
                r"^(?:typedef\s+)?(?:struct|union|enum)\s+(?P<name>[a-zA-Z_]\w*)", re.MULTILINE
            ),
        ],
        ".cpp": [
            re.compile(r"^(?:\w+\s+)+\s*(?P<name>[a-zA-Z_]\w*)\s*\(", re.MULTILINE),
            re.compile(r"^class\s+(?P<name>[a-zA-Z_]\w*)", re.MULTILINE),
        ],
        ".hpp": [
            re.compile(r"^(?:\w+\s+)+\s*(?P<name>[a-zA-Z_]\w*)\s*\(", re.MULTILINE),
            re.compile(r"^class\s+(?P<name>[a-zA-Z_]\w*)", re.MULTILINE),
        ],
        ".cc": [
            re.compile(r"^(?:\w+\s+)+\s*(?P<name>[a-zA-Z_]\w*)\s*\(", re.MULTILINE),
            re.compile(r"^class\s+(?P<name>[a-zA-Z_]\w*)", re.MULTILINE),
        ],
        ".cxx": [re.compile(r"^(?:\w+\s+)+\s*(?P<name>[a-zA-Z_]\w*)\s*\(", re.MULTILINE)],
    },
}

_DIFF_FILE_RE = re.compile(r"^diff --git a/(?P<path>.+?) b/(?P<to>.+)$", re.MULTILINE)
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


_MAX_DECLARATIONS: int = 24
_MAX_REFS: int = 8


def _changed_paths(diff_text: str) -> list[str]:
    seen: dict[str, None] = {}
    for match in _DIFF_FILE_RE.finditer(diff_text):
        seen.setdefault(match.group("to"), None)
    return list(seen)


def _parse_hunks(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    hunks: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None
    for line in diff_text.splitlines():
        file_match = _DIFF_FILE_RE.match(line)
        if file_match:
            current_file = file_match.group("to")
            continue
        if current_file is None:
            continue
        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            start = int(hunk_match.group("start"))
            count = int(hunk_match.group("count") or "1")
            end = start + max(count, 1) - 1
            hunks.setdefault(current_file, []).append((start, end))
    return hunks


def _intersects_hunks(line_no: int, hunk_ranges: list[tuple[int, int]]) -> bool:
    return any(start <= line_no <= end for start, end in hunk_ranges)


def _extension(path: str) -> str:
    _, dot = os.path.splitext(path)
    return dot.lower()


def _find_declarations(path: str, cwd: str) -> list[dict[str, object]]:
    full = os.path.join(cwd, path)
    if not os.path.isfile(full):
        return []
    try:
        text = Path(full).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    ext = _extension(path)
    results: list[dict[str, object]] = []
    seen_names: set[str] = set()
    for lang, entries in _LANG_PATTERNS.items():
        patterns = entries.get(ext, [])
        for pat in patterns:
            for match in pat.finditer(text):
                name = match.group("name")
                if name and name not in seen_names:
                    seen_names.add(name)
                    line = text[: match.start()].count("\n") + 1
                    results.append({"name": name, "language": lang, "line": line})
    return results


def _find_references(
    symbol: str,
    cwd: str,
    *,
    exclude_file: str | None = None,
    max_refs: int = 8,
) -> list[dict[str, object]]:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "grep", "-nw", "--no-color", "-e", symbol],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError, subprocess.TimeoutExpired, OSError:
        return []
    if result.returncode not in {0, 1}:
        return []
    refs: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) < 2:
            continue
        ref_file = parts[0]
        if exclude_file and ref_file == exclude_file:
            continue
        try:
            ref_line = int(parts[1])
        except ValueError, IndexError:
            continue
        refs.append({"file": ref_file, "line": ref_line})
        if len(refs) >= max_refs:
            break
    return refs


def extract_impact(diff_text: str, cwd: str) -> dict[str, object]:
    hunks = _parse_hunks(diff_text)
    rows: list[dict[str, object]] = []
    for fp in _changed_paths(diff_text):
        file_hunks = hunks.get(fp)
        if not file_hunks:
            continue
        decls = _find_declarations(fp, cwd)
        for d in decls:
            line_val = d["line"]
            assert isinstance(line_val, int)
            if not _intersects_hunks(line_val, file_hunks):
                continue
            name_val = d["name"]
            assert isinstance(name_val, str)
            refs = _find_references(name_val, cwd, exclude_file=fp)
            rows.append(
                {
                    "file": fp,
                    "declaration": d["name"],
                    "language": d["language"],
                    "line": d["line"],
                    "references": refs,
                }
            )
    rows.sort(key=lambda r: (r["language"], r["file"], r["line"]))
    capped = rows[:_MAX_DECLARATIONS]
    return {
        "impactPath": capped,
        "truncated": len(rows) > _MAX_DECLARATIONS,
        "totalDeclarations": len(rows),
    }


def write_impact(
    diff_text: str,
    cwd: str,
    tmpdir: str,
    pull_number: int | str,
) -> dict[str, object] | None:
    data = extract_impact(diff_text, cwd)
    rows = data.get("impactPath", [])
    if not rows:
        return None
    path = str(Path(tmpdir) / f"pr-{pull_number}-impact.json")
    Path(path).write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return {
        "impactPath": path,
        "impactTruncated": data["truncated"],
        "impactDeclarationCount": data["totalDeclarations"],
    }
