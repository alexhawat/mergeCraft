"""Deterministic triage tier: decide, before any LLM runs, whether a diff needs one.

The full agent review runs on every diff, however mechanical. The "genuinely trivial"
rule in the review modes is a decision the *agent* makes, so the tokens are already
spent by the time it applies. This module makes that decision deterministically, from
the unified diff and the operator's base-side config alone, before the agent exists.

Recognizers are pure functions answering one question about the **whole** diff: "is
every change in it of this kind?". There is no partial credit — a diff that mostly
matches and hides one real change matches nothing and gets a full review.

* ``pinBump`` — every changed line pair differs only in a 40-hex SHA (or a
  ``sha256:`` digest), and always by the same single old → new pair.
* ``prose`` — only ``.md`` / ``.markdown`` / ``.txt`` files, outside high-stakes
  paths, with no changed line in a code fence, front matter, or indented code. A
  dependency manifest or lockfile named like prose, and an agent-instruction file
  that steers later reviews, are never prose. Validated head text and diff hunks
  reconstruct the base: removals are checked in the old structure and additions in
  the new one. Without both sides nothing is proven.
* ``whitespace`` — reconstruct the complete base text from the head and verified
  hunks. Python must retain the same AST; a closed C-family subset must contain no
  ambiguous multiline lexical constructs. Normalized file text must also match.
  Missing context, executable-mode changes and unsupported syntax get full review.
* ``generated`` — only lockfiles or generated paths changed, and no dependency
  manifest or generator config changed with them.
* ``commentOnly`` — only ``//`` comment lines changed, in a closed list of
  ``//``-comment languages chosen by suffix (no JavaScript, JSX/TSX or Rust;
  ``Package.swift`` and Go ``_test.go`` / ``DO NOT EDIT`` files refused; a Java unicode
  escape or a C-family ``??`` refuses the file). Each
  changed line is ``//``, one space and a plain alphabetic word that is not a directive
  word; a removal must be replaced by an added line. The diff and the head text must be
  printable ASCII (plus tab and newline) and are split on ``\n`` only. A file with a
  backtick, a raw-string marker, any ``/*``, or a quote left open at the end of a line
  is refused, so every head line provably starts outside a string or comment.
  ``#``-comment languages are never recognised: a ``#`` line can be content.

Three tiers ship: ``skip`` (no LLM review), ``lite`` (one capped LLM call, see
:mod:`mergecraft.agents.lite`) and ``full`` (today's review). ``lite`` is chosen only
when the operator enabled ``review.fastPath.lite``, and only for the two cases ``skip``
deliberately leaves out: a recognizer that matches but is not opted in to ``skipLlm``,
and a pin bump whose verifying check has not passed from a trusted GitHub App. With
``lite`` off both stay ``full``.

The tier is a pure function of the diff, the config, head-side text used only to prove
a markdown edit stays out of a code fence, and the names of the checks that passed on
the head SHA from a configured trusted App (the I/O shell filters by ``app.slug``).
The pull request's title, body, labels and head-side config are not inputs: a fork
author must not be able to opt themselves out of review.

Exports:
    TriageDecision: The tier, the recognizer behind it, and why.
    TriageInputs: What the I/O layer reads for one pull request.
    triage_diff: The pure tier decision.
    recognize_pin_bump, recognize_prose_only, recognize_whitespace_only,
    recognize_generated, recognize_comment_only: The recognizers.
    COMMENT_ONLY_SUFFIXES: The closed ``//``-comment language list.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, Literal

from mergecraft.analyzers.scope import changed_paths_from_scope, parse_diff_scope
from mergecraft.classify.change_classifier import _HIGH_STAKES_PATH_PARTS
from mergecraft.classify.generated_files import FileKind, classify_path
from mergecraft.review_policy.manifest_names import (
    DEPENDENCY_MANIFEST_NAMES,
    GENERATOR_CONFIG_NAMES,
    LOCKFILE_NAMES,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

    from mergecraft.config.settings import FastPathSettings

Tier = Literal["skip", "lite", "full"]

_SHA: Final[re.Pattern[str]] = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{40}(?![0-9A-Fa-f])|sha256:[0-9A-Fa-f]{64}"
)
_FENCE: Final[re.Pattern[str]] = re.compile(r"^\s{0,3}(```|~~~)")
_PROSE_SUFFIXES: Final[tuple[str, ...]] = (".md", ".markdown", ".txt")
# A prose skip must never hide a dependency change or an instruction that steers
# later reviews: both kinds of file read as prose by suffix alone. Manifest and
# lockfile names are compared lowercased (the path is lowercased first).
_AGENT_INSTRUCTION_BASENAMES: Final[frozenset[str]] = frozenset(
    {
        "agents.md",
        "claude.md",
        "gemini.md",
        "copilot-instructions.md",
        ".cursorrules",
        ".windsurfrules",
        ".clinerules",
    }
)
_PROSE_REFUSED_BASENAMES: Final[frozenset[str]] = (
    frozenset(name.lower() for name in DEPENDENCY_MANIFEST_NAMES | LOCKFILE_NAMES)
    | _AGENT_INSTRUCTION_BASENAMES
)
_PROSE_REFUSED_PATH_PARTS: Final[tuple[str, ...]] = (
    ".github/skills/",
    ".github/instructions/",
    ".github/prompts/",
    ".github/chatmodes/",
    ".claude/",
    ".cursor/",
    ".agents/",
    ".codex/",
    "agent-instructions",
)
_MARKDOWN_SUFFIXES: Final[tuple[str, ...]] = (".md", ".markdown")


@dataclass(frozen=True, slots=True)
class TriageDecision:
    """The triage tier and the reasoning behind it.

    Attributes:
        tier: ``skip`` (no LLM review runs), ``lite`` (one capped LLM call) or
            ``full`` (today's review).
        recognizer: The recognizer behind a ``skip`` or ``lite``; ``None`` for ``full``.
        reason: Why, in one sentence.
        relied_on_checks: Checks that had to pass on the head SHA for this ``skip``.
        token_cap: The configured ``lite`` token cap on a ``lite`` decision, else ``None``.
    """

    tier: Tier
    recognizer: str | None
    reason: str
    relied_on_checks: tuple[str, ...] = field(default_factory=tuple)
    token_cap: int | None = None

    def record_line(self) -> str:
        """The line the run record and the checks show, so a skip never reads as a review."""
        if self.tier == "skip":
            return f"Tier: skip ({self.recognizer}) — no LLM review ran"
        if self.tier == "lite":
            return f"Tier: lite — single-call review, cap {self.token_cap} tokens"
        return "Tier: full"


@dataclass(frozen=True, slots=True)
class TriageInputs:
    """What the I/O layer reads for one pull request: the diff, head text, passed checks."""

    diff_text: str
    head_files: dict[str, str] = field(default_factory=dict)
    passed_checks: tuple[str, ...] = ()


# ── parsing ───────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _Hunk:
    new_start: int
    old_start: int = 0
    old_count: int = -1
    new_count: int = -1
    lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _File:
    path: str
    previous_path: str
    binary: bool = False
    metadata_changed: bool = False
    hunks: list[_Hunk] = field(default_factory=list)


def _parse(diff_text: str, *, newline_only: bool = False) -> list[_File]:
    """Parse a unified diff; ``newline_only`` splits on ``\n`` alone, never ``splitlines``."""
    files: list[_File] = []
    current: _File | None = None
    hunk: _Hunk | None = None
    raws = diff_text.split("\n") if newline_only else diff_text.splitlines()
    for raw in raws:
        if raw.startswith("diff --git "):
            previous, _, path = raw.removeprefix("diff --git a/").rpartition(" b/")
            current = _File(path=path.strip(), previous_path=previous.strip())
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        if raw.startswith(
            ("old mode ", "new mode ", "new file mode ", "deleted file mode ", "\\ No newline")
        ):
            current.metadata_changed = True
            continue
        if hunk is None:
            if raw.startswith("+++ b/"):
                current.path = raw[6:].strip()
            elif raw.startswith(("rename from ", "copy from ")):
                current.previous_path = raw.split(" from ", 1)[1].strip()
            elif raw.startswith(("Binary files ", "GIT binary patch")):
                current.binary = True
            elif raw.startswith("@@"):
                hunk = _new_hunk(raw, current)
            continue
        if raw.startswith("@@"):
            hunk = _new_hunk(raw, current)
        elif raw[:1] in {" ", "+", "-"}:
            hunk.lines.append(raw)
    return files


def _new_hunk(header: str, current: _File) -> _Hunk:
    match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header)
    hunk = (
        _Hunk(
            new_start=int(match.group(3)),
            old_start=int(match.group(1)),
            old_count=int(match.group(2) or 1),
            new_count=int(match.group(4) or 1),
        )
        if match
        else _Hunk(new_start=1)
    )
    current.hunks.append(hunk)
    return hunk


def _changeable(files: list[_File]) -> bool:
    """Every file has real hunks (no rename-only, mode-only or binary entries)."""
    return bool(files) and all(f.hunks and not f.binary for f in files)


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


# ── recognizers ───────────────────────────────────────────────────────────────


def recognize_pin_bump(diff_text: str) -> bool:
    """Every changed line pair swaps one SHA or digest for another, always the same pair."""
    files = _parse(diff_text)
    if not _changeable(files):
        return False
    pairs: set[tuple[str, str]] = set()
    for file in files:
        for hunk in file.hunks:
            removed: list[str] = []
            added: list[str] = []
            for line in hunk.lines:
                if line[0] == "-":
                    removed.append(line[1:])
                elif line[0] == "+":
                    added.append(line[1:])
            if len(removed) != len(added) or not removed:
                return False
            for old, new in zip(removed, added, strict=True):
                old_tokens, new_tokens = _SHA.findall(old), _SHA.findall(new)
                if not old_tokens or len(old_tokens) != len(new_tokens):
                    return False
                if _SHA.sub("\0", old) != _SHA.sub("\0", new):
                    return False
                changed = [
                    (a.lower(), b.lower())
                    for a, b in zip(old_tokens, new_tokens, strict=True)
                    if a.lower() != b.lower()
                ]
                if not changed:
                    return False
                pairs.update(changed)
    return len(pairs) == 1


def _inside_code_before(lines: list[str]) -> list[bool]:
    """``inside[n]`` — whether new-side line ``n`` (1-based) starts inside a code fence."""
    inside = [False, False]
    in_fence = False
    marker = ""
    for line in lines:
        match = _FENCE.match(line)
        if match:
            if not in_fence:
                in_fence, marker = True, match.group(1)
            elif match.group(1) == marker:
                in_fence = False
        inside.append(in_fence)
    return inside


def _front_matter_end(lines: list[str]) -> int:
    """Last 1-based line of YAML front matter, or ``0`` when the file has none."""
    if not lines or lines[0].strip() != "---":
        return 0
    for index, line in enumerate(lines[1:], start=2):
        if line.strip() in {"---", "..."}:
            return index
    return len(lines)


def _prose_file_ok(file: _File, head_text: str) -> bool:
    if not any(
        path.lower().endswith(_MARKDOWN_SUFFIXES) for path in (file.previous_path, file.path)
    ):
        return True  # plain text: no fences, no front matter
    before_text = _reconstruct_before(file, head_text)
    if before_text is None:
        return False
    old_lines, new_lines = before_text.split("\n"), head_text.split("\n")
    old_inside, new_inside = _inside_code_before(old_lines), _inside_code_before(new_lines)
    old_front_matter, new_front_matter = _front_matter_end(old_lines), _front_matter_end(new_lines)
    for hunk in file.hunks:
        old_position, new_position = hunk.old_start, hunk.new_start
        for line in hunk.lines:
            kind, text = line[0], line[1:]
            if kind == " ":
                old_position += 1
                new_position += 1
                continue
            if _FENCE.match(text) or text.startswith(("    ", "\t")):
                return False
            if kind == "-":
                position, front_matter, inside = old_position, old_front_matter, old_inside
                old_position += 1
            else:
                position, front_matter, inside = new_position, new_front_matter, new_inside
                new_position += 1
            if position <= front_matter or (position < len(inside) and inside[position]):
                return False
    return True


def recognize_prose_only(diff_text: str, *, head_files: Mapping[str, str]) -> bool:
    """Only prose files changed, and no changed line sits in code, a fence or front matter."""
    files = _parse(diff_text)
    if not _changeable(files):
        return False
    for file in files:
        for path in (file.previous_path, file.path):
            lowered = path.lower()
            if not lowered.endswith(_PROSE_SUFFIXES):
                return False
            if any(part in lowered for part in _HIGH_STAKES_PATH_PARTS):
                return False
            if PurePosixPath(lowered).name in _PROSE_REFUSED_BASENAMES:
                return False
            if any(part in lowered for part in _PROSE_REFUSED_PATH_PARTS):
                return False
        head_text = head_files.get(file.path)
        if head_text is None:
            return False
        if not _prose_file_ok(file, head_text):
            return False
    return True


def _blocks(hunk: _Hunk) -> list[tuple[list[str], list[str]]]:
    """Split a hunk into contiguous change blocks of ``(removed, added)`` lines."""
    blocks: list[tuple[list[str], list[str]]] = []
    removed: list[str] = []
    added: list[str] = []
    for line in hunk.lines:
        if line[0] == "-":
            removed.append(line[1:])
        elif line[0] == "+":
            added.append(line[1:])
        else:
            if removed or added:
                blocks.append((removed, added))
            removed, added = [], []
    if removed or added:
        blocks.append((removed, added))
    return blocks


def _renamed_or_copied(file: _File) -> bool:
    """A rename or copy is never a mechanical edit: the path itself carries meaning.

    ``src/foo.ts`` → ``src/foo.d.ts`` stops emitting JS, ``foo.c`` → ``foo.cpp``
    changes the compiler dialect and Go runs ``init`` in lexical filename order,
    so a renamed or copied file (``previous_path`` differs) refuses the recognizers
    that promise "no runtime change", whatever its hunks contain.
    """
    return bool(file.previous_path) and file.previous_path != file.path


def _reconstruct_before(file: _File, head_text: str) -> str | None:
    """Reverse complete, position-checked hunks against the immutable head text."""
    if file.metadata_changed or not head_text.endswith("\n") or "\r" in head_text:
        return None
    head = head_text[:-1].split("\n")
    before: list[str] = []
    cursor = 0
    for hunk in file.hunks:
        start = hunk.new_start - (hunk.new_count != 0)
        if start < cursor or start > len(head):
            return None
        before.extend(head[cursor:start])
        if len(before) != hunk.old_start - (hunk.old_count != 0):
            return None
        cursor = start
        old_count = new_count = 0
        for line in hunk.lines:
            kind, text = line[0], line[1:]
            if kind in {" ", "+"}:
                if cursor >= len(head) or head[cursor] != text:
                    return None
                cursor += 1
                new_count += 1
            if kind in {" ", "-"}:
                before.append(text)
                old_count += 1
        if (old_count, new_count) != (hunk.old_count, hunk.new_count):
            return None
    return "\n".join([*before, *head[cursor:]]) + "\n"


def _whitespace_context_safe(path: str, before: str, after: str) -> bool:
    # Shebang position and directive comments are executable/build metadata too.
    if any("#!" in text for text in (before, after)):
        return False
    if path.lower().endswith(".py"):
        try:
            return ast.dump(ast.parse(before, type_comments=True)) == ast.dump(
                ast.parse(after, type_comments=True)
            )
        except (SyntaxError, ValueError, RecursionError):
            return False
    if not path.lower().endswith((*COMMENT_ONLY_SUFFIXES, ".js")):
        return False
    text = before + after
    # No multi-line lexical constructs, preprocessing, escapes or JSX: this is a
    # deliberately small proof, not a lexer for every dialect these suffixes allow.
    if _COMMENT_ONLY_TEXT.fullmatch(text) is None:
        return False
    if any(marker in text for marker in (*_UNLEXABLE_MARKERS, "\\", "#", "??")):
        return False
    if path.lower().endswith((".js", ".ts")) and any(c in text for c in "<>"):
        return False
    if any(marker in text for marker in ("//go:", "// +build", "// swift-tools-version")):
        return False
    if [line for line in before.split("\n") if "//" in line] != [
        line for line in after.split("\n") if "//" in line
    ]:
        return False
    return _strings_close_on_every_line(text.split("\n"))


def recognize_whitespace_only(
    diff_text: str, *, head_files: Mapping[str, str] | None = None
) -> bool:
    """Whitespace changes whose complete before/after text proves no literal changed."""
    files = _parse(diff_text, newline_only=True)
    if not _changeable(files) or head_files is None:
        return False
    for file in files:
        if _renamed_or_copied(file):
            return False
        head = head_files.get(file.path)
        if head is None:
            return False
        before = _reconstruct_before(file, head)
        if before is None or not _whitespace_context_safe(file.path, before, head):
            return False
        strict = file.path.lower().endswith(".py")
        if _normalize(before.split("\n"), strict=strict) != _normalize(
            head.split("\n"), strict=strict
        ):
            return False
    return True


def _normalize(lines: list[str], *, strict: bool) -> list[str]:
    """Normalize whitespace that carries no meaning, and only that.

    ``strict`` (indent-sensitive languages) drops trailing whitespace; the rest
    also drops leading whitespace so a re-indent reads as whitespace-only. Neither
    collapses *internal* runs: ``const s = "a  b"`` and ``const s = "a b"`` differ
    as string literals, and treating them as equal would hide a semantic edit.
    """
    if strict:
        return [line.rstrip() for line in lines if line.strip()]
    return [line.strip() for line in lines if line.strip()]


def recognize_generated(diff_text: str) -> bool:
    """Only lockfiles or generated paths changed, with no manifest or generator config."""
    files = _parse(diff_text)
    if not files:
        return False
    paths = {path for f in files for path in (f.previous_path, f.path)}
    paths.update(changed_paths_from_scope(parse_diff_scope(diff_text)))
    names = {_basename(p) for p in paths}
    if names & DEPENDENCY_MANIFEST_NAMES or names & GENERATOR_CONFIG_NAMES:
        return False
    return all(
        _basename(path) in LOCKFILE_NAMES or classify_path(path) == FileKind.GENERATED
        for path in paths
    )


# ── comment-only ──────────────────────────────────────────────────────────────

# JavaScript (``.js``, which may hold JSX), JSX and TSX are off the list: a JSX text
# child can start with ``//`` and render. Rust is off the list: a lifetime's lone ``'``
# makes the quote check unsound.
COMMENT_ONLY_SUFFIXES: Final[tuple[str, ...]] = (
    ".ts",
    ".go",
    ".java",
    ".kt",
    ".c",
    ".h",
    ".cc",
    ".cpp",
    ".hpp",
    ".cs",
    ".swift",
)
# Manifests whose comments a tool reads (SwiftPM reads the tools-version line).
_COMMENT_ONLY_REFUSED_BASENAMES: Final[frozenset[str]] = frozenset({"package.swift"})
# Strings the lexer does not model (template literals; raw, verbatim and multi-line
# strings) and any block comment: a file holding one is refused outright.
_UNLEXABLE_MARKERS: Final[tuple[str, ...]] = (
    "`",
    'r#"',
    'R"',
    '@"',
    '@$"',
    '#"',
    '"""',
    "/*",
    "#/",  # Swift extended regex literals (``#/…/#``) can span lines
)
# Java translates ``\uXXXX`` (any number of ``u``) before lexing, even inside comments,
# so ``// note \u000a doEvil();`` is a call. C trigraphs (``??/`` is a backslash) can
# splice the next line into a comment.
_JAVA_UNICODE_ESCAPE: Final[re.Pattern[str]] = re.compile(r"\\u+")
_C_FAMILY_SUFFIXES: Final[tuple[str, ...]] = (".c", ".h", ".cc", ".cpp", ".hpp")
_C_TRIGRAPH_MARKER: Final[str] = "??"
# Go: a ``_test.go`` file's ``// Output:`` comments are test assertions, and a file
# marked ``DO NOT EDIT`` is generated (its comments may be generator input or output).
_GO_TEST_SUFFIX: Final[str] = "_test.go"
_GO_GENERATED_MARKER: Final[re.Pattern[str]] = re.compile(r"do not edit", re.IGNORECASE)
# Printable ASCII plus tab and newline. Anything else (U+2028, U+2029, a lone CR, NEL,
# CRLF, any non-ASCII byte) could end a line for the language but not for this lexer.
_COMMENT_ONLY_TEXT: Final[re.Pattern[str]] = re.compile(r"[\t\n\x20-\x7e]*")
# The comment shape: optional indentation, ``//``, exactly one space, then a purely
# alphabetic first word followed by a space or the end of the line. Directive and
# pragma comments (``//go:``, ``// +build``, ``///``, ``// @ts-ignore``,
# ``// eslint-disable``, ``// Output:``) all fail this shape.
_PLAIN_COMMENT: Final[re.Pattern[str]] = re.compile(r"[ \t]*// ([A-Za-z]+)(?: .*)?")
# Plain words that still steer a compiler, a test runner or a linter.
_DIRECTIVE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "fallthrough",
        "output",
        "unordered",
        "nosonar",
        "nolint",
        "revive",
        "golangci",
        "pragma",
        "build",
        "line",
        "code",
        "istanbul",
        "nolintnextline",
        "nolintbegin",
        "nolintend",
        "iwyu",
        "jshint",
        "noqa",
        "coverage",
        "fall",
        "falls",
        "fallthru",
        "resharper",
        "noinspection",
        "tslint",
        "detekt",
    }
)


