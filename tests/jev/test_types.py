"""J1.1 / J1.4 — wire types for Choice, Score, Noul, and Usage (T3-T5)."""

from __future__ import annotations

import pytest

from tests.jev.support import PINNED_MODEL, import_jev, load_transport_body


def test_parse_system_one_response_accepts_none_usage() -> None:
    types = import_jev("types")
    response = types.parse_system_one_response(load_transport_body("usage_tokens_none.json"))
    assert response.model == PINNED_MODEL
    assert response.usage.input_tokens is None
    assert response.usage.output_tokens is None
    assert response.answers["triage"].choice == "suspicious"


def test_parse_rejects_empty_body_with_structured_code() -> None:
    types = import_jev("types")
    with pytest.raises(types.JevError) as exc_info:
        types.parse_system_one_response({})
    assert exc_info.value.code == "invalid_response"


def test_noul_answer_has_no_confidence_field() -> None:
    types = import_jev("types")
    answer = types.NoulAnswer(noul=0.5)
    assert answer.noul == 0.5
    dumped = answer.model_dump()
    assert set(dumped) == {"noul"}
