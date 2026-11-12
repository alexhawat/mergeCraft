"""Which ``.md`` / ``.txt`` paths the ``prose`` recognizer may skip.

Instruction and skill sources (the paths instruction discovery reads) and the
``.mergecraft/`` directory are never prose: each gets a full review. Every case
runs through :func:`triage_diff` with ``prose`` opted in to ``skipLlm``, so the
decision is the one a run makes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from mergecraft.classify.triage import TriageDecision

_HEAD = "hello there\n"


def _prose_diff(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        "@@ -1,1 +1,1 @@\n-hello world\n+hello there\n"
    )


def _triage(path: str, *, extra_filenames: tuple[str, ...] = ()) -> TriageDecision:
    from mergecraft.classify.triage import triage_diff
    from mergecraft.config.settings import FastPathSettings

    config = FastPathSettings.model_validate({"enabled": True, "skipLlm": ["prose"]})
    return triage_diff(
        _prose_diff(path),
        config=config,
        head_files={path: _HEAD},
        instruction_extra_filenames=extra_filenames,
    )


_INSTRUCTION_PATHS = [
    "skills/code-review/SKILL.md",
    "docs/review/SKILL.md",
    "SKILL.md",
    "pkg/AGENTS.md",
    "sub/CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    ".windsurf/rules/review.md",
    "app/.windsurf/rules/style.md",
    ".cursor/rules/review.md",
    ".mergecraft/learnings.md",
    ".mergecraft/xrepo-brief.md",
    "Agents.md",
]


@pytest.mark.parametrize("path", _INSTRUCTION_PATHS, ids=_INSTRUCTION_PATHS)
def test_instruction_and_mergecraft_paths_get_a_full_review(path: str) -> None:
    decision = _triage(path)

    assert decision.tier == "full", decision.reason


@pytest.mark.parametrize("name", ["TEAM.md", "team.md"], ids=["exact-case", "other-case"])
def test_a_configured_extra_instruction_filename_gets_a_full_review(name: str) -> None:
    assert _triage(name, extra_filenames=("TEAM.md",)).tier == "full"


def test_every_path_instruction_discovery_reads_is_refused() -> None:
    """The refusal is derived from discovery's own predicate, not a second list."""
    from mergecraft.classify.triage import recognize_prose_only
    from mergecraft.context.instruction_discovery import is_instruction_path

    candidates = [
        *_INSTRUCTION_PATHS,
        "TEAM.md",
        "a/b/c/SKILL.md",
        ".cursor/rules/nested/x.md",
        "docs/guide.md",
        "README.md",
    ]
    for path in candidates:
        if is_instruction_path(path, extra_filenames=("TEAM.md",)):
            assert not recognize_prose_only(
                _prose_diff(path),
                head_files={path: _HEAD},
                instruction_extra_filenames=("TEAM.md",),
            ), path


@pytest.mark.parametrize(
    "path",
    ["README.md", "docs/guide.md", "docs/notes.txt", "NOTICE.txt"],
    ids=["readme", "docs-markdown", "docs-text", "notice-text"],
)
def test_ordinary_prose_still_skips(path: str) -> None:
    decision = _triage(path)

    assert decision.tier == "skip"
    assert decision.recognizer == "prose"