def _strings_close_on_every_line(lines: list[str]) -> bool:
    """Every ``"`` or ``'`` string opened outside a ``//`` comment closes on its line.

    With no block comment in the file and no string allowed to run past the end of a
    line, every line starts outside a string or comment, so a ``//`` line is a comment.
    """
    for line in lines:
        quote = ""
        index = 0
        while index < len(line):
            char = line[index]
            if quote:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = ""
            elif line.startswith("//", index):
                break
            elif char in {'"', "'"}:
                quote = char
            index += 1
        if quote:
            return False
    return True


def _is_plain_comment(text: str) -> bool:
    """A whole ``//`` line comment of plain words that cannot splice or steer a tool."""
    match = _PLAIN_COMMENT.fullmatch(text)
    if match is None or text.rstrip().endswith("\\"):
        return False
    return match.group(1).lower() not in _DIRECTIVE_WORDS


def _comment_file_ok(file: _File, head_text: str) -> bool:
    lowered = file.path.lower()
    if PurePosixPath(lowered).name in _COMMENT_ONLY_REFUSED_BASENAMES:
        return False
    if _COMMENT_ONLY_TEXT.fullmatch(head_text) is None:
        return False
    file_text = "\n".join([head_text, *(line[1:] for hunk in file.hunks for line in hunk.lines)])
    if any(marker in file_text for marker in _UNLEXABLE_MARKERS):
        return False
    if lowered.endswith(".java") and _JAVA_UNICODE_ESCAPE.search(file_text):
        return False
    if lowered.endswith(_C_FAMILY_SUFFIXES) and _C_TRIGRAPH_MARKER in file_text:
        return False
    if lowered.endswith(_GO_TEST_SUFFIX):
        return False
    if lowered.endswith(".go") and _GO_GENERATED_MARKER.search(file_text):
        return False
    if lowered.endswith(".go") and '"C"' in head_text:
        return False  # a cgo preamble is C code written as a comment
    head_lines = head_text.split("\n")
    if not _strings_close_on_every_line(head_lines):
        return False

    def head_line(number: int) -> str | None:
        return head_lines[number - 1] if 1 <= number <= len(head_lines) else None

    def spliced(number: int) -> bool:
        previous = head_line(number - 1)
        return previous is not None and previous.rstrip().endswith("\\")

    for hunk in file.hunks:
        for _removed, added in _blocks(hunk):
            if not added:
                return False  # a removal exists only on the base side; nothing proves it
        position = hunk.new_start
        for line in hunk.lines:
            kind, text = line[0], line[1:]
            if kind == " ":
                position += 1
                continue
            if not _is_plain_comment(text) or spliced(position):
                return False
            if kind == "+":
                if head_line(position) != text:
                    return False
                position += 1
    return True


