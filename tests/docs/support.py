"""Shared helpers for the ``tests/docs`` contract suite (#405)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from mergecraft.utils.git_ref import git_ref_exists
from tests.ci.workflow_support import REPO_ROOT

__all__ = [
    "AGENT_SECTION_MARKER_RE",
    "action_uses_pattern",
    "agent_section_precedes_body",
    "ci_steps",
    "git_ref_exists",
    "load_harness_manifest",
    "load_script_module",
    "makefile_prerequisite_tokens",
    "readme_agent_section_region",
]

action_uses_pattern = re.compile(
    r"uses:\s*alexhawat/mergeCraft@(\S+)",
    re.IGNORECASE,
)

HARNESS_MANIFEST = REPO_ROOT / "skills" / "harnesses.yaml"


def load_harness_manifest() -> dict[str, Any]:
    """Parse ``skills/harnesses.yaml`` as a mapping."""
    assert HARNESS_MANIFEST.is_file(), f"missing {HARNESS_MANIFEST.relative_to(REPO_ROOT)}"
    data = yaml.safe_load(HARNESS_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "skills/harnesses.yaml must parse as a mapping"
    return data


def makefile_prerequisite_tokens(makefile: str, target: str) -> set[str]:
    """Return Makefile prerequisite tokens for *target*."""
    match = re.search(rf"^{re.escape(target)}:(.*)$", makefile, re.MULTILINE)
    assert match, f"Makefile missing {target}: recipe"
    return set(match.group(1).split())


def ci_steps() -> list[str]:
    """Return Makefile ``CI_STEPS`` tokens."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^CI_STEPS\s*:?=\s*(.+)$", makefile, re.MULTILINE)
    assert match, "Makefile missing CI_STEPS"
    return match.group(1).split()


def load_script_module(path: str | Path) -> ModuleType:
    """Load a repo script by absolute or repo-relative path."""
    script = Path(path)
    if not script.is_absolute():
        script = REPO_ROOT / script
    assert script.is_file(), f"missing {script.relative_to(REPO_ROOT)}"
    module_name = f"mergecraft_docs_support_{script.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        msg = f"could not load {script}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# The README's agent section may be written either as a plain H2 or collapsed
# into a ``<details>`` disclosure block. D2 requires the section to exist and to
# come before the prose, not that it be rendered as a heading -- a ``<summary>``
# carries the same text and the same ``#for-agents`` anchor. Both spellings are
# accepted so the README can present the section either way.
AGENT_SECTION_MARKER_RE = re.compile(
    r"^(?:"
    r"##\s+[^\n]*(?:For LLM\s*/\s*Agents|For AI coding agents)[^\n]*"
    r"|"
    r"<summary>[^\n]*(?:For LLM\s*/\s*Agents|For AI coding agents)[^\n]*</summary>"
    r")\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# A section ends at the next H2. The collapsed form ends at the ``</details>``
# that closes ITS OWN ``<details>`` -- the README nests disclosure blocks (the
# per-agent one-liners sit inside the agent section), so a naive search for the
# first ``</details>`` truncates the region mid-section.
_H2_RE = re.compile(r"^##\s", re.MULTILINE)
_DETAILS_TOKEN_RE = re.compile(r"<details[\s>]|</details>", re.IGNORECASE)


def _collapsed_section_end(text: str, start: int) -> int:
    """Return the offset of the ``</details>`` closing the section opened before *start*."""
    depth = 1
    for token in _DETAILS_TOKEN_RE.finditer(text, start):
        depth += -1 if token.group(0).lower() == "</details>" else 1
        if depth == 0:
            return token.start()
    return len(text)


def readme_agent_section_region(text: str) -> str | None:
    """Return the README agent section body, or ``None`` when absent.

    Handles both the H2 spelling and the collapsed ``<details>`` spelling,
    including disclosure blocks nested inside the section.
    """
    marker = AGENT_SECTION_MARKER_RE.search(text)
    if marker is None:
        return None
    start = marker.end()
    if marker.group(0).lstrip().lower().startswith("<summary"):
        end = _collapsed_section_end(text, start)
    else:
        next_h2 = _H2_RE.search(text, start)
        end = next_h2.start() if next_h2 else len(text)
    return text[start:end]


def agent_section_precedes_body(text: str) -> bool:
    """Return whether the agent section opens before the first prose H2.

    The collapsed form emits no H2 of its own, so ordering is checked by offset
    against the first H2 rather than by reading the heading list.
    """
    marker = AGENT_SECTION_MARKER_RE.search(text)
    if marker is None:
        return False
    for m in re.finditer(r"^##\s+(?!#)([^\n]*)$", text, re.MULTILINE):
        if AGENT_SECTION_MARKER_RE.match(m.group(0)):
            continue
        return marker.start() < m.start()
    return True
