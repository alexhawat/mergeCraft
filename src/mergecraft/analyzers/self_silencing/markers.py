"""Suppression markers added by a PR — the in-code half of self-silencing (#942).

A newly added ``# nosec``, ``# noqa``, ``// eslint-disable-next-line``, ``#[allow(..)]``
… makes the analyzer skip that line, and the resulting *absence* of a finding reads as
clean. Nothing flagged the suppression itself. This module scans **added** lines only
(markers that already existed on base are not reported) against a per-language table.

Module: mergecraft.analyzers.self_silencing.markers
Depends: mergecraft.analyzers.scope, mergecraft.analyzers.finding

Exports:
    Classes:
        MarkerHit — One added suppression marker with the rule codes it silences.
    Functions:
        scan_added_markers — Find added suppression markers in a unified diff.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import NamedTuple

from mergecraft.analyzers.scope import iter_diff_hunks


@dataclass(frozen=True, slots=True)
class MarkerHit:
    """One added suppression marker."""

    path: str
    line: int
    marker: str
    codes: tuple[str, ...]
    security: bool
    text: str


class _Rule(NamedTuple):
    name: str
    pattern: re.Pattern[str]
    security: bool = False


_PROSE_SUFFIXES = frozenset({".md", ".mdx", ".rst", ".txt", ".adoc"})

_PY = frozenset({".py", ".pyi"})
_JS = frozenset({".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"})
_RUST = frozenset({".rs"})
_GO = frozenset({".go"})
_C = frozenset({".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh"})
_RUBY = frozenset({".rb"})
_JVM = frozenset({".java", ".kt", ".kts"})
_SHELL = frozenset({".sh", ".bash", ".zsh"})
_CODE = _PY | _JS | _RUST | _GO | _C | _RUBY | _JVM | _SHELL | frozenset({".php", ".cs", ".swift"})

_LANGUAGE_RULES: tuple[tuple[frozenset[str], tuple[_Rule, ...]], ...] = (
    (
        _PY,
        (
            _Rule("noqa", re.compile(r"#\s*noqa\b(?::\s*(?P<codes>[A-Za-z0-9, ]+))?", re.I)),
            _Rule(
                "type: ignore",
                re.compile(r"#\s*type:\s*ignore(?:\[(?P<codes>[^\]]*)\])?"),
            ),
            _Rule(
                "pylint: disable",
                re.compile(r"#\s*pylint:\s*disable(?:-next)?\s*=\s*(?P<codes>[\w\-, ]+)"),
            ),
        ),
    ),
    (
        _JS,
        (
            _Rule(
                "eslint-disable",
                re.compile(
                    r"(?://|/\*)\s*eslint-disable(?P<kind>-next-line|-line)?"
                    r"(?:\s+(?P<codes>[\w@/\-, ]+?))?\s*(?:\*/|$)"
                ),
            ),
            _Rule("@ts-ignore", re.compile(r"//\s*@ts-ignore\b")),
            _Rule("@ts-expect-error", re.compile(r"//\s*@ts-expect-error\b")),
            _Rule("@ts-nocheck", re.compile(r"//\s*@ts-nocheck\b")),
        ),
    ),
    (_RUST, (_Rule("allow", re.compile(r"#!?\[allow\((?P<codes>[^)]*)\)\]")),)),
    (
        _GO,
        (_Rule("nolint", re.compile(r"//\s*nolint\b(?::(?P<codes>[\w,\-]+))?")),),
    ),
    (
        _C,
        (
            _Rule(
                "NOLINT",
                re.compile(r"//\s*NOLINT(?:NEXTLINE|BEGIN)?(?:\((?P<codes>[^)]*)\))?"),
            ),
        ),
    ),
    (
        _RUBY,
        (_Rule("rubocop:disable", re.compile(r"#\s*rubocop:disable\s+(?P<codes>[\w/, ]+)")),),
    ),
    (
        _JVM,
        (_Rule("SuppressWarnings", re.compile(r"@SuppressWarnings\((?P<codes>[^)]*)\)")),),
    ),
    (
        _SHELL,
        (
            _Rule(
                "shellcheck disable",
                re.compile(r"#\s*shellcheck\s+disable=(?P<codes>[\w,]+)"),
            ),
        ),
    ),
)

# Markers any code file can carry. ``nosec`` and ``nosemgrep`` silence a security
# scanner; the secret-scanner markers live in ``_SECRET_SCANNER_RULES`` because,
# unlike these, they apply to every file.
_GENERIC_RULES: tuple[_Rule, ...] = (
    _Rule("nosec", re.compile(r"(?:#|//)\s*#?\s*nosec\b(?P<codes>[^\n]*)"), security=True),
    _Rule(
        "nosemgrep",
        re.compile(r"(?:#|//)\s*nosemgrep(?::\s*(?P<codes>[\w.\-, ]+))?"),
        security=True,
    ),
    _Rule(
        "codeql",
        re.compile(r"(?:codeql|lgtm)\[(?P<codes>[^\]]*)\]"),
        security=True,
    ),
    _Rule("NOSONAR", re.compile(r"\bNOSONAR\b")),
)

# Secret scanners honour their own line markers in *any* file: a
# ``<!-- trufflehog:ignore -->`` in a Markdown example silences a finding exactly
# as ``# gitleaks:allow`` does in code (#1008). Prose suffixes and unknown
# extensions get these and nothing else — ``# noqa`` in a document is not a
# suppression.
_SECRET_SCANNER_RULES: tuple[_Rule, ...] = (
    _Rule("gitleaks:allow", re.compile(r"gitleaks:allow\b"), security=True),
    _Rule("trufflehog:ignore", re.compile(r"trufflehog:ignore\b"), security=True),
)

_CODE_TOKEN = re.compile(r"[A-Za-z][\w:/.\-]*\d[\w]*|[\w:/.\-]+")
_SECURITY_CODE_HINTS = ("gosec", "bandit", "security/", "security.", "semgrep", "sonar")
_RUFF_SECURITY = re.compile(r"^S\d+$")


def _split_codes(raw: str | None, *, marker: str) -> tuple[str, ...]:
    if not raw:
        return ()
    cleaned = raw.replace('"', " ").replace("'", " ").replace("{", " ").replace("}", " ")
    if marker == "nosec":
        # ``# nosec B603 -- reviewed``: codes are the bandit ids, not the trailing prose.
        return tuple(dict.fromkeys(re.findall(r"\b[A-Z]{1,3}\d{2,4}\b", cleaned)))
    parts = [part.strip() for part in re.split(r"[,\s]+", cleaned) if part.strip()]
    return tuple(dict.fromkeys(part for part in parts if _CODE_TOKEN.fullmatch(part)))


def _is_security(rule: _Rule, codes: tuple[str, ...]) -> bool:
    if rule.security:
        return True
    lowered = [code.casefold() for code in codes]
    if any(hint in code for code in lowered for hint in _SECURITY_CODE_HINTS):
        return True
    return any(_RUFF_SECURITY.match(code) for code in codes)


def _rules_for(path: str) -> tuple[_Rule, ...]:
    suffix = PurePosixPath(path).suffix.casefold()
    if suffix in _PROSE_SUFFIXES or suffix not in _CODE:
        return _SECRET_SCANNER_RULES
    rules: list[_Rule] = []
    for suffixes, language_rules in _LANGUAGE_RULES:
        if suffix in suffixes:
            rules.extend(language_rules)
    rules.extend(_GENERIC_RULES)
    rules.extend(_SECRET_SCANNER_RULES)
    return tuple(rules)


def _markers_in(path: str, text: str) -> list[tuple[str, tuple[str, ...], bool]]:
    found: list[tuple[str, tuple[str, ...], bool]] = []
    for rule in _rules_for(path):
        match = rule.pattern.search(text)
        if match is None:
            continue
        groups = match.groupdict()
        name = rule.name + (groups.get("kind") or "")
        codes = _split_codes(groups.get("codes"), marker=rule.name)
        found.append((name, codes, _is_security(rule, codes)))
    return found


def scan_added_markers(diff_text: str) -> list[MarkerHit]:
    """Return suppression markers on *added* lines that were not already on base.

    A marker counts as pre-existing when the same file's removed lines carry the same
    marker with the same silenced codes — an edit to a line that keeps its ``# noqa``
    is not a new suppression. Removed and context lines never produce a hit.
    """
    hits: list[MarkerHit] = []
    for hunk in iter_diff_hunks(diff_text):
        removed: Counter[tuple[str, tuple[str, ...]]] = Counter()
        for line in hunk.lines:
            if line.startswith("-"):
                for name, codes, _security in _markers_in(hunk.path, line[1:]):
                    removed[(name, tuple(sorted(codes)))] += 1
        new_line = hunk.new_start
        for line in hunk.lines:
            prefix = line[:1]
            if prefix == "-":
                continue
            if prefix == "+":
                for name, codes, security in _markers_in(hunk.path, line[1:]):
                    signature = (name, tuple(sorted(codes)))
                    if removed[signature] > 0:
                        removed[signature] -= 1
                        continue
                    hits.append(
                        MarkerHit(
                            path=hunk.path,
                            line=new_line,
                            marker=name,
                            codes=codes,
                            security=security,
                            text=line[1:].strip(),
                        )
                    )
            new_line += 1
    return hits


__all__ = ["MarkerHit", "scan_added_markers"]
