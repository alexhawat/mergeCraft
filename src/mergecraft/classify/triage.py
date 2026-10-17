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
  paths, with no changed line in a code fence, front matter, or indented code. The
  head-side file text proves that; without it nothing is proven.
* ``whitespace`` — every contiguous change block is the same tokens before and
  after. Whitespace-sensitive languages only get trailing-whitespace and blank-line
  changes; comment-only changes are not recognized (they need the language's string
  rules) and fall through to a full review.
* ``generated`` — only lockfiles or generated paths changed, and no dependency
  manifest or generator config changed with them.

Two tiers ship: ``skip`` (no LLM review) and ``full`` (today's review). A cheaper
``lite`` tier is not implemented; a recognizer that matches but is not enabled, or a
pin bump whose verifying check has not passed, is ``full``.

The tier is a pure function of the diff, the config, head-side text used only to prove
a markdown edit stays out of a code fence, and the names of the checks that passed on
the head SHA. The pull request's title, body, labels and head-side config are not
inputs: a fork author must not be able to opt themselves out of review.

Exports:
    TriageDecision: The tier, the recognizer behind it, and why.
    TriageInputs: What the I/O layer reads for one pull request.
    triage_diff: The pure tier decision.
    recognize_pin_bump, recognize_prose_only, recognize_whitespace_only,
    recognize_generated: The recognizers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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

Tier = Literal["skip", "full"]

_SHA: Final[re.Pattern[str]] = re.compile(
    r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{40}(?![0-9A-Fa-f])|sha256:[0-9A-Fa-f]{64}"
)
_FENCE: Final[re.Pattern[str]] = re.compile(r"^\s{0,3}(```|~~~)")
_PROSE_SUFFIXES: Final[tuple[str, ...]] = (".md", ".markdown", ".txt")
_MARKDOWN_SUFFIXES: Final[tuple[str, ...]] = (".md", ".markdown")
# Whitespace carries meaning here, so only trailing whitespace and blank lines are noise.
_INDENT_SENSITIVE_SUFFIXES: Final[tuple[str, ...]] = (
    ".py",
    ".pyx",
    ".mk",
    ".nim",
    ".haml",
    ".pug",
    ".slim",
    ".coffee",
)
_INDENT_SENSITIVE_NAMES: Final[frozenset[str]] = frozenset({"Makefile", "makefile", "GNUmakefile"})
# Formats where even trailing whitespace is content (hard breaks, block scalars).
_WHITESPACE_INELIGIBLE_SUFFIXES: Final[tuple[str, ...]] = (
    ".md",
    ".markdown",
    ".rst",
    ".txt",
    ".yml",
    ".yaml",
)


@dataclass(frozen=True, slots=True)
class TriageDecision:
    """The triage tier and the reasoning behind it.

    Attributes:
        tier: ``skip`` (no LLM review runs) or ``full`` (today's review).
        recognizer: The recognizer behind a ``skip``; ``None`` for ``full``.
        reason: Why, in one sentence.
        relied_on_checks: Checks that had to pass on the head SHA for this ``skip``.
    """

    tier: Tier
    recognizer: str | None
    reason: str
    relied_on_checks: tuple[str, ...] = field(default_factory=tuple)

    def record_line(self) -> str:
        """The line the run record and the checks show, so a skip never reads as a review."""
        if self.tier == "skip":
            return f"Tier: skip ({self.recognizer}) — no LLM review ran"
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
    lines: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _File:
    path: str
    binary: bool = False
    hunks: list[_Hunk] = field(default_factory=list)


def _parse(diff_text: str) -> list[_File]:
    files: list[_File] = []
    current: _File | None = None
    hunk: _Hunk | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            path = raw.rpartition(" b/")[2].strip()
            current = _File(path=path)
            files.append(current)
            hunk = None
            continue
        if current is None:
            continue
        if hunk is None:
            if raw.startswith("+++ b/"):
                current.path = raw[6:].strip()
            elif raw.startswith(("Binary files ", "GIT binary patch")):
                current.binary = True
            elif raw.startswith("@@"):
                hunk = _new_hunk(raw, current)
            continue
        if raw.startswith("@@"):
            hunk = _new_hunk(raw, current)
        elif raw[:1] in {" ", "+", "-"}:
            hunk.lines.append(raw)
        elif raw == "":
            hunk.lines.append(" ")
    return files


def _new_hunk(header: str, current: _File) -> _Hunk:
    match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", header)
    hunk = _Hunk(new_start=int(match.group(1)) if match else 1)
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
    if not file.path.lower().endswith(_MARKDOWN_SUFFIXES):
        return True  # plain text: no fences, no front matter
    head_lines = head_text.splitlines()
    inside = _inside_code_before(head_lines)
    front_matter = _front_matter_end(head_lines)
    for hunk in file.hunks:
        position = hunk.new_start
        for line in hunk.lines:
            if line[0] == " ":
                position += 1
                continue
            text = line[1:]
            if _FENCE.match(text) or text.startswith(("    ", "\t")):
                return False
            if position <= front_matter or (position < len(inside) and inside[position]):
                return False
            if line[0] == "+":
                position += 1
    return True


def recognize_prose_only(diff_text: str, *, head_files: Mapping[str, str]) -> bool:
    """Only prose files changed, and no changed line sits in code, a fence or front matter."""
    files = _parse(diff_text)
    if not _changeable(files):
        return False
    for file in files:
        lowered = file.path.lower()
        if not lowered.endswith(_PROSE_SUFFIXES):
            return False
        if any(part in lowered for part in _HIGH_STAKES_PATH_PARTS):
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


def recognize_whitespace_only(diff_text: str) -> bool:
    """Every change block is the same tokens before and after, differing only in whitespace."""
    files = _parse(diff_text)
    if not _changeable(files):
        return False
    for file in files:
        lowered = file.path.lower()
        if lowered.endswith(_WHITESPACE_INELIGIBLE_SUFFIXES):
            return False
        name = _basename(file.path)
        strict = name in _INDENT_SENSITIVE_NAMES or lowered.endswith(_INDENT_SENSITIVE_SUFFIXES)
        for hunk in file.hunks:
            for removed, added in _blocks(hunk):
                if _normalize(removed, strict=strict) != _normalize(added, strict=strict):
                    return False
    return True


def _normalize(lines: list[str], *, strict: bool) -> list[str]:
    if strict:
        return [line.rstrip() for line in lines if line.strip()]
    return [" ".join(line.split()) for line in lines if line.strip()]


def recognize_generated(diff_text: str) -> bool:
    """Only lockfiles or generated paths changed, with no manifest or generator config."""
    files = _parse(diff_text)
    if not files:
        return False
    paths = {f.path for f in files} | set(changed_paths_from_scope(parse_diff_scope(diff_text)))
    names = {_basename(p) for p in paths}
    if names & DEPENDENCY_MANIFEST_NAMES or names & GENERATOR_CONFIG_NAMES:
        return False
    return all(
        _basename(path) in LOCKFILE_NAMES or classify_path(path) == FileKind.GENERATED
        for path in paths
    )


# ── the decision ──────────────────────────────────────────────────────────────

_DESCRIPTIONS: Final[dict[str, str]] = {
    "pinBump": "SHA or digest substitution of one old → new pair",
    "prose": "prose edit outside code, fences and front matter",
    "whitespace": "whitespace-only change",
    "generated": "lockfile or generated-file regeneration",
}


def _full(reason: str) -> TriageDecision:
    return TriageDecision(tier="full", recognizer=None, reason=reason)


def triage_diff(
    diff_text: str,
    *,
    config: FastPathSettings,
    head_files: Mapping[str, str] | None = None,
    passed_checks: Collection[str] = (),
) -> TriageDecision:
    """Decide the tier for one diff.

    Pure: no I/O, no clock, no environment. ``head_files`` is the head-side text of
    prose files (only used to prove an edit stays out of a code fence) and
    ``passed_checks`` the names of the checks that passed on the head SHA.
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
    if recognize_whitespace_only(diff_text):
        matched.append("whitespace")
    if recognize_generated(diff_text):
        matched.append("generated")
    if not matched:
        return _full("no recognizer matches the whole diff")
    for name in matched:
        if name not in config.skip_llm:
            continue
        if name == "pinBump":
            required = list(config.pin_bump.require_checks)
            if not required:
                return _full(
                    "a pin bump needs at least one review.fastPath.pinBump.requireChecks check"
                )
            missing = [check for check in required if check not in set(passed_checks)]
            if missing:
                return _full(
                    "a pin bump needs its verifying check(s) passed on the head SHA; "
                    "not passed: " + ", ".join(missing)
                )
            return TriageDecision(
                tier="skip",
                recognizer=name,
                reason=f"every change is a {_DESCRIPTIONS[name]}; verified by {', '.join(required)}",
                relied_on_checks=tuple(required),
            )
        return TriageDecision(
            tier="skip",
            recognizer=name,
            reason=f"every change is a {_DESCRIPTIONS[name]}",
        )
    return _full(f"{', '.join(matched)} matched but is not enabled in review.fastPath.skipLlm")


__all__ = [
    "Tier",
    "TriageDecision",
    "TriageInputs",
    "recognize_generated",
    "recognize_pin_bump",
    "recognize_prose_only",
    "recognize_whitespace_only",
    "triage_diff",
]
