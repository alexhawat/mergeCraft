"""C15 / C20 — renderer-aware markdown link check (PD1 RED).

Wave plan: ``.ignorelocal/waves/44-prompts-docs-contracts-wave-plan.md`` (PD1).
Locked decision **PD-D9** — a pytest in ``tests/docs/`` (not a make target)
using GitHub slug rules plus explicit ``<span id>`` / ``<a id>`` / ``<a name>``
anchors; ``{#id}`` is **not** an anchor. Scope: ``docs/**/*.md``,
``README.md``, ``REVIEW-CHECKS.md``, ``SECURITY.md``, ``CONTRIBUTING.md``,
``AGENTS.md``; ``CHANGELOG.md`` and the generated ``docs/action-reference.md``
are excluded. Relative links resolve against the containing file's directory;
a directory target is valid.

Links and anchors are extracted from renderer-faithful text: fenced code blocks
(``` / `~~~`) and inline code spans are blanked first, because GitHub renders
neither as a link or an anchor. Heading text keeps its inline-code *content*
(``## The `push` input`` → ``the-push-input``) but a ``#`` line inside a fence is
not a heading.

The named fix cases are PD4.1-PD4.4's post-fix target list; the named green
cases must stay green. These assertions fail until PD4; do not xfail: RED is the
point.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import NamedTuple

import pytest

from tests.ci.workflow_support import REPO_ROOT

_ROOT = REPO_ROOT

_LINK_RE = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+[\"'][^\"']*[\"'])?\s*\)")
_EXPLICIT_ANCHOR_RE = re.compile(
    r"<(?:span|a)\s+[^>]*?(?:id|name)\s*=\s*[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_ATX_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$", re.MULTILINE)
_LINK_TITLE_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1", re.DOTALL)

_EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:")
_IGNORED_DIR = ".ignorelocal"

_ROOT_FILES = ("README.md", "REVIEW-CHECKS.md", "SECURITY.md", "CONTRIBUTING.md", "AGENTS.md")
_EXCLUDED = frozenset({"docs/action-reference.md"})


class LinkBreak(NamedTuple):
    """One link GitHub would not resolve."""

    source: str
    line: int
    target: str
    reason: str


def _blank_text(text: str) -> str:
    """Replace every non-newline character with a space (offsets stay stable)."""
    return "".join("\n" if ch == "\n" else " " for ch in text)


def _strip_fenced(text: str) -> str:
    """Blank ``` / `~~~` fenced code blocks; GitHub renders no heading or link inside."""
    lines = text.split("\n")
    fence: str | None = None
    for index, line in enumerate(lines):
        match = _FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)[0]
                lines[index] = _blank_text(line)
        else:
            lines[index] = _blank_text(line)
            if match and match.group(1)[0] == fence:
                fence = None
    return "\n".join(lines)


def _strip_code(text: str) -> str:
    """Blank fenced blocks and inline code spans — GitHub renders neither as a link/anchor."""
    return _INLINE_CODE_RE.sub(lambda match: _blank_text(match.group(0)), _strip_fenced(text))


def _scope_files() -> list[Path]:
    files = sorted((_ROOT / "docs").rglob("*.md"))
    files.extend(_ROOT / name for name in _ROOT_FILES)
    out: list[Path] = []
    for path in files:
        if not path.is_file():
            continue
        rel = path.relative_to(_ROOT).as_posix()
        if rel in _EXCLUDED:
            continue
        out.append(path)
    return out


def _slugify(text: str) -> str:
    """GitHub heading slug: lowercase, strip non-word chars, spaces → hyphens."""
    text = _LINK_TITLE_RE.sub(r"\1", text)
    text = text.replace("`", "").replace("*", "").replace("~", "")
    lowered = text.lower()
    kept = "".join(ch for ch in lowered if ch.isalnum() or ch in "_- ")
    return kept.replace(" ", "-")


def _anchors_from_text(text: str) -> set[str]:
    anchors = set(_EXPLICIT_ANCHOR_RE.findall(_strip_code(text)))
    anchors.update(_slugify(match.group(2)) for match in _ATX_RE.finditer(_strip_fenced(text)))
    return anchors


@cache
def _anchors_for(path: Path) -> frozenset[str]:
    return frozenset(_anchors_from_text(path.read_text(encoding="utf-8")))


def _iter_links(text: str) -> list[tuple[int, str]]:
    stripped = _strip_code(text)
    return [(match.start(), match.group(1).strip()) for match in _LINK_RE.finditer(stripped)]


def _reason_for(source: Path, target: str) -> str | None:
    if not target or target.startswith(_EXTERNAL_PREFIXES):
        return None
    if target.startswith("#"):
        fragment = target[1:]
        target_path = source
    else:
        head, _, fragment = target.partition("#")
        target_path = (source.parent / head).resolve()
    if not target_path.exists():
        return "missing target"
    if fragment and target_path.is_file() and fragment not in _anchors_for(target_path):
        return "missing anchor"
    return None


def link_resolves(source_rel: str, target: str) -> bool:
    """Return whether *target* resolves from the in-repo file *source_rel*."""
    return _reason_for(_ROOT / source_rel, target) is None