def recognize_comment_only(diff_text: str, *, head_files: Mapping[str, str]) -> bool:
    """Only plain ``//`` comment lines changed, each proven a comment by the head text.

    The diff and the head text are split on ``\\n`` only, and either one holding a
    character outside printable ASCII plus tab and newline refuses the diff.
    """
    if _COMMENT_ONLY_TEXT.fullmatch(diff_text) is None:
        return False
    files = _parse(diff_text, newline_only=True)
    if not _changeable(files):
        return False
    for file in files:
        if _renamed_or_copied(file):
            return False
        if not file.path.lower().endswith(COMMENT_ONLY_SUFFIXES):
            return False
        head_text = head_files.get(file.path)
        if head_text is None:
            return False
        if not _comment_file_ok(file, head_text):
            return False
    return True


# ── the decision ──────────────────────────────────────────────────────────────

_DESCRIPTIONS: Final[dict[str, str]] = {
    "pinBump": "SHA or digest substitution of one old → new pair",
    "prose": "prose edit outside code, fences and front matter",
    "whitespace": "whitespace-only change",
    "generated": "lockfile or generated-file regeneration",
    "commentOnly": "comment-only edit of // line comments",
}


def _full(reason: str) -> TriageDecision:
    return TriageDecision(tier="full", recognizer=None, reason=reason)


