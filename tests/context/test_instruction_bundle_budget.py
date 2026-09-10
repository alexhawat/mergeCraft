"""RS1.2 — instruction bundle budget and exclusions (RS2, F6/F7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.context.instruction_discovery import discover_review_skill_paths
from tests.context.review_skill_support import (
    INSTRUCTION_BUNDLE_BYTE_CAP,
    LIMITATION_MARKER,
    init_repo_with_skill,
    render_prompt,
    review_section,
    seed_agent_config_noise,
    seed_nested_worktree_duplicate,
    seed_product_skill_noise,
)
from tests.context.support import git_commit_all, git_init_repo


@pytest.mark.xfail(reason="green after RS2: bundle byte cap", strict=False)
def test_bundle_respects_the_total_byte_cap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    noise = repo / "AGENTS.md"
    noise.write_text("N" * 200_000 + "\n", encoding="utf-8")
    sha = init_repo_with_skill(repo, body="Small review skill body.\n")
    prompt = render_prompt(repo, commit_sha=sha, byte_cap=INSTRUCTION_BUNDLE_BYTE_CAP)
    assert len(prompt.encode("utf-8")) <= INSTRUCTION_BUNDLE_BYTE_CAP


@pytest.mark.xfail(reason="green after RS2: truncation priority order", strict=False)
def test_review_skill_and_references_survive_truncation_first(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "AGENTS.md").write_text("A" * 200_000 + "\n", encoding="utf-8")
    marker = "PRIORITY_REFERENCE_SURVIVES"
    sha = init_repo_with_skill(
        repo,
        body="See [checks](references/checks.md).\n",
        references={"checks.md": f"# Checks\n\n{marker}\n"},
    )
    prompt = render_prompt(repo, commit_sha=sha, byte_cap=4096)
    section = review_section(prompt)
    assert marker in section


@pytest.mark.xfail(reason="green after RS2: visible truncation reporting", strict=False)
def test_truncation_is_reported_as_a_visible_limitation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "CLAUDE.md").write_text("C" * 200_000 + "\n", encoding="utf-8")
    sha = init_repo_with_skill(repo, body="Review skill body.\n")
    prompt = render_prompt(repo, commit_sha=sha, byte_cap=4096)
    assert LIMITATION_MARKER.casefold() in prompt.casefold()


@pytest.mark.xfail(reason="green after RS2: exclude product skills", strict=False)
def test_own_product_skills_are_excluded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    seed_product_skill_noise(repo)
    sha = init_repo_with_skill(repo, body="Review skill body.\n")
    prompt = render_prompt(repo, commit_sha=sha)
    assert "PRODUCT_SKILL_NOISE" not in prompt
    assert "BUNDLED_PRODUCT_SKILL" not in prompt
    assert "Review skill body." in review_section(prompt)


@pytest.mark.xfail(reason="green after RS2: skip agent config dirs", strict=False)
def test_agent_config_dirs_are_skipped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    seed_agent_config_noise(repo)
    sha = init_repo_with_skill(repo, body="Review skill body.\n")
    prompt = render_prompt(repo, commit_sha=sha)
    assert "AGENT_CONFIG_SKILL" not in prompt


@pytest.mark.xfail(reason="green after RS2: skip nested worktrees", strict=False)
def test_nested_worktree_is_skipped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = init_repo_with_skill(repo, body="Canonical review skill.\n")
    seed_nested_worktree_duplicate(repo, body="Duplicate worktree skill.\n")
    git_commit_all(repo, message="add worktree duplicate")
    paths = discover_review_skill_paths(repo)
    rels = [path.relative_to(repo).as_posix() for path in paths]
    assert rels.count(".github/skills/code-review/SKILL.md") == 1
    prompt = render_prompt(repo, commit_sha=sha)
    assert prompt.count("Canonical review skill.") == 1
    assert "Duplicate worktree skill." not in prompt


def test_a_repo_with_no_instruction_files_renders_nothing(tmp_path: Path) -> None:
    from mergecraft.context.instruction_discovery import render_review_context

    repo = tmp_path / "empty"
    repo.mkdir()
    (repo / "README.md").write_text("# Empty\n", encoding="utf-8")
    git_init_repo(repo)
    sha = git_commit_all(repo)
    prompt = render_review_context(
        repo_root=repo,
        trust_tier="trusted",
        repo="acme/demo",
        commit_sha=sha,
    )
    assert prompt == ""
