"""J1.4 — versioned question packs (D1, D16). No instruction-substring asserts."""

from __future__ import annotations

from typing import Any

from tests.jev.support import (
    ALIGN_QUESTION_NAMES,
    CLAIM_QUESTION_NAMES,
    EVIDENCE_QUESTION_NAMES,
    FORBIDDEN_COUNT_NAMES,
    PACK_IDS,
    UNIT_QUESTION_NAMES,
    import_jev,
    load_transport_body,
)


def _questions() -> Any:
    return import_jev("questions")


def _types() -> Any:
    return import_jev("types")


def test_unit_pack_v1_names_and_types() -> None:
    pack = _questions().unit_pack()
    assert pack.pack_id == "unit/v1"
    assert tuple(pack.question_names) == UNIT_QUESTION_NAMES
    assert pack.question_type("triage") == "choice"
    assert pack.question_type("severity") == "score"
    for name in (
        "security",
        "error_discard",
        "contract_break",
        "untrusted_input",
        "missing_tests",
        "style_nit",
    ):
        assert pack.question_type(name) == "noul"


def test_evidence_pack_v1_names_and_types() -> None:
    pack = _questions().evidence_pack()
    assert pack.pack_id == "evidence/v1"
    assert tuple(pack.question_names) == EVIDENCE_QUESTION_NAMES
    assert pack.question_type("relation") == "choice"
    assert pack.question_type("falsifiable") == "noul"
    assert pack.question_type("located") == "noul"


def test_claim_pack_v1_names_and_types() -> None:
    pack = _questions().claim_pack()
    assert pack.pack_id == "claim/v1"
    assert tuple(pack.question_names) == CLAIM_QUESTION_NAMES
    for name in CLAIM_QUESTION_NAMES:
        assert pack.question_type(name) == "noul"


def test_align_pack_v1_names_and_types() -> None:
    pack = _questions().align_pack()
    assert pack.pack_id == "align/v1"
    assert tuple(pack.question_names) == ALIGN_QUESTION_NAMES
    assert pack.question_type("same_defect") == "choice"
    assert pack.question_type("is_withdrawn_reraise") == "noul"


def test_get_pack_returns_every_versioned_id() -> None:
    questions = _questions()
    for pack_id in PACK_IDS:
        pack = questions.get_pack(pack_id)
        assert pack.pack_id == pack_id


def test_packs_do_not_include_counting_or_arithmetic_questions() -> None:
    questions = _questions()
    for pack_id in PACK_IDS:
        names = set(questions.get_pack(pack_id).question_names)
        assert names.isdisjoint(FORBIDDEN_COUNT_NAMES)


def test_parse_choice_score_and_noul_from_recorded_unit_body() -> None:
    types = _types()
    body = load_transport_body("unit_happy.json")
    response = types.parse_system_one_response(body)
    triage = response.answers["triage"]
    severity = response.answers["severity"]
    security = response.answers["security"]
    assert triage.choice == "defective"
    assert triage.confidence == 0.92
    assert triage.probabilities["defective"] == 0.92
    assert severity.score == 3.0
    assert severity.legend[3] == "Critical"
    assert security.noul == 0.81
    assert getattr(security, "confidence", None) is None
