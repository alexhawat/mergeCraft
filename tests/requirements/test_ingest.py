"""Behavioral suite for ``requirements/ingest.py`` (plan 29 T3 / #768).

The previous pin read the module's source text; ``ingest_requirements()`` and
its helpers (``_state_for``, ``_is_negative_requirement``, ``_kind_for``,
``_resolve_body``, ``_stable_id``) had never run against a fixture. These tests
drive the public entry point and observe ``IngestResult`` / ``Requirement``
outcomes: stable ids, kinds, states from evidence and scope, nonce fencing, and
the source-resolution precedence order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.requirements.criteria import ChangeMap
from mergecraft.requirements.ingest import (
    IngestResult,
    RequirementState,
    ingest_requirements,
)

if TYPE_CHECKING:
    from pathlib import Path

_BODY = (
    "## Acceptance criteria\n"
    "\n"
    "- [ ] login works\n"
    "- [ ] must not log login credentials\n"
    "- [ ] backwards compatible response shape\n"
)


def _code_change_map() -> ChangeMap:
    return ChangeMap(changed_paths=("src/login.py",), touched_symbols=("login",))


# ── extraction, ids, kinds ─────────────────────────────────────────────


def test_ingest_returns_stable_ordered_ids_and_kinds() -> None:
    result = ingest_requirements(source="local_spec", text=_BODY)

    assert isinstance(result, IngestResult)
    assert result.source == "local_spec"
    assert result.source_ref == "local_spec"
    assert [req.requirement_id for req in result.requirements] == [
        "REQ-001",
        "REQ-002",
        "REQ-003",
    ]
    assert [req.text for req in result.requirements] == [
        "login works",
        "must not log login credentials",
        "backwards compatible response shape",
    ]
    assert [req.kind for req in result.requirements] == [
        "acceptance",
        "constraint",
        "compatibility",
    ]
    assert all(req.source == "local_spec" for req in result.requirements)


def test_ingest_fences_external_text_with_one_shared_nonce() -> None:
    result = ingest_requirements(source="linked_issue", text=_BODY)

    fenced = result.fenced_text
    assert fenced.startswith("<<<UNTRUSTED-MERGECRAFT-CONTENT ")
    assert fenced.endswith(">>>")
    assert "field=linked_issue" in fenced
    assert "tier=untrusted" in fenced
    nonce = fenced.split("nonce=", 1)[1].split(" ", 1)[0]
    assert len(nonce) == 16
    assert f"<<<END-UNTRUSTED-MERGECRAFT-CONTENT nonce={nonce}>>>" in fenced
    assert all(req.fenced_source == fenced for req in result.requirements)


def test_only_bullets_inside_the_acceptance_section_are_ingested() -> None:
    body = "- [ ] outside the section\n## Acceptance criteria\n- [ ] inside the section\n"

    result = ingest_requirements(source="local_spec", text=body)

    assert [req.text for req in result.requirements] == ["inside the section"]


def test_empty_body_yields_no_requirements_and_still_fences() -> None:
    result = ingest_requirements(source="local_spec")

    assert result.requirements == ()
    assert result.source_ref == "local_spec"
    assert "<<<UNTRUSTED-MERGECRAFT-CONTENT" in result.fenced_text


# ── states from evidence and scope ─────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected_state"),
    [
        ("- [ ] login works\n", RequirementState.PARTIALLY_SATISFIED),
        ("- [ ] must not log login credentials\n", RequirementState.CONTRADICTED),
        ("- [ ] backwards compatible response shape\n", RequirementState.OUT_OF_SCOPE),
    ],
)
def test_state_from_code_evidence_and_scope(text: str, expected_state: RequirementState) -> None:
    result = ingest_requirements(source="local_spec", text=text, change_map=_code_change_map())

    assert result.requirements[0].state is expected_state


def test_test_evidence_is_satisfied() -> None:
    result = ingest_requirements(
        source="local_spec",
        text="- [ ] login works\n",
        change_map=ChangeMap(changed_paths=("tests/test_login.py",), touched_symbols=("login",)),
    )

    requirement = result.requirements[0]
    assert requirement.state is RequirementState.SATISFIED
    assert requirement.evidence_paths == ("tests/test_login.py",)


def test_without_a_change_map_every_requirement_is_not_evidenced() -> None:
    result = ingest_requirements(source="local_spec", text=_BODY)

    assert {req.state for req in result.requirements} == {RequirementState.NOT_EVIDENCED}


# ── source resolution ──────────────────────────────────────────────────


def test_unknown_source_is_rejected_before_any_extraction() -> None:
    with pytest.raises(ValueError, match="unknown requirement source 'not-a-source'"):
        ingest_requirements(source="not-a-source", text=_BODY)


@pytest.mark.parametrize(
    "source",
    ["pr_description", "linked_issue", "local_spec", "jira", "linear", "adr"],
)
def test_named_sources_are_accepted(source: str) -> None:
    result = ingest_requirements(source=source, text="- [ ] login works\n")

    assert result.source == source
    assert [req.text for req in result.requirements] == ["login works"]


def test_explicit_text_wins_over_pr_description() -> None:
    result = ingest_requirements(
        source="pr_description",
        text="- [ ] from explicit text\n",
        pr_description="## Acceptance criteria\n- [ ] from pr body\n",
    )

    assert [req.text for req in result.requirements] == ["from explicit text"]
    assert "from pr body" not in result.fenced_text
    assert result.source_ref == "pr_description"


def test_pr_description_used_when_text_absent() -> None:
    result = ingest_requirements(
        source="pr_description",
        pr_description="## Acceptance criteria\n- [ ] from pr body\n",
    )

    assert [req.text for req in result.requirements] == ["from pr body"]
    assert result.source_ref == "pr_description"


def test_linked_issue_used_when_text_absent() -> None:
    result = ingest_requirements(source="linked_issue", linked_issue="- [ ] from issue\n")

    assert [req.text for req in result.requirements] == ["from issue"]
    assert result.source_ref == "linked_issue"


def test_local_spec_reads_spec_md_from_repo_root(tmp_path: Path) -> None:
    (tmp_path / "SPEC.md").write_text(
        "## Acceptance criteria\n- [ ] from spec file\n", encoding="utf-8"
    )

    result = ingest_requirements(source="local_spec", repo_root=tmp_path)

    assert [req.text for req in result.requirements] == ["from spec file"]
    assert result.source_ref == "SPEC.md"


def test_root_spec_md_wins_over_docs_spec(tmp_path: Path) -> None:
    (tmp_path / "SPEC.md").write_text("- [ ] root spec\n", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "SPEC.md").write_text("- [ ] docs spec\n", encoding="utf-8")

    result = ingest_requirements(source="local_spec", repo_root=tmp_path)

    assert [req.text for req in result.requirements] == ["root spec"]
    assert result.source_ref == "SPEC.md"


def test_adr_falls_back_to_docs_adr(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-decision.md").write_text("- [ ] adopted decision\n", encoding="utf-8")

    result = ingest_requirements(source="adr", repo_root=tmp_path)

    assert [req.text for req in result.requirements] == ["adopted decision"]
    assert result.source_ref == "docs/adr/0001-decision.md"


def test_local_spec_without_files_yields_empty_requirements(tmp_path: Path) -> None:
    result = ingest_requirements(source="local_spec", repo_root=tmp_path)

    assert result.requirements == ()
    assert result.source_ref == "local_spec"


__all__: list[str] = []
