"""Change-impact extraction from a diff - declaration-level reference leads.

Given a formatted PR diff and the checked-out files, produces a structured
artifact (``impactPath``) listing every declaration the diff *actually touches*
(within hunk ranges), grouped by language, with cross-file references.
Default off behind ``analyzers.impact``.

Declaration nodes are extracted through the shipped ``ast-grep`` catalog entry
(``analyzers/catalog/ast-grep.yaml``) rather than hand-rolled regexes, using the
kind-based rules in ``analyzers/catalog/impact-declarations/``. Any extraction
failure (subprocess error, timeout, unexpected exit) suppresses the whole
artifact instead of publishing a partial result — a partial ``impactPath`` with
silently-empty references would read as "no other usages" when the truth is
"we couldn't check".

Design decisions documented at
``.ignorelocal/waves/evidence/s6-design-decisions.md``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, cast

from loguru import logger

_CATALOG_DECL_DIR = Path(__file__).resolve().parent / "catalog" / "impact-declarations"

# extension -> (friendly language label, ast-grep rule file under _CATALOG_DECL_DIR)
_EXTENSION_RULES: dict[str, tuple[str, str]] = {
    ".py": ("Python", "python.yml"),
    ".js": ("JavaScript/TypeScript", "javascript.yml"),
    ".ts": ("JavaScript/TypeScript", "typescript.yml"),
    ".tsx": ("JavaScript/TypeScript", "tsx.yml"),
    ".go": ("Go", "go.yml"),
    ".java": ("Java", "java.yml"),
    ".rs": ("Rust", "rust.yml"),
    ".c": ("C/C++", "c.yml"),
    ".h": ("C/C++", "c.yml"),
    ".cpp": ("C/C++", "cpp.yml"),
    ".hpp": ("C/C++", "cpp.yml"),
    ".cc": ("C/C++", "cpp.yml"),
    ".cxx": ("C/C++", "cpp.yml"),
}

_DIFF_FILE_RE = re.compile(r"^diff --git a/(?P<path>.+?) b/(?P<to>.+)$", re.MULTILINE)
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


_MAX_DECLARATIONS: int = 24
_MAX_REFS: int = 8


class _ExtractionFailed(RuntimeError):
    """Internal signal: a subprocess call failed outright (not just "no matches")."""


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


def _run_ast_grep(
    binary: str,
    rule_path: Path,
    files: list[str],
    cwd: str,
) -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            [binary, "scan", "--json", "-r", str(rule_path), *files],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        msg = f"ast-grep invocation failed ({rule_path.name}): {exc}"
        raise _ExtractionFailed(msg) from exc
    if result.returncode != 0:
        msg = f"ast-grep exited {result.returncode} ({rule_path.name}): {result.stderr.strip()}"
        raise _ExtractionFailed(msg)
    try:
        matches = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        msg = f"ast-grep produced unparsable output ({rule_path.name}): {exc}"
        raise _ExtractionFailed(msg) from exc
    return cast("list[dict[str, Any]]", matches)


def _find_declarations_batch(
    paths: list[str],
    cwd: str,
    ast_grep_binary: str,
) -> dict[str, list[dict[str, object]]]:
    """Extract declaration-node candidates for every path, grouped by ast-grep rule.

    Raises ``_ExtractionFailed`` if any batch's ast-grep invocation fails outright.
    A path that does not exist on disk (deleted file, etc.) is skipped, not a failure.
    """
    groups: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for fp in paths:
        if not os.path.isfile(os.path.join(cwd, fp)):
            continue
        rule = _EXTENSION_RULES.get(_extension(fp))
        if rule is None:
            continue
        label, rule_name = rule
        groups.setdefault(rule_name, []).append(fp)
        labels[rule_name] = label

    results: dict[str, list[dict[str, object]]] = {fp: [] for fp in paths}
    for rule_name, files in groups.items():
        rule_path = _CATALOG_DECL_DIR / rule_name
        matches = _run_ast_grep(ast_grep_binary, rule_path, files, cwd)
        label = labels[rule_name]
        for m in matches:
            name_mv = m.get("metaVariables", {}).get("single", {}).get("NAME")
            name = name_mv.get("text") if name_mv else None
            file_field = m.get("file")
            if not name or file_field not in results:
                continue
            line = int(m["range"]["start"]["line"]) + 1
            results[file_field].append({"name": name, "language": label, "line": line})
    return results


def _find_references(
    symbol: str,
    cwd: str,
    *,
    exclude_file: str | None = None,
    max_refs: int = _MAX_REFS,
) -> tuple[list[dict[str, object]], bool]:
    """Return (capped references, whether more references existed than the cap)."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "grep", "-nw", "-F", "--no-color", "-e", symbol],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        msg = f"git grep failed for {symbol!r}: {exc}"
        raise _ExtractionFailed(msg) from exc
    if result.returncode not in {0, 1}:
        msg = f"git grep exited {result.returncode} for {symbol!r}: {result.stderr.strip()}"
        raise _ExtractionFailed(msg)
    refs: list[dict[str, object]] = []
    total = 0
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
        total += 1
        if len(refs) < max_refs:
            refs.append({"file": ref_file, "line": ref_line})
    return refs, total > max_refs


