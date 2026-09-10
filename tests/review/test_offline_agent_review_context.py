"""RS1.7 — CLI review context wiring (RS2, F11/D19)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.context.review_skill_support import (
    INSTRUCTION_BUNDLE_BYTE_CAP,
    init_repo_with_skill,
    resolve_offline_instructions,
    review_section,
)
from tests.context.support import REPO_INSTRUCTIONS_HEADER, section_text


@pytest.mark.xfail(reason="green after RS2: CLI review skills section", strict=False)
def test_cli_review_renders_the_review_skills_section(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo_with_skill(repo, body="CLI review skill body.\n")
    resolved = resolve_offline_instructions(repo)
    assert "REVIEW SKILLS" in resolved.full
    assert "CLI review skill body." in review_section(resolved.full)
    assert REPO_INSTRUCTIONS_HEADER in resolved.full or section_text(
        resolved.full, REPO_INSTRUCTIONS_HEADER
    )


@pytest.mark.xfail(reason="green after RS2: CLI review_skill_paths extra", strict=False)
def test_cli_review_populates_review_skill_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo_with_skill(repo, body="CLI review skill body.\n")
    resolved = resolve_offline_instructions(repo)
    review_skills = list(resolved.extra.get("review_skills") or [])
    assert review_skills == [".github/skills/code-review/SKILL.md"]


@pytest.mark.xfail(reason="green after RS2: CLI reference resolution", strict=False)
def test_cli_review_resolves_skill_references(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    marker = "CLI_RESOLVED_REFERENCE"
    init_repo_with_skill(
        repo,
        body="See [checks](references/checks.md).\n",
        references={"checks.md": f"# Checks\n\n{marker}\n"},
    )
    resolved = resolve_offline_instructions(repo)
    assert marker in review_section(resolved.full)


def test_untrusted_cli_source_fences_the_discovered_skill(tmp_path: Path) -> None:
    """D19 control — wiring ``repo_root`` must not bypass the untrusted fence."""
    repo = tmp_path / "repo"
    marker = "UNTRUSTED_CLI_SKILL"
    init_repo_with_skill(repo, body=f"{marker}\n")
    resolved = resolve_offline_instructions(repo, wired=True, trust_tier="untrusted")
    assert marker not in review_section(resolved.full)
    assert any(marker in block for block in _fenced_blocks(resolved.full))


@pytest.mark.xfail(reason="green after RS2: CLI bundle cap", strict=False)
def test_cli_review_respects_the_bundle_cap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    (repo / "AGENTS.md").write_text("Z" * 200_000 + "\n", encoding="utf-8")
    init_repo_with_skill(repo, body="Small CLI review skill.\n")
    resolved = resolve_offline_instructions(repo)
    assert len(resolved.full.encode("utf-8")) <= INSTRUCTION_BUNDLE_BYTE_CAP


@pytest.mark.parametrize("retry", [False, True], ids=["primary", "retry"])
@pytest.mark.xfail(reason="green after RS2: both offline call sites wired", strict=False)
def test_both_call_sites_are_wired(tmp_path: Path, retry: bool) -> None:
    repo = tmp_path / "repo"
    init_repo_with_skill(repo, body=f"Offline call site retry={retry}\n")
    resolved = resolve_offline_instructions(repo, retry=retry)
    assert "REVIEW SKILLS" in resolved.full
    assert resolved.extra.get("review_skills")


def _fenced_blocks(prompt: str) -> list[str]:
    from tests.context.support import fenced_blocks

    return fenced_blocks(prompt)
