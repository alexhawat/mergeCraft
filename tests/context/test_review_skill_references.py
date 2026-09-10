"""RS1.1 — review-skill reference resolution (RS2, F1/F2/F3)."""

from __future__ import annotations

from pathlib import Path

from tests.context.review_skill_support import (
    LIMITATION_MARKER,
    REFUSED_MARKER,
    init_repo_with_skill,
    render_prompt,
    review_section,
    write_review_skill,
)
from tests.context.support import fenced_blocks, git_commit_all, git_init_repo

_CHECKS_BODY = "CHECKS_REFERENCE_BODY_UNIQUE_TOKEN"
_NESTED_BODY = "NESTED_REFERENCE_BODY_UNIQUE_TOKEN"


def test_review_skill_references_are_resolved_into_the_prompt(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = init_repo_with_skill(
        repo,
        body="Follow [checks](references/checks.md).\n",
        references={"checks.md": f"# Checks\n\n{_CHECKS_BODY}\n"},
    )
    prompt = render_prompt(repo, commit_sha=sha)
    section = review_section(prompt)
    assert _CHECKS_BODY in section


def test_reference_resolution_is_one_level_deep(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = init_repo_with_skill(
        repo,
        body="See [a](references/a.md).\n",
        references={
            "a.md": "Link to [b](references/b.md).\n",
            "b.md": f"# B\n\n{_NESTED_BODY}\n",
        },
    )
    prompt = render_prompt(repo, commit_sha=sha)
    section = review_section(prompt)
    assert "Link to [b](references/b.md)." in section or "references/a.md" in section
    assert _NESTED_BODY not in section


def test_reference_outside_the_skill_directory_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    outside = repo / "REVIEW-CHECKS.md"
    outside.write_text("# Outside\n\nOUTSIDE_DOCTRINE_BODY\n", encoding="utf-8")
    sha = init_repo_with_skill(
        repo,
        body="Follow [REVIEW-CHECKS.md](../../../REVIEW-CHECKS.md).\n",
    )
    prompt = render_prompt(repo, commit_sha=sha)
    section = review_section(prompt)
    assert "OUTSIDE_DOCTRINE_BODY" not in section
    record = _load_record(repo)
    assert _refusal_recorded(record, "../../../REVIEW-CHECKS.md")


def test_absolute_and_traversal_paths_are_refused(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    secret = repo / "secret.txt"
    secret.write_text("SECRET_BODY\n", encoding="utf-8")
    link_body = (
        "See [/etc/passwd](/etc/passwd), "
        "[encoded](../..%2fsecret.txt), "
        "and [escape](references/escape.md).\n"
    )
    skill_dir = write_review_skill(repo, body=link_body)
    escape = skill_dir / "references" / "escape.md"
    escape.parent.mkdir(parents=True, exist_ok=True)
    outside = repo / "outside.txt"
    outside.write_text("OUTSIDE_ESCAPE_BODY\n", encoding="utf-8")
    escape.symlink_to(outside)
    git_init_repo(repo)
    sha = git_commit_all(repo)
    prompt = render_prompt(repo, commit_sha=sha)
    section = review_section(prompt)
    assert "SECRET_BODY" not in section
    assert "OUTSIDE_ESCAPE_BODY" not in section
    record = _load_record(repo)
    assert _refusal_recorded(record, "/etc/passwd")
    assert _refusal_recorded(record, "..%2f")


def test_reference_resolution_respects_the_byte_cap(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    huge = "X" * 120_000
    sha = init_repo_with_skill(
        repo,
        body="See [checks](references/checks.md).\n",
        references={"checks.md": f"# Huge\n\n{huge}\n"},
    )
    prompt = render_prompt(repo, commit_sha=sha, byte_cap=4096)
    section = review_section(prompt)
    assert "X" * 120_000 not in section
    assert LIMITATION_MARKER.casefold() in prompt.casefold()


def test_only_review_tier_skills_resolve_references(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    generic = repo / ".cursor" / "skills" / "demo"
    generic.mkdir(parents=True)
    (generic / "SKILL.md").write_text(
        "---\nname: demo\n---\n\nSee [checks](references/checks.md).\n",
        encoding="utf-8",
    )
    (generic / "references").mkdir(parents=True)
    (generic / "references" / "checks.md").write_text(
        f"# Generic\n\n{_CHECKS_BODY}\n",
        encoding="utf-8",
    )
    sha = init_repo_with_skill(
        repo,
        body="See [checks](references/checks.md).\n",
        references={"checks.md": "REVIEW_TIER_REFERENCE\n"},
    )
    prompt = render_prompt(repo, commit_sha=sha)
    assert "REVIEW_TIER_REFERENCE" in review_section(prompt)
    assert _CHECKS_BODY not in prompt


def test_untrusted_review_skill_references_render_inside_the_fence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    marker = "UNTRUSTED_REFERENCE_MARKER"
    sha = init_repo_with_skill(
        repo,
        body="See [checks](references/checks.md).\n",
        references={"checks.md": f"# Checks\n\n{marker}\n"},
    )
    prompt = render_prompt(repo, trust_tier="untrusted", commit_sha=sha)
    assert marker not in review_section(prompt)
    blocks = fenced_blocks(prompt)
    assert blocks, "expected untrusted fence blocks"
    joined = "\n".join(blocks)
    assert marker in joined
    assert "references/checks.md" in joined or marker in joined


def test_missing_reference_is_a_recorded_limitation_not_a_silent_drop(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    sha = init_repo_with_skill(
        repo,
        body="See [missing](references/missing.md).\n",
    )
    prompt = render_prompt(repo, commit_sha=sha)
    assert "missing.md" in prompt or "missing" in prompt
    record = _load_record(repo)
    assert _limitation_recorded(record, "references/missing.md")


def _load_record(repo: Path):
    from tests.context.review_skill_support import review_skill_record

    return review_skill_record(repo)


def _refusal_recorded(record: object, fragment: str) -> bool:
    text = str(record)
    return REFUSED_MARKER.casefold() in text.casefold() and fragment in text


def _limitation_recorded(record: object, fragment: str) -> bool:
    text = str(record)
    return LIMITATION_MARKER.casefold() in text.casefold() and fragment in text
