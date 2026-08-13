"""Change-impact extraction from a diff — declaration-level reference leads.

Given a formatted PR diff and the checked-out files, produces a structured
artifact (``impactPath``) listing every declaration the diff touches, grouped
by language and ranked by severity. Default off behind ``analyzers.impact``.

Design decisions documented at
``.ignorelocal/waves/evidence/s6-design-decisions.md``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

# Language → extension → declaration patterns (multiline regex).
# Covers the 8 languages in the shipped ast-grep catalog (python, javascript,
# typescript, go, java, rust, c, cpp).  Patterns look for the declaration
# *headline* on its own line — class/function/interface definitions.
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
        ".c": [
            re.compile(r"^(?:\w+\s+)+\s*(?P<name>[a-zA-Z_]\w*)\s*\(", re.MULTILINE),
        ],
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
        ".cxx": [
            re.compile(r"^(?:\w+\s+)+\s*(?P<name>[a-zA-Z_]\w*)\s*\(", re.MULTILINE),
        ],
    },
}


_DIFF_FILE_RE = re.compile(r"^diff --git a/(?P<path>.+?) b/(?P<to>.+)$", re.MULTILINE)

# Q3 design cap: 24 declarations per review, 8 references per decl.
_MAX_DECLARATIONS: int = 24
_MAX_REFS: int = 8


def _changed_paths(diff_text: str) -> list[str]:
    """Return the post-image paths named by a unified diff, in first-seen order."""
    seen: dict[str, None] = {}
    for match in _DIFF_FILE_RE.finditer(diff_text):
        seen.setdefault(match.group("to"), None)
    return list(seen)


def _extension(path: str) -> str:
    _, dot = os.path.splitext(path)
    return dot.lower()


def _find_declarations(path: str, cwd: str) -> list[dict[str, object]]:
    """Extract declaration names from *path* (relative to *cwd*).

    Returns ``[{"name": str, "language": str, "line": int}, …]``
    sorted by file order. Empty when the file has no recognised extension
    or is not on disk.
    """
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
                    # Approximate line number from match position
                    line = text[: match.start()].count("\n") + 1
                    results.append({"name": name, "language": lang, "line": line})
    return results


def extract_impact(diff_text: str, cwd: str) -> dict[str, object]:
    """Extract impact data from *diff_text* and files checked out at *cwd*.

    Returns ``{"impactPath": […], "truncated": bool, "totalDeclarations": int}``.
    """
    rows: list[dict[str, object]] = []
    for fp in _changed_paths(diff_text):
        decls = _find_declarations(fp, cwd)
        for d in decls:
            rows.append(
                {
                    "file": fp,
                    "declaration": d["name"],
                    "language": d["language"],
                    "line": d["line"],
                }
            )

    # Sort: language → file → line
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
    """Write the impact-path JSON artifact to disk.

    Returns ``None`` when there are zero declarations, so the caller omits
    the ``impactPath`` key entirely (same convention as ``incrementalDiffPath``).
    """
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