def _lite_or_full(reason: str, *, recognizer: str, config: FastPathSettings) -> TriageDecision:
    """``lite`` for a case ``skip`` deliberately leaves out, when the operator enabled it.

    With ``review.fastPath.lite`` off this is today's ``full`` with the same reason.
    """
    if not config.lite.enabled:
        return _full(reason)
    return TriageDecision(
        tier="lite",
        recognizer=recognizer,
        reason=f"{reason}; review.fastPath.lite gives it a single capped LLM call",
        token_cap=config.lite.token_cap,
    )


# The Actions app creates the check runs of `pull_request` workflows, whose job names
# come from the head ref. A pull request author controls that ref, so its identity alone
# proves nothing about who verified the pin.
_REFUSED_CHECK_APP_SLUGS: Final[frozenset[str]] = frozenset({"github-actions"})


def trusted_check_apps(apps: Collection[str]) -> frozenset[str]:
    """Normalize the configured App slugs, dropping the ones that cannot vouch.

    A check run's name and conclusion are whatever its creator set, so a pin-bump skip
    only accepts a run from an App the operator installed. ``github-actions`` is refused
    because a ``pull_request`` workflow's job names are head-controlled; a workflow that
    may vouch must publish as its own App.
    """
    trusted: set[str] = set()
    for app in apps:
        slug = app.strip().lower()
        if slug and slug not in _REFUSED_CHECK_APP_SLUGS:
            trusted.add(slug)
    return frozenset(trusted)


