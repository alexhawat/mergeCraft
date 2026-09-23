"""Strict preparation contract for the first human golden-case batch (#780)."""

from __future__ import annotations

import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from mergecraft.evals.human_batch import (
    GOLDEN_BATCH_001_CASE_IDS,
    HumanBatchManifest,
    load_human_batch,
    render_review_sheet,
    verify_corrected_cases,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST_PATH = _REPO_ROOT / "evals" / "adjudication" / "golden-batch-001.json"


def _manifest_payload() -> dict[str, object]:
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _first_case(payload: dict[str, object]) -> dict[str, object]:
    cases = payload["cases"]
    assert isinstance(cases, list)
    row = cases[0]
    assert isinstance(row, dict)
    return row


def test_committed_manifest_records_all_evidence_and_decisions_as_missing() -> None:
    manifest = load_human_batch(_MANIFEST_PATH, repo_root=_REPO_ROOT)
    assert manifest.adjudicator_login == "alexhawat"
    assert {row.case_id for row in manifest.cases} == set(GOLDEN_BATCH_001_CASE_IDS)
    assert len(manifest.cases) == 9
    assert {row.evidence_status for row in manifest.cases} == {"missing"}
    assert {row.decision for row in manifest.cases} == {"pending"}
    assert all(row.decided_by is None and row.decided_at is None for row in manifest.cases)


def test_review_sheet_is_ordered_and_keeps_every_row_visibly_unanswered() -> None:
    manifest = load_human_batch(_MANIFEST_PATH, repo_root=_REPO_ROOT)
    sheet = render_review_sheet(manifest, repo_root=_REPO_ROOT)
    row_lines = [line for line in sheet.splitlines() if line.startswith("| golden-")]
    assert len(row_lines) == 9
    assert [line.split("|")[1].strip() for line in row_lines] == sorted(GOLDEN_BATCH_001_CASE_IDS)
    assert all("UNANSWERED" in line for line in row_lines)
    assert "Severity" not in sheet


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
    row = _first_case(payload)
    row["decided_at"] = "2026-09-22T12:00:00Z"
    row["decided_by"] = "alexhawat"
    with pytest.raises(ValidationError, match="pending decisions must leave"):
        HumanBatchManifest.model_validate(payload)


def test_abstain_requires_actual_human_identity_but_not_recovered_evidence() -> None:
    payload = _manifest_payload()
    _first_case(payload)["decision"] = "abstain"
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
