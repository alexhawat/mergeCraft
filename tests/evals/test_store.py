"""Pure-model tests for the eval bank store (W11.6).

The store is the **pure core** of the bank. These tests pin:

- The case schema (``Case`` model, ``LearningProvenance`` embedding).
- The parse / render round-trip.
- The front-matter validation rules (D5, D13).
- The list filter behaviour.
- The diff function between two cases.

The fixtures are **synthetic** (id-prefix ``synthetic``) so the
committed corpus never looks like a real historical failure record.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from mergecraft.evals.store import (
    CASE_FILE_SUFFIX,
    DEFAULT_BANK_DIR,
    Case,
    ReplayDiff,
    add_case,
    diff_cases,
    list_cases,
    load_case,
    parse_case_text,
    render_case_text,
)
from mergecraft.utils.learnings import LearningProvenance

# ── fixtures ───────────────────────────────────────────────────────────


def _provenance(**overrides: object) -> LearningProvenance:
    defaults: dict[str, object] = {
        "run_id": "synthetic",
        "pr_number": 1,
        "source_field": "eval_bank",
        "author_login": "synthetic",
        "author_association": "OWNER",
        "trust_tier": "trusted",
        "timestamp": datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return LearningProvenance(**defaults)  # type: ignore[arg-type]


def _case(**overrides: object) -> Case:
    defaults: dict[str, object] = {
        "id": "synthetic-001",
        "title": "missed a fabricated deletion",
        "category": "missed_finding",
        "submitted_at": datetime(2026, 8, 9, 10, 0, 0, tzinfo=UTC),
        "run_id": "synthetic",
        "pr_number": 1,
        "failure_mode": "missed_finding",
        "expected_finding": "src/mergecraft/foo.py:42-60: 'delete' on unborn file",
        "expected_decision": "block",
        "replay_command": "mergecraft eval replay synthetic-001",
        "provenance": _provenance(),
        "body": "# synthetic-001\n\ndescription\n",
    }
    defaults.update(overrides)
    return Case(**defaults)  # type: ignore[arg-type]


def _rendered(case: Case) -> str:
    return render_case_text(case)


# ── Case schema ────────────────────────────────────────────────────────


def test_case_schema_loads_minimal_payload() -> None:
    """The ``Case`` model accepts a minimal valid payload."""
    case = _case()
    assert case.id == "synthetic-001"
    assert case.expected_decision == "block"
    assert case.provenance.trust_tier == "trusted"


def test_case_schema_rejects_extra_fields() -> None:
    """``extra="forbid"`` is the locked invariant on the case model."""
    with pytest.raises(ValidationError):
        _case(unknown="nope")  # type: ignore[call-arg]


def test_case_schema_rejects_unknown_verb() -> None:
    """``expected_decision`` must be in the verdict vocabulary."""
    with pytest.raises(ValidationError):
        _case(expected_decision="definitely-not-a-verdict")


def test_case_schema_rejects_empty_id() -> None:
    """The case id is non-empty by construction."""
    with pytest.raises(ValidationError):
        _case(id="")


def test_case_schema_rejects_invalid_trust_tier() -> None:
    """The embedded ``LearningProvenance`` enforces tier='trusted'/'untrusted'."""
    with pytest.raises(ValidationError):
        _case(provenance=_provenance(trust_tier="bogus"))  # type: ignore[arg-type]


def test_case_extra_forbid_invariant_documented() -> None:
    """The model config advertises ``extra="forbid"``.

    The cross-file contract in ``docs/test-plans/cross-file-deps.md``
    pins this as the invariant that protects the security plan's
    contract from silent drift.
    """
    assert Case.model_config.get("extra") == "forbid"


def test_is_synthetic_helper() -> None:
    """``Case.is_synthetic`` returns True for the synthetic prefix."""
    assert _case(id="synthetic-007").is_synthetic is True
    assert _case(id="real-001").is_synthetic is False


# ── parse / render round-trip ──────────────────────────────────────────


def test_parse_round_trip_preserves_every_field() -> None:
    """A case rendered to text and parsed back equals the original."""
    case = _case()
    text = _rendered(case)
    parsed = parse_case_text(Path("synthetic-001.md"), text)
    assert parsed == case


def test_parse_round_trip_preserves_provenance() -> None:
    """Round-trip preserves the embedded ``LearningProvenance``."""
    case = _case(provenance=_provenance(author_login="alice", pr_number=42))
    text = _rendered(case)
    parsed = parse_case_text(Path("synthetic-001.md"), text)
    assert parsed.provenance == case.provenance
    assert parsed.provenance.author_login == "alice"
    assert parsed.provenance.pr_number == 42


def test_parse_round_trip_preserves_body() -> None:
    """The body is preserved verbatim through the round-trip."""
    body = "# synthetic-001\n\nThe agent missed a `delete` on an unborn file.\n"
    case = _case(body=body)
    text = _rendered(case)
    parsed = parse_case_text(Path("synthetic-001.md"), text)
    assert parsed.body == body


def test_parse_rejects_missing_front_matter() -> None:
    """A file without an opening ``---`` line is rejected."""
    with pytest.raises(ValueError, match="front-matter"):
        parse_case_text(Path("synthetic-001.md"), "no front matter here\n")


def test_parse_rejects_missing_closing_delimiter() -> None:
    """A file with only an opening ``---`` line is rejected."""
    with pytest.raises(ValueError, match="closing"):
        parse_case_text(Path("synthetic-001.md"), "---\nid: x\n")


def test_parse_rejects_missing_required_field() -> None:
    """A front matter missing a required field is rejected."""
    raw = (
        "---\n"
        "id: synthetic-001\n"
        "title: missed finding\n"
        # category missing
        "submitted_at: 2026-08-09T10:00:00Z\n"
        "run_id: synthetic\n"
        "pr_number: 1\n"
        "failure_mode: missed_finding\n"
        "expected_finding: src/mergecraft/foo.py:42\n"
        "expected_decision: block\n"
        "replay_command: 'mergecraft eval replay synthetic-001'\n"
        "provenance:\n"
        "  run_id: synthetic\n"
        "  pr_number: 1\n"
        "  source_field: eval_bank\n"
        "  author_login: synthetic\n"
        "  author_association: OWNER\n"
        "  trust_tier: trusted\n"
        "  timestamp: 2026-08-09T10:00:00Z\n"
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match="missing required fields"):
        parse_case_text(Path("synthetic-001.md"), raw)


def test_parse_rejects_unknown_expected_decision() -> None:
    """``expected_decision`` outside the verdict vocabulary is rejected."""
    raw = (
        "---\n"
        "id: synthetic-001\n"
        "title: t\n"
        "category: missed_finding\n"
        "submitted_at: 2026-08-09T10:00:00Z\n"
        "run_id: synthetic\n"
        "pr_number: 1\n"
        "failure_mode: missed_finding\n"
        "expected_finding: x\n"
        "expected_decision: ship-it\n"
        "replay_command: 'r'\n"
        "provenance:\n"
        "  run_id: synthetic\n"
        "  pr_number: 1\n"
        "  source_field: eval_bank\n"
        "  author_login: synthetic\n"
        "  author_association: OWNER\n"
        "  trust_tier: trusted\n"
        "  timestamp: 2026-08-09T10:00:00Z\n"
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match="verdict"):
        parse_case_text(Path("synthetic-001.md"), raw)


def test_parse_rejects_missing_provenance() -> None:
    """A front matter without a provenance record is rejected (D5)."""
    raw = (
        "---\n"
        "id: synthetic-001\n"
        "title: t\n"
        "category: missed_finding\n"
        "submitted_at: 2026-08-09T10:00:00Z\n"
        "run_id: synthetic\n"
        "pr_number: 1\n"
        "failure_mode: missed_finding\n"
        "expected_finding: x\n"
        "expected_decision: block\n"
        "replay_command: 'r'\n"
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match="provenance"):
        parse_case_text(Path("synthetic-001.md"), raw)


def test_parse_rejects_invalid_provenance() -> None:
    """A malformed provenance record is rejected."""
    raw = (
        "---\n"
        "id: synthetic-001\n"
        "title: t\n"
        "category: missed_finding\n"
        "submitted_at: 2026-08-09T10:00:00Z\n"
        "run_id: synthetic\n"
        "pr_number: 1\n"
        "failure_mode: missed_finding\n"
        "expected_finding: x\n"
        "expected_decision: block\n"
        "replay_command: 'r'\n"
        "provenance:\n"
        "  run_id: synthetic\n"
        "  source_field: eval_bank\n"
        "  author_login: synthetic\n"
        "  trust_tier: trusted\n"
        "  timestamp: not-a-real-timestamp\n"
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match="provenance"):
        parse_case_text(Path("synthetic-001.md"), raw)


def test_parse_rejects_invalid_id() -> None:
    """An id outside the locked identifier shape is rejected."""
    raw = (
        "---\n"
        "id: 'has spaces'\n"
        "title: t\n"
        "category: missed_finding\n"
        "submitted_at: 2026-08-09T10:00:00Z\n"
        "run_id: synthetic\n"
        "pr_number: 1\n"
        "failure_mode: missed_finding\n"
        "expected_finding: x\n"
        "expected_decision: block\n"
        "replay_command: 'r'\n"
        "provenance:\n"
        "  run_id: synthetic\n"
        "  pr_number: 1\n"
        "  source_field: eval_bank\n"
        "  author_login: synthetic\n"
        "  author_association: OWNER\n"
        "  trust_tier: trusted\n"
        "  timestamp: 2026-08-09T10:00:00Z\n"
        "---\n"
        "body\n"
    )
    with pytest.raises(ValueError, match="not a valid identifier"):
        parse_case_text(Path("synthetic-001.md"), raw)


# ── add_case / list_cases / load_case ──────────────────────────────────


def test_add_case_persists_to_disk(tmp_path: Path) -> None:
    """``add_case`` writes a file under ``bank_dir`` with the locked shape."""
    case = _case()
    target = add_case(tmp_path, case)
    assert (
        target == tmp_path / "case.synthetic-001.md"
        or target == tmp_path / f"synthetic-001{CASE_FILE_SUFFIX}"
    )
    assert target.is_file()
    # Round-trip via the file system.
    loaded = load_case(target)
    assert loaded == case


def test_add_case_refuses_overwrite_without_flag(tmp_path: Path) -> None:
    """``add_case`` raises ``FileExistsError`` when the case already exists."""
    case = _case()
    add_case(tmp_path, case)
    with pytest.raises(FileExistsError):
        add_case(tmp_path, case)


def test_add_case_overwrites_when_flagged(tmp_path: Path) -> None:
    """``add_case(overwrite=True)`` replaces the existing case."""
    case = _case()
    add_case(tmp_path, case)
    case_v2 = _case(body="updated")
    target = add_case(tmp_path, case_v2, overwrite=True)
    assert load_case(target).body == "updated"


def test_add_case_creates_missing_directory(tmp_path: Path) -> None:
    """``add_case`` creates ``bank_dir`` when it does not exist."""
    target_dir = tmp_path / "deep" / "nested" / "bank"
    case = _case()
    target = add_case(target_dir, case)
    assert target_dir.is_dir()
    assert target.is_file()


def test_list_cases_returns_all_when_no_filters(tmp_path: Path) -> None:
    """``list_cases`` returns every case in the bank."""
    add_case(tmp_path, _case(id="synthetic-001"))
    add_case(
        tmp_path,
        _case(
            id="synthetic-002",
            submitted_at=datetime(2026, 8, 9, 11, 0, 0, tzinfo=UTC),
        ),
    )
    cases = list_cases(tmp_path)
    assert [c.id for c in cases] == ["synthetic-001", "synthetic-002"]


def test_list_cases_filters_by_category(tmp_path: Path) -> None:
    """``list_cases(category=...)`` filters by exact category."""
    add_case(tmp_path, _case(id="synthetic-001", category="missed_finding"))
    add_case(
        tmp_path,
        _case(
            id="synthetic-002",
            category="false_positive",
            submitted_at=datetime(2026, 8, 9, 11, 0, 0, tzinfo=UTC),
        ),
    )
    cases = list_cases(tmp_path, category="missed_finding")
    assert [c.id for c in cases] == ["synthetic-001"]


def test_list_cases_filters_by_since(tmp_path: Path) -> None:
    """``list_cases(since=...)`` filters by ``submitted_at``."""
    add_case(
        tmp_path,
        _case(id="synthetic-001", submitted_at=datetime(2026, 7, 1, tzinfo=UTC)),
    )
    add_case(
        tmp_path,
        _case(id="synthetic-002", submitted_at=datetime(2026, 8, 9, 11, 0, 0, tzinfo=UTC)),
    )
    cutoff = datetime(2026, 8, 1, tzinfo=UTC)
    cases = list_cases(tmp_path, since=cutoff)
    assert [c.id for c in cases] == ["synthetic-002"]


def test_list_cases_filters_by_id_prefix(tmp_path: Path) -> None:
    """``list_cases(id_prefix=...)`` filters by id prefix."""
    add_case(tmp_path, _case(id="synthetic-001"))
    add_case(
        tmp_path,
        _case(
            id="real-001",
            submitted_at=datetime(2026, 8, 9, 11, 0, 0, tzinfo=UTC),
        ),
    )
    cases = list_cases(tmp_path, id_prefix="synthetic")
    assert [c.id for c in cases] == ["synthetic-001"]


def test_list_cases_returns_empty_when_bank_missing(tmp_path: Path) -> None:
    """``list_cases`` returns ``[]`` when the bank directory does not exist."""
    assert list_cases(tmp_path / "missing") == []


def test_list_cases_skips_malformed_without_raising(tmp_path: Path) -> None:
    """A malformed case file is skipped, not raised."""
    add_case(tmp_path, _case(id="synthetic-good"))
    bad = tmp_path / "synthetic-bad.md"
    bad.write_text("not a real case file", encoding="utf-8")
    cases = list_cases(tmp_path)
    assert [c.id for c in cases] == ["synthetic-good"]


# ── DEFAULT_BANK_DIR ───────────────────────────────────────────────────


def test_default_bank_dir_is_evals_cases() -> None:
    """The default bank directory is ``evals/cases/`` (D13)."""
    assert Path("evals") / "cases" == DEFAULT_BANK_DIR


# ── diff_cases ─────────────────────────────────────────────────────────


def test_diff_cases_reports_equal_when_identical() -> None:
    """Two identical cases produce an empty diff."""
    case = _case()
    assert diff_cases(case, case) == {}


def test_diff_cases_reports_field_level_drift() -> None:
    """Unequal fields are reported as ``expected`` vs ``got``."""
    a = _case(title="missed a fabricated deletion")
    b = _case(title="missed a different failure")
    diff = diff_cases(a, b)
    assert "title" in diff
    assert diff["title"] == {
        "expected": "missed a fabricated deletion",
        "got": "missed a different failure",
    }


def test_diff_cases_reports_provenance_drift() -> None:
    """Provenance drift is reported as the structured Pydantic dump."""
    a = _case(provenance=_provenance(author_login="alice"))
    b = _case(provenance=_provenance(author_login="bob"))
    diff = diff_cases(a, b)
    assert "provenance" in diff
    assert diff["provenance"]["expected"]["author_login"] == "alice"
    assert diff["provenance"]["got"]["author_login"] == "bob"


def test_diff_cases_reports_body_drift() -> None:
    """Body drift is reported as the raw strings."""
    a = _case(body="first")
    b = _case(body="second")
    diff = diff_cases(a, b)
    assert diff["body"] == {"expected": "first", "got": "second"}


# ── ReplayDiff model ───────────────────────────────────────────────────


def test_replay_diff_rejects_extra_fields() -> None:
    """``ReplayDiff`` is also ``extra="forbid"`` — the diff is the contract."""
    with pytest.raises(ValidationError):
        ReplayDiff(
            case_id="synthetic-001",
            expected_decision="block",
            current_decision="block",
            status="passed",
            not_a_field=True,  # type: ignore[call-arg]
        )