def triage_diff(
    diff_text: str,
    *,
    config: FastPathSettings,
    head_files: Mapping[str, str] | None = None,
    passed_checks: Collection[str] = (),
) -> TriageDecision:
    """Decide the tier for one diff.

    Pure: no I/O, no clock, no environment. ``head_files`` is the head-side text of
    prose and comment-only-language files (only used to prove an edit stays out of a
    code fence, a string literal or a block comment) and ``passed_checks`` the names
    of the checks that passed on the head SHA **from a configured trusted App** — the
    I/O shell filters by ``app.slug`` before calling.

    ``lite`` (with ``config.lite.enabled``) replaces exactly two ``full`` outcomes: a
    matched recognizer that is not in ``skipLlm``, and an opted-in pin bump whose
    verifying checks have not passed from a trusted App (including a pin bump with no
    ``requireChecks`` or no ``trustedCheckApps``, which can never pass). It never
    takes a diff away from ``skip``.
    """
    if not config.enabled:
        return _full("review.fastPath is not enabled")
    if not diff_text.strip():
        return _full("the diff is empty")
    heads = head_files or {}
    matched: list[str] = []
    if recognize_pin_bump(diff_text):
        matched.append("pinBump")
    if recognize_prose_only(diff_text, head_files=heads):
        matched.append("prose")
    if recognize_whitespace_only(diff_text, head_files=heads):
        matched.append("whitespace")
    if recognize_generated(diff_text):
        matched.append("generated")
    if recognize_comment_only(diff_text, head_files=heads):
        matched.append("commentOnly")
    if not matched:
        return _full("no recognizer matches the whole diff")
    for name in matched:
        if name not in config.skip_llm:
            continue
        if name == "pinBump":
            required = list(config.pin_bump.require_checks)
            if not required:
                return _lite_or_full(
                    "a pin bump needs at least one review.fastPath.pinBump.requireChecks check",
                    recognizer=name,
                    config=config,
                )
            apps = trusted_check_apps(config.pin_bump.trusted_check_apps)
            if not apps:
                return _lite_or_full(
                    "a pin bump needs at least one review.fastPath.pinBump.trustedCheckApps "
                    "GitHub App; a check name alone cannot prove who verified it",
                    recognizer=name,
                    config=config,
                )
            missing = [check for check in required if check not in set(passed_checks)]
            if missing:
                return _lite_or_full(
                    "a pin bump needs its verifying check(s) passed on the head SHA from a "
                    "trusted App; not passed: " + ", ".join(missing),
                    recognizer=name,
                    config=config,
                )
            return TriageDecision(
                tier="skip",
                recognizer=name,
                reason=(
                    f"every change is a {_DESCRIPTIONS[name]}; verified by "
                    f"{', '.join(required)} from {', '.join(sorted(apps))}"
                ),
                relied_on_checks=tuple(required),
            )
        return TriageDecision(
            tier="skip",
            recognizer=name,
            reason=f"every change is a {_DESCRIPTIONS[name]}",
        )
    return _lite_or_full(
        f"{', '.join(matched)} matched but is not enabled in review.fastPath.skipLlm",
        recognizer=matched[0],
        config=config,
    )


__all__ = [
    "COMMENT_ONLY_SUFFIXES",
    "Tier",
    "TriageDecision",
    "TriageInputs",
    "recognize_comment_only",
    "recognize_generated",
    "recognize_pin_bump",
    "recognize_prose_only",
    "recognize_whitespace_only",
    "triage_diff",
]
