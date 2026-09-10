"""Shared helpers for review-skill doctrine RED tests (RS1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mergecraft.config.settings import RepoInfo
from mergecraft.modes import Mode
from mergecraft.utils.instructions import resolve_instructions
from tests.context.support import (
    git_commit_all,
    git_init_repo,
    section_text,
)

REVIEW_SKILLS_HEADER = "************* REVIEW SKILLS *************"

INSTRUCTION_BUNDLE_BYTE_CAP = 65536
BASELINE_SKILL_MARKER = "Follow [REVIEW-CHECKS.md](../../../REVIEW-CHECKS.md)"
DOCTRINE_GRADING_MARKER = "## 1. Code correctness"
LIMITATION_MARKER = "instruction limitation"
REFUSED_MARKER = "refused"


def write_review_skill(
    root: Path,
    *,
    body: str,
    references: dict[str, str] | None = None,
    skill_dir: Path | None = None,
) -> Path:
    """Lay down a Copilot-style review skill tree under ``root``."""
    target = skill_dir or (root / ".github" / "skills" / "code-review")
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        "---\nname: code-review\n"
        "description: Review pull requests for this repository.\n---\n\n"
        f"{body.strip()}\n",
        encoding="utf-8",
    )
    if references:
        ref_dir = target / "references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        for name, content in references.items():
            (ref_dir / name).write_text(content.strip() + "\n", encoding="utf-8")
    return target


def render_prompt(
    repo_root: Path,
    *,
    trust_tier: str = "trusted",
    commit_sha: str = "fixture-sha",
    byte_cap: int | None = INSTRUCTION_BUNDLE_BYTE_CAP,
) -> str:
    """Call the real loader with optional RS2 byte-cap kwarg."""
    from mergecraft.context.instruction_discovery import render_review_context

    kwargs: dict[str, Any] = {
        "repo_root": repo_root,
        "trust_tier": trust_tier,
        "repo": "acme/demo",
        "commit_sha": commit_sha,
    }
    if byte_cap is not None:
        kwargs["byte_cap"] = byte_cap
    return render_review_context(**kwargs)


def resolve_offline_instructions(
    repo_root: Path,
    *,
    trust_tier: str | None = None,
    retry: bool = False,
    wired: bool = True,
) -> Any:
    """Mirror ``review/offline_agent.py`` resolve_instructions call shape.

    ``wired=True`` (default) is the RS2 target shape — passes both
    ``repo_root`` and a resolved trust tier (D19). ``wired=False`` matches
    the pre-RS2 broken CLI call sites at ``offline_agent.py:212`` and
    ``:255`` (no ``repo_root``, default ``trust_tier="untrusted"``).
    """
    from mergecraft.offline_review import resolve_offline_review_trust_tier

    payload = {
        "event": {"trigger": "unknown", "title": "offline diff-review"},
        "shell": "restricted",
        "push": "disabled",
        "prompt": "review this diff",
    }
    if retry:
        payload["event"]["title"] = "offline diff-review retry"
    kwargs: dict[str, Any] = {
        "payload": payload,
        "repo": RepoInfo(owner="local", name=repo_root.name),
        "modes": [Mode(name="Review", description="Review", prompt="review")],
        "agent_id": "opencode",
        "output_schema": None,
        "setup_script_skip_reason": "",
    }
    if wired:
        kwargs["repo_root"] = repo_root
        kwargs["trust_tier"] = (
            trust_tier
            if trust_tier is not None
            else resolve_offline_review_trust_tier(
                cwd=repo_root,
                invocation_root=repo_root,
            )
        )
    elif trust_tier is not None:
        kwargs["trust_tier"] = trust_tier
    return resolve_instructions(**kwargs)


def review_skill_record(repo_root: Path, *, trust_tier: str = "trusted") -> Any:
    """Return the RS2 honest record for one rendered bundle."""
    from mergecraft.context.instruction_discovery import build_review_skill_record

    return build_review_skill_record(
        repo_root=repo_root,
        trust_tier=trust_tier,
        repo="acme/demo",
        commit_sha="fixture-sha",
        byte_cap=INSTRUCTION_BUNDLE_BYTE_CAP,
    )


def review_section(prompt: str) -> str:
    """Extract the REVIEW SKILLS section body."""
    return section_text(prompt, REVIEW_SKILLS_HEADER)


def init_repo_with_skill(
    repo_root: Path, *, body: str, references: dict[str, str] | None = None
) -> str:
    """Initialize git and return HEAD sha for a one-skill fixture repo."""
    write_review_skill(repo_root, body=body, references=references)
    git_init_repo(repo_root)
    return git_commit_all(repo_root)


def seed_product_skill_noise(repo_root: Path) -> None:
    """Add mergeCraft product-skill paths that RS2 must exclude (F6)."""
    product = repo_root / "skills" / "mergecraft"
    product.mkdir(parents=True, exist_ok=True)
    (product / "SKILL.md").write_text(
        "---\nname: mergecraft\n---\n\nPRODUCT_SKILL_NOISE\n",
        encoding="utf-8",
    )
    bundled = repo_root / "src" / "mergecraft" / "skills" / "demo"
    bundled.mkdir(parents=True, exist_ok=True)
    (bundled / "SKILL.md").write_text(
        "---\nname: demo\n---\n\nBUNDLED_PRODUCT_SKILL\n",
        encoding="utf-8",
    )


def seed_agent_config_noise(repo_root: Path) -> None:
    """Add agent-config trees RS2 must skip (F7)."""
    for rel in (
        ".claude/skills/demo/SKILL.md",
        ".agents/skills/demo/SKILL.md",
        ".opencode/skills/demo/SKILL.md",
        ".cursor/skills/demo/SKILL.md",
    ):
        path = repo_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nname: demo\n---\n\nAGENT_CONFIG_SKILL\n", encoding="utf-8")


def seed_nested_worktree_duplicate(repo_root: Path, *, body: str) -> None:
    """Lay a duplicate review skill under ``.claude/worktrees/`` (F7)."""
    duplicate_root = repo_root / ".claude" / "worktrees" / "nested-fixture"
    write_review_skill(
        duplicate_root, body=body, skill_dir=duplicate_root / ".github" / "skills" / "code-review"
    )
    git_dir = duplicate_root / ".git"
    git_dir.parent.mkdir(parents=True, exist_ok=True)
    git_dir.write_text("gitdir: /tmp/fake-worktree\n", encoding="utf-8")


def skill_root() -> Path:
    """Return the canonical code-review skill directory for this checkout."""
    return Path(__file__).resolve().parents[2] / ".github" / "skills" / "code-review"
