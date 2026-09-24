"""Strict preparation contract for the first human golden-case batch (#780).

Two properties hold before, during and after Alex's decisions: the manifest
attributes every non-pending row to its named adjudicator, and the authoring
corpus objects carry human provenance *if and only if* a row has been confirmed
or corrected with recovered evidence. The second is the agreement guard: the
tooling records no identity, so nothing else connects a manifest decision to the
corpus object it authorises.
"""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.evals.corpora import CorpusCase
from mergecraft.evals.human_batch import (
    GOLDEN_BATCH_001_CASE_IDS,
    HumanBatchCase,
    HumanBatchManifest,
    load_human_batch,
    render_review_sheet,
    verify_corrected_cases,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "evals" / "adjudication" / "golden-batch-001.json"
#: The one case the RED case mutates; it exists in both corpora trees.
_MUTATED_CASE_ID = "golden-python-django-migration-001"


def _manifest_payload() -> dict[str, object]:
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _first_case(payload: dict[str, object]) -> dict[str, object]:
    cases = payload["cases"]
    assert isinstance(cases, list)
    row = cases[0]
    assert isinstance(row, dict)
    return row


def _reset_to_pending(row: dict[str, object]) -> dict[str, object]:
    """Return ``row`` to the undecided state, whatever the committed decision is."""
    row.update(decision="pending", decided_at=None, decided_by=None, corrected_fields=None)
    return row


def _load_committed_manifest() -> HumanBatchManifest:
    return load_human_batch(_MANIFEST_PATH, repo_root=_REPO_ROOT)


def _manifest_with_pending_row(case_id: str) -> HumanBatchManifest:
    """The committed manifest with ``case_id`` forced back to ``pending``."""
    payload = _manifest_payload()
    cases = payload["cases"]
    assert isinstance(cases, list)
    row = next(row for row in cases if row["case_id"] == case_id)
    _reset_to_pending(row)
    return HumanBatchManifest.model_validate(payload)


def _authoring_case_path(case_id: str, *, repo_root: Path) -> Path:
    return repo_root / "evals" / "cases" / "golden" / f"{case_id}.json"


def _load_authoring_case(case_id: str, *, repo_root: Path) -> CorpusCase:
    return CorpusCase.model_validate_json(
        _authoring_case_path(case_id, repo_root=repo_root).read_text(encoding="utf-8")
    )


def _copy_authoring_golden_cases(tmp_path: Path) -> Path:
    """Copy every authoring golden object into a throwaway ``evals/`` layout."""
    target = tmp_path / "evals" / "cases" / "golden"
    target.mkdir(parents=True)
    for case_id in GOLDEN_BATCH_001_CASE_IDS:
        source = _authoring_case_path(case_id, repo_root=_REPO_ROOT)
        (target / f"{case_id}.json").write_bytes(source.read_bytes())
    return target


def _row_claims_human_provenance(row: HumanBatchCase) -> bool:
    """A row authorises human provenance only when confirmed/corrected and recovered."""
    return row.decision in {"confirm", "correct"} and row.evidence_status == "recovered"


def _assert_row_and_corpus_agree(row: HumanBatchCase, case: CorpusCase) -> None:
    """The agreement guard: human provenance iff a recovered confirm/correct row.

    Raises:
        AssertionError: Naming the case ID and the distinguishing field whenever
            the manifest row and the authoring corpus object disagree.
    """
    adjudication = case.adjudication
    claims_human = _row_claims_human_provenance(row)
    carries_human = (
        case.provenance == "human"
        and adjudication is not None
        and adjudication.adjudicated_by == "human"
        and adjudication.independence == "independent"
    )
    if claims_human and not carries_human:
        raise AssertionError(
            f"{row.case_id}: manifest decision={row.decision!r} with "
            f"evidence_status={row.evidence_status!r} requires corpus "
            f"provenance='human' and an independent human adjudication, but the "
            f"authoring case carries provenance={case.provenance!r} and "
            f"adjudication={adjudication!r}"
        )
    if carries_human and not claims_human:
        raise AssertionError(
            f"{row.case_id}: the authoring case carries provenance={case.provenance!r} "
            f"and adjudication={adjudication!r}, but its manifest row is "
            f"decision={row.decision!r} with evidence_status={row.evidence_status!r}"
        )
    if not claims_human and (case.provenance == "human" or adjudication is not None):
        raise AssertionError(
            f"{row.case_id}: the manifest row is decision={row.decision!r} with "
            f"evidence_status={row.evidence_status!r}, so the authoring case must "
            f"carry neither provenance nor adjudication, but it carries "
            f"provenance={case.provenance!r} and adjudication={adjudication!r}"
        )


def _assert_manifest_corpus_agreement(manifest: HumanBatchManifest, *, repo_root: Path) -> None:
    for row in manifest.cases:
        _assert_row_and_corpus_agree(row, _load_authoring_case(row.case_id, repo_root=repo_root))


def test_manifest_names_the_nine_and_attributes_every_decision() -> None:
    manifest = _load_committed_manifest()
    assert manifest.adjudicator_login == "alexhawat"
    assert {row.case_id for row in manifest.cases} == set(GOLDEN_BATCH_001_CASE_IDS)
    assert len(manifest.cases) == 9
    for row in manifest.cases:
        if row.decision == "pending":
            assert row.decided_by is None
            assert row.decided_at is None
        else:
            assert row.decided_by == manifest.adjudicator_login
            assert row.decided_at is not None


@pytest.mark.parametrize("case_id", GOLDEN_BATCH_001_CASE_IDS)
def test_manifest_row_and_authoring_case_agree_on_human_provenance(case_id: str) -> None:
    manifest = _load_committed_manifest()
    row = next(row for row in manifest.cases if row.case_id == case_id)
    _assert_row_and_corpus_agree(row, _load_authoring_case(case_id, repo_root=_REPO_ROOT))


def test_manifest_and_authoring_corpus_agree_across_the_whole_batch() -> None:
    _assert_manifest_corpus_agreement(_load_committed_manifest(), repo_root=_REPO_ROOT)


def test_correct_rows_match_their_corrected_corpus_fields() -> None:
    manifest = _load_committed_manifest()
    for row in manifest.cases:
        if row.decision != "correct":
            continue
        assert row.corrected_fields is not None
        case = _load_authoring_case(row.case_id, repo_root=_REPO_ROOT)
        supplied = row.corrected_fields.model_dump(exclude_none=True)
        for field, expected in supplied.items():
            assert getattr(case, field) == expected, f"{row.case_id}: {field}"


def test_review_sheet_marks_only_pending_rows_unanswered() -> None:
    manifest = _load_committed_manifest()
    sheet = render_review_sheet(manifest, repo_root=_REPO_ROOT)
    row_lines = [line for line in sheet.splitlines() if line.startswith("| golden-")]
    assert len(row_lines) == 9
    lines_by_id = {line.split("|")[1].strip(): line for line in row_lines}
    assert list(lines_by_id) == sorted(GOLDEN_BATCH_001_CASE_IDS)
    for row in manifest.cases:
        line = lines_by_id[row.case_id]
        if row.decision == "pending":
            assert "UNANSWERED" in line
        else:
            assert "UNANSWERED" not in line
            assert f"{row.decision} by {row.decided_by}" in line
    assert "Severity" not in sheet


def test_adjudicating_a_pending_case_breaks_the_agreement_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The RED case: the CLI can add provenance the manifest never authorised."""
    manifest = _manifest_with_pending_row(_MUTATED_CASE_ID)
    case_dir = _copy_authoring_golden_cases(tmp_path)
    target = case_dir / f"{_MUTATED_CASE_ID}.json"

    # The untouched copy is green, so a failure below is the mutation's doing.
    _assert_manifest_corpus_agreement(manifest, repo_root=tmp_path)

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        ["eval", "adjudicate", str(target), "--id", _MUTATED_CASE_ID, "--by", "human"],
    )
    assert result.exit_code == 0, result.output

    payload = json.loads(target.read_text(encoding="utf-8"))
    # Assert the distinguishing field, not mere absence: the corpus object now
    # claims independent human provenance while its manifest row is pending.
    assert payload["provenance"] == "human"
    assert payload["adjudication"]["adjudicated_by"] == "human"
    row = next(row for row in manifest.cases if row.case_id == _MUTATED_CASE_ID)
    assert row.decision == "pending"

    with pytest.raises(AssertionError) as excinfo:
        _assert_manifest_corpus_agreement(manifest, repo_root=tmp_path)
    message = str(excinfo.value)
    assert _MUTATED_CASE_ID in message
    assert "provenance" in message


def test_manifest_forbids_unknown_fields() -> None:
    payload = _manifest_payload()
    _first_case(payload)["invented"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        HumanBatchManifest.model_validate(payload)


def test_manifest_requires_exactly_the_frozen_nine_case_ids() -> None:
    payload = _manifest_payload()
    cases = payload["cases"]
    assert isinstance(cases, list)
    cases.pop()
    with pytest.raises(ValidationError, match="exactly the nine"):
        HumanBatchManifest.model_validate(payload)


def test_missing_evidence_cannot_carry_a_source_or_fixture() -> None:
    payload = _manifest_payload()
    _first_case(payload)["source_url"] = (
        "https://github.com/example/project/blob/0123456789abcdef0123456789abcdef01234567/file.py"
    )
    with pytest.raises(ValidationError, match="must leave source and fixture fields null"):
        HumanBatchManifest.model_validate(payload)


def test_recovered_evidence_requires_an_immutable_source_or_fixture() -> None:
    payload = _manifest_payload()
    _first_case(payload)["evidence_status"] = "recovered"
    with pytest.raises(ValidationError, match="requires an immutable source URL or fixture"):
        HumanBatchManifest.model_validate(payload)


def test_mutable_source_url_is_rejected() -> None:
    payload = _manifest_payload()
    row = _first_case(payload)
    row["evidence_status"] = "recovered"
    row["source_url"] = (
        "https://github.com/example/project/blob/main/file.py?commit="
        "0123456789abcdef0123456789abcdef01234567"
    )
    with pytest.raises(ValidationError, match="must pin a GitHub blob or commit path"):
        HumanBatchManifest.model_validate(payload)


def test_pending_decision_cannot_prepopulate_human_identity() -> None:
    payload = _manifest_payload()
    row = _reset_to_pending(_first_case(payload))
    row["decided_at"] = "2026-09-22T12:00:00Z"
    row["decided_by"] = "alexhawat"
    with pytest.raises(ValidationError, match="pending decisions must leave"):
        HumanBatchManifest.model_validate(payload)


def test_abstain_requires_actual_human_identity_but_not_recovered_evidence() -> None:
    payload = _manifest_payload()
    _reset_to_pending(_first_case(payload))["decision"] = "abstain"
    with pytest.raises(ValidationError, match="non-pending decisions require"):
        HumanBatchManifest.model_validate(payload)

    row = _first_case(payload)
    row["decided_at"] = "2026-09-22T12:00:00Z"
    row["decided_by"] = "alexhawat"
    manifest = HumanBatchManifest.model_validate(payload)
    assert manifest.cases[0].decision == "abstain"
    assert manifest.cases[0].evidence_status == "missing"


def test_confirm_requires_recovered_evidence_and_matching_human_identity() -> None:
    payload = _manifest_payload()
    row = _first_case(payload)
    row.update(
        {
            "evidence_status": "recovered",
            "source_url": (
                "https://github.com/example/project/blob/"
                "0123456789abcdef0123456789abcdef01234567/file.py"
            ),
            "decision": "confirm",
            "decided_at": "2026-09-22T12:00:00Z",
            "decided_by": "someone-else",
        }
    )
    with pytest.raises(ValidationError, match="must match the manifest adjudicator_login"):
        HumanBatchManifest.model_validate(payload)


def test_correct_requires_at_least_one_corrected_corpus_field() -> None:
    payload = _manifest_payload()
    row = _first_case(payload)
    row.update(
        {
            "evidence_status": "recovered",
            "source_url": (
                "https://github.com/example/project/blob/"
                "0123456789abcdef0123456789abcdef01234567/file.py"
            ),
            "decision": "correct",
            "decided_at": "2026-09-22T12:00:00Z",
            "decided_by": "alexhawat",
            "corrected_fields": {},
        }
    )
    with pytest.raises(ValidationError, match="at least one corrected corpus field"):
        HumanBatchManifest.model_validate(payload)


def test_fixture_path_is_confined_to_its_case_directory() -> None:
    payload = _manifest_payload()
    row = _first_case(payload)
    row.update(
        {
            "evidence_status": "recovered",
            "fixture_path": "evals/fixtures/golden/other-case/task.patch",
            "fixture_sha256": "0" * 64,
        }
    )
    with pytest.raises(ValidationError, match="inside the case's golden fixture directory"):
        HumanBatchManifest.model_validate(payload)


def test_fixture_hash_is_verified_before_rendering(tmp_path: Path) -> None:
    payload = deepcopy(_manifest_payload())
    row = _first_case(payload)
    case_id = str(row["case_id"])
    fixture_relative = Path("evals") / "fixtures" / "golden" / case_id / "task.patch"
    fixture = tmp_path / fixture_relative
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes(b"review evidence\n")
    row.update(
        {
            "evidence_status": "recovered",
            "fixture_path": fixture_relative.as_posix(),
            "fixture_sha256": sha256(fixture.read_bytes()).hexdigest(),
        }
    )
    manifest = HumanBatchManifest.model_validate(payload)

    fixture.write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="fixture hash mismatch"):
        render_review_sheet(manifest, repo_root=tmp_path)


def test_corrected_fields_are_merged_through_strict_corpus_case_validation(
    tmp_path: Path,
) -> None:
    payload = _manifest_payload()
    row = _first_case(payload)
    case_id = str(row["case_id"])
    row.update(
        {
            "evidence_status": "recovered",
            "source_url": (
                "https://github.com/example/project/blob/"
                "0123456789abcdef0123456789abcdef01234567/file.py"
            ),
            "decision": "correct",
            "decided_at": "2026-09-22T12:00:00Z",
            "decided_by": "alexhawat",
            "corrected_fields": {"title": "corrected title"},
        }
    )
    target = tmp_path / "evals" / "cases" / "golden" / f"{case_id}.json"
    target.parent.mkdir(parents=True)
    source = _REPO_ROOT / "evals" / "cases" / "golden" / f"{case_id}.json"
    base_case = json.loads(source.read_text(encoding="utf-8"))
    base_case["unknown"] = "strict validation must reject this"
    target.write_text(json.dumps(base_case), encoding="utf-8")
    manifest = HumanBatchManifest.model_validate(payload)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        verify_corrected_cases(manifest, repo_root=tmp_path)