def _link_enters_ignored_dir(source: Path, target: str) -> bool:
    """Return whether *target* resolves into the gitignored ``.ignorelocal/`` tree."""
    if not target or target.startswith(_EXTERNAL_PREFIXES) or target.startswith("#"):
        return False
    head = target.partition("#")[0]
    if not head:
        return False
    resolved = (source.parent / head).resolve()
    return resolved.is_relative_to((_ROOT / _IGNORED_DIR).resolve())


def collect_breaks() -> list[LinkBreak]:
    """Return every unresolved in-scope link (empty when the docs are clean)."""
    breaks: list[LinkBreak] = []
    for path in _scope_files():
        text = path.read_text(encoding="utf-8")
        for offset, target in _iter_links(text):
            reason = _reason_for(path, target)
            if reason is None:
                continue
            breaks.append(
                LinkBreak(
                    source=path.relative_to(_ROOT).as_posix(),
                    line=text[:offset].count("\n") + 1,
                    target=target,
                    reason=reason,
                )
            )
    return breaks


# PD4.1-PD4.4's post-fix contract: the target each doc will hold *after* the fix,
# and therefore must resolve. Several already resolve in the current tree; the two
# glossary anchors stay RED until PD4.3 converts the `{#id}` headings. The general
# guard below is what tracks the not-yet-fixed doc strings.
_PD4_FIX_LINKS: tuple[tuple[str, str], ...] = (
    ("docs/trust-policy.md", "../src/mergecraft/config/trust_policy.py"),
    ("docs/trust-policy.md", "../src/mergecraft/analyzers/trust.py"),
    ("docs/trust-policy.md", "../.github/workflows/mergecraft-approve.yml"),
    ("docs/trust-policy.md", "../.mergecraft/config.yaml"),
    ("docs/workflows.md", "../.github/workflows/mergecraft-approve.yml"),
    ("docs/dev/changelog-archive.md", "../findings-carryover.md"),
    ("README.md", "docs/glossary.md#trust-tier"),
    ("docs/trust-policy.md", "glossary.md#trust-tier"),
    (
        "docs/_mcp_reviewer_tools.md",
        "config-failure-policy.md#mcp-git-tool--reviewer-surface-enforcement-257",
    ),
    (
        "docs/mcp-tools.md",
        "config-failure-policy.md#mcp-git-tool--reviewer-surface-enforcement-257",
    ),
    # True GitHub slug of `## Quick start — init → auth → review`: github-slugger
    # 2.0.0 strips both the em dash and the arrow, leaving a double hyphen (the same
    # rule as the green `example-1--auto-review-every-pr`).
    ("docs/agent-roster.md", "authentication.md#quick-start--init--auth--review"),
)

# Named green cases (Part 1 "valid, no action").
_GREEN_LINKS: tuple[tuple[str, str], ...] = (
    ("README.md", "#how-it-works"),
    ("README.md", "#for-agents"),
    ("docs/workflows.md", "#security-model"),
    ("docs/trust-policy.md", "../SECURITY.md#agent-credential-broker-codex-553"),
    ("SECURITY.md", "docs/trust-policy.md#agent-credential-broker-553"),
    ("docs/install.md", "../README.md#example-1--auto-review-every-pr"),
)


def test_slug_rules_match_github() -> None:
    assert _slugify("Example 1 — auto review every PR") == "example-1--auto-review-every-pr"
    assert _slugify("Trust tier {#trust-tier}") == "trust-tier-trust-tier"


def test_explicit_anchors_are_honoured_and_brace_ids_are_not() -> None:
    anchors = _anchors_from_text(
        "### Trust tier {#trust-tier}\n"
        '<span id="how-it-works"></span>\n'
        '<a id="explicit-a"></a>\n'
        '<a name="explicit-n"></a>\n'
    )
    assert {"how-it-works", "explicit-a", "explicit-n"} <= anchors
    assert "trust-tier" not in anchors
    assert "trust-tier-trust-tier" in anchors


def test_no_broken_markdown_links_in_scope() -> None:
    breaks = collect_breaks()
    rendered = "\n".join(f"  {b.source}:{b.line} -> {b.target} [{b.reason}]" for b in breaks)
    assert not breaks, f"{len(breaks)} link(s) do not resolve on GitHub:\n{rendered}"


def test_no_in_scope_link_enters_the_gitignored_wave_directory() -> None:
    """No in-scope doc may link into `.ignorelocal/` — gitignored, so CI never resolves it."""
    offenders: list[str] = []
    for path in _scope_files():
        text = path.read_text(encoding="utf-8")
        for offset, target in _iter_links(text):
            if not _link_enters_ignored_dir(path, target):
                continue
            line = text[:offset].count("\n") + 1
            offenders.append(f"  {path.relative_to(_ROOT).as_posix()}:{line} -> {target}")
    assert not offenders, (
        f"{len(offenders)} in-scope markdown link(s) target the gitignored "
        f"{_IGNORED_DIR}/ tree (de-link them; CI cannot resolve them):\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize(("source", "target"), _GREEN_LINKS)
def test_named_green_links_resolve(source: str, target: str) -> None:
    assert link_resolves(source, target), f"{source} -> {target} must resolve"


@pytest.mark.parametrize(("source", "target"), _PD4_FIX_LINKS)
def test_pd4_fix_targets_resolve(source: str, target: str) -> None:
    assert link_resolves(source, target), f"{source} -> {target} must resolve after PD4 (see PD-D9)"
