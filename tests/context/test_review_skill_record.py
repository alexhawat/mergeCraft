"""RS1.3 — honest review-skill record (RS2, F5/F8/D12)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.context.instruction_discovery import discover_review_skill_paths
from mergecraft.findings.ledger import render_deterministic_review_block
from tests.context.review_skill_support import (
    init_repo_with_skill,
    review_skill_record,
    seed_product_skill_noise,
    write_review_skill,
)
from tests.context.support import git_commit_all, git_init_repo


def test_record_lists_injected_skills_not_discovered_ones(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    seed_product_skill_noise(repo)
    init_repo_with_skill(repo, body="Injected review skill.\n")
    discovered = [path.relative_to(repo).as_posix() for path in discover_review_skill_paths(repo)]
    assert discovered == [".github/skills/code-review/SKILL.md"]
    record = review_skill_record(repo)
    injected = _injected_paths(record)
    assert injected == [".github/skills/code-review/SKILL.md"]
    assert "skills/mergecraft/SKILL.md" not in injected


def test_record_lists_resolved_reference_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo_with_skill(
        repo,
        body="See [checks](references/checks.md).\n",
        references={"checks.md": "# Checks\n"},
    )
    record = review_skill_record(repo)
    refs = _resolved_reference_paths(record)
    assert ".github/skills/code-review/references/checks.md" in refs


def test_quarantined_skill_is_recorded_as_quarantined(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo_with_skill(repo, body="Quarantined review skill.\n")
    record = review_skill_record(repo, trust_tier="untrusted")
    text = str(record)
    assert "quarantined" in text.casefold()
    block = render_deterministic_review_block(
        packet=_empty_packet(),
        review_skills=_ledger_review_skills(record),
    )
    assert "quarantined" in block.casefold()


def test_final_cap_pop_syncs_injected_with_dropped_review_skills(tmp_path: Path) -> None:
    """Final assembly cap enforcement must pop ``injected`` with ``review_blocks``."""
    repo = tmp_path / "repo"
    write_review_skill(repo, body="P" * 100 + "\n")
    secondary_dir = repo / ".github" / "skills" / "pr-review"
    write_review_skill(
        repo,
        body="S" * 100 + "\n",
        skill_dir=secondary_dir,
    )
    git_init_repo(repo)
    git_commit_all(repo)
    from mergecraft.context.instruction_discovery import build_review_skill_record

    record = build_review_skill_record(
        repo_root=repo,
        trust_tier="trusted",
        repo="acme/demo",
        commit_sha="fixture-sha",
        byte_cap=400,
    )
    injected = _injected_paths(record)
    dropped = list(getattr(record, "dropped", ()))
    ledger = _ledger_review_skills(record)
    assert injected == [".github/skills/code-review/SKILL.md"]
    assert ".github/skills/pr-review/SKILL.md" not in injected
    assert ".github/skills/pr-review/SKILL.md" not in ledger
    assert ".github/skills/pr-review/SKILL.md" in dropped
    assert any(
        "review skill dropped to honor bundle byte cap" in limitation
        for limitation in getattr(record, "limitations", ())
    )


def test_skill_discovered_but_dropped_by_the_cap_is_not_recorded_as_applied(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    write_review_skill(repo, body="Primary review skill.\n")
    secondary_dir = repo / ".github" / "skills" / "pr-review"
    write_review_skill(
        repo,
        body="Secondary review skill.\n",
        skill_dir=secondary_dir,
    )
    git_init_repo(repo)
    git_commit_all(repo)
    # RS2 must drop the lower-priority skill under an artificially tiny cap while
    # recording the drop — not list it as applied.
    from mergecraft.context.instruction_discovery import build_review_skill_record

    tiny = build_review_skill_record(
        repo_root=repo,
        trust_tier="trusted",
        repo="acme/demo",
        commit_sha="fixture-sha",
        byte_cap=330,
    )
    injected = _injected_paths(tiny)
    assert ".github/skills/code-review/SKILL.md" in injected
    assert ".github/skills/pr-review/SKILL.md" not in injected
    assert "dropped" in str(tiny).casefold() or "limitation" in str(tiny).casefold()


def _injected_paths(record: object) -> list[str]:
    injected = getattr(record, "injected", None)
    if injected is not None:
        return list(injected)
    extra = getattr(record, "skills", None)
    if extra is not None:
        return list(extra)
    raise AssertionError(f"record lacks injected skill paths: {record!r}")


def _resolved_reference_paths(record: object) -> list[str]:
    refs = getattr(record, "references", None)
    if refs is not None:
        return list(refs)
    resolved = getattr(record, "resolved_references", None)
    if resolved is not None:
        return list(resolved)
    raise AssertionError(f"record lacks resolved reference paths: {record!r}")


def _ledger_review_skills(record: object) -> list[str]:
    ledger = getattr(record, "ledger_review_skills", None)
    if ledger is not None:
        return list(ledger)
    return _injected_paths(record)


def _empty_packet() -> object:
    from mergecraft.evidence.build import build_packet

    return build_packet(
        change_id="acme/demo#rs1",
        agent_id="opencode",
        agent_version="0.0.1",
        model="test-model",
        files_changed=[],
        findings=[],
        deterministic_checks=[],
    )
