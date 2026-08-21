"""W8 / W11 — remaining instruction sources + trust-tiered external files (#357).

Does not author mergeCraft's own AGENTS.md / skill (file 7).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.context.support import (
    REPO_INSTRUCTIONS_HEADER,
    STANDING_INSTRUCTIONS_HEADER,
    fenced_blocks,
    git_commit_all,
    git_init_repo,
    section_text,
)
from tests.support.cc_batch import load_module, require_callable

_UNTRUSTED_MARKER = "UNTRUSTED_GEMINI_MUST_NOT_ENTER_INSTRUCTIONS"


def test_discovers_gemini_copilot_windsurf_and_custom_list(tmp_path: Path) -> None:
    """#357 — GEMINI.md, Copilot instructions, Windsurf rules, configurable extras."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "GEMINI.md").write_text("# gemini\n", encoding="utf-8")
    github = repo / ".github"
    github.mkdir()
    (github / "copilot-instructions.md").write_text("# copilot\n", encoding="utf-8")
    windsurf = repo / ".windsurf" / "rules"
    windsurf.mkdir(parents=True)
    (windsurf / "style.md").write_text("# windsurf\n", encoding="utf-8")
    (repo / "TEAM.md").write_text("# team\n", encoding="utf-8")
    git_init_repo(repo)
    git_commit_all(repo)

    module = load_module("mergecraft.context.instruction_discovery")
    discover = require_callable(module, "discover_instruction_paths")
    paths = {str(path).replace("\\", "/") for path in discover(repo, extra_filenames=("TEAM.md",))}
    joined = " ".join(sorted(paths))
    assert "GEMINI.md" in joined
    assert "copilot-instructions.md" in joined
    assert "style.md" in joined
    assert "TEAM.md" in joined


def test_skill_md_remains_a_controlled_context_source(tmp_path: Path) -> None:
    """#357 — SKILL.md stays a controlled context source."""
    repo = tmp_path / "repo"
    skill = repo / ".cursor" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\n\nbody\n", encoding="utf-8")
    git_init_repo(repo)
    git_commit_all(repo)
    module = load_module("mergecraft.context.instruction_discovery")
    discover = require_callable(module, "discover_instruction_paths")
    paths = [str(path).replace("\\", "/") for path in discover(repo)]
    assert any(path.endswith("SKILL.md") for path in paths)


def test_injected_instructions_are_hashed_into_the_run_manifest(tmp_path: Path) -> None:
    """#357 — injected instruction bytes are hashed into the run manifest."""
    module = load_module("mergecraft.context.instruction_discovery")
    hash_injected = require_callable(module, "hash_injected_instructions")
    digest = hash_injected({"AGENTS.md": "follow the service boundaries"})
    assert isinstance(digest, dict)
    assert "AGENTS.md" in digest
    assert isinstance(digest["AGENTS.md"], str)
    assert len(digest["AGENTS.md"]) == 64
    manifest_mod = load_module("mergecraft.evidence.run_manifest")
    build = require_callable(manifest_mod, "build_run_manifest")
    manifest = build(
        cwd=tmp_path,
        model="test-model",
        agent_id="reviewer",
        prompt_text="prompt",
        instruction_hashes=digest,
    )
    hashes = manifest.get("instruction_hashes") or manifest.get("hashes", {}).get("instructions")
    assert hashes == digest


def test_competing_instruction_sources_are_resolved() -> None:
    """#357 — competing instruction sources record a winner and a conflict."""
    module = load_module("mergecraft.context.instruction_discovery")
    resolve = require_callable(module, "resolve_instruction_conflicts")
    result = resolve(
        [
            {"path": "AGENTS.md", "text": "always run the full suite"},
            {"path": "GEMINI.md", "text": "never run tests"},
        ]
    )
    winner = getattr(result, "winner", None) or result.get("winner")
    conflicts = getattr(result, "conflicts", None) or result.get("conflicts")
    assert winner
    assert conflicts


def test_untrusted_gemini_renders_through_the_nonce_fence(tmp_path: Path) -> None:
    """#357 — untrusted instruction files are data, never merged into the bundle."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "GEMINI.md").write_text(_UNTRUSTED_MARKER + "\n", encoding="utf-8")
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
    repo_instructions = section_text(prompt, REPO_INSTRUCTIONS_HEADER)
    standing = section_text(prompt, STANDING_INSTRUCTIONS_HEADER)
    assert _UNTRUSTED_MARKER not in repo_instructions
    assert _UNTRUSTED_MARKER not in standing
    assert any(_UNTRUSTED_MARKER in block for block in fenced_blocks(prompt))


def test_external_context_files_enforce_type_size_trust_and_provenance(tmp_path: Path) -> None:
    """#357 — external context files have type/size/trust/provenance limits."""
    module = load_module("mergecraft.context.external_files")
    load_file = require_callable(module, "load_external_context_file")
    allowed = tmp_path / "notes.md"
    allowed.write_text("# notes\n", encoding="utf-8")
    loaded = load_file(
        allowed,
        trust_tier="untrusted",
        max_bytes=1024,
        allowed_suffixes=(".md", ".txt"),
    )
    assert getattr(loaded, "provenance", None) or loaded.get("provenance")
    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\x00\x01")
    with pytest.raises((ValueError, OSError, TypeError)):
        load_file(
            binary,
            trust_tier="untrusted",
            max_bytes=1024,
            allowed_suffixes=(".md", ".txt"),
        )
    huge = tmp_path / "huge.md"
    huge.write_text("x" * 64, encoding="utf-8")
    with pytest.raises((ValueError, OSError)):
        load_file(
            huge,
            trust_tier="untrusted",
            max_bytes=8,
            allowed_suffixes=(".md", ".txt"),
        )
