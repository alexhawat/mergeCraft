"""#620 — Copilot-style review skills are preferred and stay trust-fenced."""

from __future__ import annotations

from pathlib import Path

from tests.context.support import (
    REPO_INSTRUCTIONS_HEADER,
    fenced_blocks,
    git_commit_all,
    git_init_repo,
    section_text,
)
from tests.support.cc_batch import load_module, require_callable

REVIEW_SKILLS_HEADER = "************* REVIEW SKILLS *************"


def test_prefers_github_code_review_skill(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    generic = repo / ".cursor" / "skills" / "demo"
    generic.mkdir(parents=True)
    (generic / "SKILL.md").write_text(
        "---\nname: demo\n---\n\nGENERIC_SKILL\n",
        encoding="utf-8",
    )
    review = repo / ".github" / "skills" / "code-review"
    review.mkdir(parents=True)
    (review / "SKILL.md").write_text(
        "---\nname: code-review\n---\n\nREVIEW_DOCTRINE\n",
        encoding="utf-8",
    )
    git_init_repo(repo)
    sha = git_commit_all(repo)
    module = load_module("mergecraft.context.instruction_discovery")
    render = require_callable(module, "render_review_context")
    prompt = render(
        repo_root=repo,
        trust_tier="trusted",
        repo="acme/demo",
        commit_sha=sha,
    )
    review_section = section_text(prompt, REVIEW_SKILLS_HEADER)
    repo_section = section_text(prompt, REPO_INSTRUCTIONS_HEADER)
    assert "REVIEW_DOCTRINE" in review_section
    assert "GENERIC_SKILL" in repo_section
    assert "REVIEW_DOCTRINE" not in repo_section


def test_untrusted_review_skill_is_fenced(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    review = repo / ".github" / "skills" / "code-review"
    review.mkdir(parents=True)
    (review / "SKILL.md").write_text(
        "---\nname: code-review\n---\n\nUNTRUSTED_REVIEW_SKILL\n",
        encoding="utf-8",
    )
    git_init_repo(repo)
    sha = git_commit_all(repo)
    module = load_module("mergecraft.context.instruction_discovery")
    render = require_callable(module, "render_review_context")
    prompt = render(
        repo_root=repo,
        trust_tier="untrusted",
        repo="acme/demo",
        commit_sha=sha,
    )
    assert "UNTRUSTED_REVIEW_SKILL" not in section_text(prompt, REVIEW_SKILLS_HEADER)
    assert any("UNTRUSTED_REVIEW_SKILL" in block for block in fenced_blocks(prompt))