def extract_impact(
    diff_text: str,
    cwd: str,
    *,
    ast_grep_binary: str = "ast-grep",
) -> dict[str, object] | None:
    """Extract the change-impact artifact, or ``None`` if extraction failed outright.

    ``None`` means "we could not reliably determine this" — the caller must omit
    the artifact entirely rather than publish a partial/misleading one.
    """
    hunks = _parse_hunks(diff_text)
    relevant_files = [fp for fp in _changed_paths(diff_text) if fp in hunks]
    if not relevant_files:
        return {"impactPath": [], "truncated": False, "totalDeclarations": 0}

    try:
        decls_by_file = _find_declarations_batch(relevant_files, cwd, ast_grep_binary)

        candidates: list[dict[str, object]] = []
        for fp in relevant_files:
            file_hunks = hunks[fp]
            for d in decls_by_file.get(fp, []):
                line_val = d["line"]
                assert isinstance(line_val, int)
                if not _intersects_hunks(line_val, file_hunks):
                    continue
                candidates.append(
                    {"file": fp, "name": d["name"], "language": d["language"], "line": d["line"]}
                )

        total = len(candidates)
        candidates.sort(key=lambda r: (r["language"], r["file"], r["line"]))
        capped = candidates[:_MAX_DECLARATIONS]

        rows: list[dict[str, object]] = []
        for c in capped:
            name_val = c["name"]
            assert isinstance(name_val, str)
            fp_val = c["file"]
            assert isinstance(fp_val, str)
            refs, refs_truncated = _find_references(name_val, cwd, exclude_file=fp_val)
            rows.append(
                {
                    "file": c["file"],
                    "declaration": c["name"],
                    "language": c["language"],
                    "line": c["line"],
                    "references": refs,
                    "referencesTruncated": refs_truncated,
                }
            )
    except _ExtractionFailed as exc:
        logger.info("impact extraction failed, suppressing artifact: {}", exc)
        return None

    return {
        "impactPath": rows,
        "truncated": total > _MAX_DECLARATIONS,
        "totalDeclarations": total,
    }


def write_impact(
    diff_text: str,
    cwd: str,
    tmpdir: str,
    pull_number: int | str,
    *,
    ast_grep_binary: str = "ast-grep",
) -> dict[str, object] | None:
    data = extract_impact(diff_text, cwd, ast_grep_binary=ast_grep_binary)
    if data is None:
        return None
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


def resolve_ast_grep_binary(repo_root: Path) -> str | None:
    """Resolve the pinned, managed ``ast-grep`` binary (D10) for impact extraction.

    Returns ``None`` when it cannot be resolved (unsupported platform, network
    unavailable, checksum mismatch) — callers should skip emitting ``impactPath``
    rather than fall back to an unpinned binary found on ``PATH``.
    """
    from mergecraft.analyzers.execution import provision_platform_key
    from mergecraft.analyzers.provision import (
        ProvisionError,
        resolve_baked_binary,
        resolve_with_lock,
    )
    from mergecraft.analyzers.registry import get_manifest

    manifest = get_manifest("ast-grep")
    baked = resolve_baked_binary(manifest)
    if baked is not None:
        return str(baked)

    cache_dir = repo_root / ".mergecraft" / "analyzer-cache"
    lock_path = repo_root / ".mergecraft" / "analyzers.lock"
    try:
        result = resolve_with_lock(
            manifest=manifest,
            lock_path=lock_path,
            cache_dir=cache_dir,
            platform=provision_platform_key(),
        )
    except ProvisionError as exc:
        logger.info("impact: could not resolve managed ast-grep binary: {}", exc)
        return None
    return str(result.resolved_path)
