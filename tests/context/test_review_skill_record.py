"""RS1.3 — honest review-skill record (RS2, F5/F8/D12)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.context.instruction_discovery import (
    assemble_review_instruction_bundle,
    discover_review_skill_paths,
)
from mergecraft.findings.ledger import render_deterministic_review_block
from tests.context.review_skill_support import (
    INSTRUCTION_BUNDLE_BYTE_CAP,
    init_repo_with_skill,
    review_skill_record,
    seed_product_skill_noise,
    write_review_skill,
)
from tests.context.support import git_commit_all, git_init_repo

_SKILL_REL = ".github/skills/code-review/SKILL.md"
_REF_REL = ".github/skills/code-review/references/checks.md"
_SECONDARY_SKILL_REL = ".github/skills/pr-review/SKILL.md"
_SECONDARY_REF_REL = ".github/skills/pr-review/references/checks.md"
_UNTRUSTED_TIGHT_CAP_SKILL_BODY = "UNTRUSTED_TIGHT_CAP_SKILL_BODY_UNIQUE_TOKEN"
_UNTRUSTED_TIGHT_CAP_REF_BODY = "UNTRUSTED_TIGHT_CAP_REFERENCE_BODY_UNIQUE_TOKEN"
# Small but valid instructionBundleByteCap. First-pass budget accepts the skill
# and its reference; the final untrusted cap loop then pops the fenced block
# (F12). Verified on b325f6dc: 768 drops the block, 896 keeps it.
_UNTRUSTED_TIGHT_CAP = 768
_TRUSTED_CAP_PRIMARY_BODY = "TRUSTED_CAP_PRIMARY_SKILL_BODY_UNIQUE_TOKEN"
_TRUSTED_CAP_SECONDARY_BODY = "TRUSTED_CAP_SECONDARY_SKILL_BODY_UNIQUE_TOKEN"
_TRUSTED_CAP_SECONDARY_REF_BODY = "TRUSTED_CAP_SECONDARY_REFERENCE_BODY_UNIQUE_TOKEN"
# Small but valid instructionBundleByteCap. First-pass budget accepts both
# skills and records the secondary reference; the final trusted cap loop then
# pops the last review_block. Verified on 7adb3fac: 720 drops the
# secondary+ref, 896 keeps both.
_TRUSTED_TIGHT_CAP = 720
_SOLE_OVERSIZE_PREFIX = "SOLE_OVERSIZE_PRIORITY_SKILL_PREFIX_UNIQUE_TOKEN"
# Body alone exceeds this small valid instructionBundleByteCap. After
# _Budget.take reserves the truncation marker inside the limit, the sole
# review skill stays injected (12ba1ec8). On 8380c7e3 the marker was appended
# after taking ``limit`` bytes and the final cap loop popped the only
# review_block. Verified: 512 keeps heading + prefix; 400 keeps heading only.
_SOLE_OVERSIZE_CAP = 512
_SOLE_OVERSIZE_BODY = f"{_SOLE_OVERSIZE_PREFIX}\n" + ("X" * 4000)


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
    """Trusted final-cap drop must pop the skill, its refs, and the ledger.

    Calls the real loader against a fixture repo (D14). Generous-cap control
    proves the referenced secondary would be injected; the tight cap must then
    drop that skill from the prompt *and* from ``injected`` / ``references``.
    """
    repo = tmp_path / "repo"
    write_review_skill(
        repo,
        body=f"{_TRUSTED_CAP_PRIMARY_BODY}\n" + ("P" * 100) + "\n",
    )
    write_review_skill(
        repo,
        body=(
            "See [checks](references/checks.md).\n\n"
            f"{_TRUSTED_CAP_SECONDARY_BODY}\n" + ("S" * 100) + "\n"
        ),
        references={"checks.md": f"# Checks\n\n{_TRUSTED_CAP_SECONDARY_REF_BODY}\n"},
        skill_dir=repo / ".github" / "skills" / "pr-review",
    )
    git_init_repo(repo)
    sha = git_commit_all(repo)

    generous_prompt, generous = assemble_review_instruction_bundle(
        repo_root=repo,
        trust_tier="trusted",
        repo="acme/demo",
        commit_sha=sha,
        byte_cap=INSTRUCTION_BUNDLE_BYTE_CAP,
    )
    assert _TRUSTED_CAP_PRIMARY_BODY in generous_prompt
    assert _TRUSTED_CAP_SECONDARY_BODY in generous_prompt
    assert _TRUSTED_CAP_SECONDARY_REF_BODY in generous_prompt
    assert _SKILL_REL in _injected_paths(generous)
    assert _SECONDARY_SKILL_REL in _injected_paths(generous)
    assert _SECONDARY_REF_REL in _resolved_reference_paths(generous)

    prompt, record = assemble_review_instruction_bundle(
        repo_root=repo,
        trust_tier="trusted",
        repo="acme/demo",
        commit_sha=sha,
        byte_cap=_TRUSTED_TIGHT_CAP,
    )
    assert _TRUSTED_CAP_PRIMARY_BODY in prompt
    assert _TRUSTED_CAP_SECONDARY_BODY not in prompt
    assert _TRUSTED_CAP_SECONDARY_REF_BODY not in prompt
    assert any(
        "review skill dropped to honor bundle byte cap" in limitation
        for limitation in getattr(record, "limitations", ())
    )

    injected = _injected_paths(record)
    refs = _resolved_reference_paths(record)
    ledger = _ledger_review_skills(record)
    dropped = list(getattr(record, "dropped", ()))
    assert injected == [_SKILL_REL]
    assert _SECONDARY_SKILL_REL not in injected
    assert _SECONDARY_REF_REL not in refs
    assert _SECONDARY_SKILL_REL not in ledger
    assert _SECONDARY_SKILL_REL in dropped

    block = render_deterministic_review_block(
        packet=_empty_packet(),
        review_skills=ledger,
    )
    assert _SECONDARY_SKILL_REL not in block
    assert _SECONDARY_REF_REL not in block


def test_untrusted_tight_cap_dropped_skill_is_not_recorded_as_injected(
    tmp_path: Path,
) -> None:
    """F12 — a cap-dropped untrusted review skill must not be recorded as injected.

    Calls the real loader against a fixture repo (D14). Generous-cap control
    proves the skill would be quarantined into the prompt; the tight cap must
    then drop that block from *both* the prompt and the record.
    """
    repo = tmp_path / "repo"
    sha = init_repo_with_skill(
        repo,
        body=f"See [checks](references/checks.md).\n\n{_UNTRUSTED_TIGHT_CAP_SKILL_BODY}\n",
        references={"checks.md": f"# Checks\n\n{_UNTRUSTED_TIGHT_CAP_REF_BODY}\n"},
    )
    generous_prompt, generous = assemble_review_instruction_bundle(
        repo_root=repo,
        trust_tier="untrusted",
        repo="acme/demo",
        commit_sha=sha,
        byte_cap=INSTRUCTION_BUNDLE_BYTE_CAP,
    )
    assert _UNTRUSTED_TIGHT_CAP_SKILL_BODY in generous_prompt
    assert _UNTRUSTED_TIGHT_CAP_REF_BODY in generous_prompt
    assert _SKILL_REL in _injected_paths(generous)
    assert _REF_REL in _resolved_reference_paths(generous)

    prompt, record = assemble_review_instruction_bundle(
        repo_root=repo,
        trust_tier="untrusted",
        repo="acme/demo",
        commit_sha=sha,
        byte_cap=_UNTRUSTED_TIGHT_CAP,
    )
    assert _UNTRUSTED_TIGHT_CAP_SKILL_BODY not in prompt
    assert _UNTRUSTED_TIGHT_CAP_REF_BODY not in prompt
    assert any(
        "untrusted instruction dropped to honor bundle byte cap" in limitation
        for limitation in getattr(record, "limitations", ())
    )

    injected = _injected_paths(record)
    refs = _resolved_reference_paths(record)
    ledger = _ledger_review_skills(record)
    dropped = list(getattr(record, "dropped", ()))
    assert _SKILL_REL not in injected
    assert _REF_REL not in refs
    assert not any(_SKILL_REL in item for item in ledger)
    assert _SKILL_REL in dropped

    block = render_deterministic_review_block(
        packet=_empty_packet(),
        review_skills=ledger,
    )
    assert _SKILL_REL not in block
    assert "Review skills (injected):" not in block


def test_sole_oversized_priority_skill_is_truncated_and_retained(
    tmp_path: Path,
) -> None:
    """A sole oversized review skill must be truncated and kept, not dropped.

    Calls the real loader against a one-skill fixture repo (D14). No other
    instruction files. The skill body alone exceeds the tight cap; the
    assembled prompt must still name the skill, stay inside the cap, and
    record a review-skill truncation — not move the path to ``dropped``.
    """
    assert len(_SOLE_OVERSIZE_BODY.encode("utf-8")) > _SOLE_OVERSIZE_CAP
    repo = tmp_path / "repo"
    sha = init_repo_with_skill(repo, body=f"{_SOLE_OVERSIZE_BODY}\n")

    prompt, record = assemble_review_instruction_bundle(
        repo_root=repo,
        trust_tier="trusted",
        repo="acme/demo",
        commit_sha=sha,
        byte_cap=_SOLE_OVERSIZE_CAP,
    )
    heading = f"### `{_SKILL_REL}`"
    assert heading in prompt
    assert _SOLE_OVERSIZE_PREFIX in prompt
    assert len(prompt.encode("utf-8")) <= _SOLE_OVERSIZE_CAP
    assert any(
        "review skill" in limitation and "truncated" in limitation
        for limitation in getattr(record, "limitations", ())
    )

    injected = _injected_paths(record)
    dropped = list(getattr(record, "dropped", ()))
    assert _SKILL_REL in injected
    assert _SKILL_REL not in dropped


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
