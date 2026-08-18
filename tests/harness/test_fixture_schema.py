"""RH1.1 RED — provider fixture schema contract (``tests.support.provider_harness.schema``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_MIN_CHAT_BODY = {
    "id": "stub",
    "choices": [{"message": {"role": "assistant", "content": "{}"}}],
}


@pytest.mark.xfail(reason="green after RH1.2", strict=False)
def test_fixture_requires_provider_and_model() -> None:
    from pydantic import ValidationError

    from tests.support.provider_harness.schema import FixtureSpec, MatchSpec, ResponseSpec

    with pytest.raises(ValidationError):
        FixtureSpec(
            name="missing-provider",
            match=MatchSpec(model="dummy"),  # type: ignore[call-arg]
            response=ResponseSpec(body=_MIN_CHAT_BODY),
        )

    with pytest.raises(ValidationError):
        FixtureSpec(
            name="missing-model",
            match=MatchSpec(provider="default"),  # type: ignore[call-arg]
            response=ResponseSpec(body=_MIN_CHAT_BODY),
        )


@pytest.mark.xfail(reason="green after RH1.2", strict=False)
def test_fixture_requires_request_match_fields() -> None:
    from pydantic import ValidationError

    from tests.support.provider_harness.schema import MatchSpec

    with pytest.raises(ValidationError):
        MatchSpec()  # type: ignore[call-arg]

    with pytest.raises(ValidationError):
        MatchSpec(provider="")  # type: ignore[call-arg]


@pytest.mark.xfail(reason="green after RH1.2", strict=False)
def test_fixture_accepts_json_response_and_metadata() -> None:
    from tests.support.provider_harness.schema import FixtureSpec, MatchSpec, ResponseSpec

    fixture = FixtureSpec(
        name="json-with-metadata",
        match=MatchSpec(provider="default", model="dummy", mode="review"),
        response=ResponseSpec(
            status_code=200,
            body=_MIN_CHAT_BODY,
            usage={"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            request_id="req-test-001",
            finish_reason="stop",
        ),
    )

    assert fixture.response.request_id == "req-test-001"
    assert fixture.response.finish_reason == "stop"
    assert fixture.response.usage == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
    }


@pytest.mark.xfail(reason="green after RH1.2", strict=False)
def test_fixture_accepts_ordered_response_blocks() -> None:
    from tests.support.provider_harness.schema import (
        FixtureSpec,
        MatchSpec,
        ResponseBlock,
        ResponseSpec,
    )

    fixture = FixtureSpec(
        name="ordered-blocks",
        match=MatchSpec(provider="default", model="dummy"),
        response=ResponseSpec(
            blocks=[
                ResponseBlock(kind="text", text="Review complete."),
                ResponseBlock(
                    kind="tool_call",
                    tool_name="submit_review_verdict",
                    tool_call_id="call-1",
                    arguments={"verdict": "approve"},
                ),
            ],
        ),
    )

    assert len(fixture.response.blocks) == 2
    assert fixture.response.blocks[0].kind == "text"
    assert fixture.response.blocks[1].tool_name == "submit_review_verdict"


@pytest.mark.xfail(reason="green after RH1.2", strict=False)
def test_malformed_fixture_is_rejected_with_path(tmp_path: Path) -> None:
    from tests.support.provider_harness.schema import MalformedFixtureError, load_fixture_file

    bad_path = tmp_path / "broken-scenario.json"
    bad_path.write_text("{ not valid json", encoding="utf-8")

    with pytest.raises(MalformedFixtureError) as exc_info:
        load_fixture_file(bad_path)

    assert str(bad_path) in str(exc_info.value)

    missing_required = tmp_path / "incomplete-scenario.json"
    missing_required.write_text(
        json.dumps({"name": "incomplete", "match": {"provider": "default"}}),
        encoding="utf-8",
    )
    with pytest.raises(MalformedFixtureError) as exc_info2:
        load_fixture_file(missing_required)
    assert str(missing_required) in str(exc_info2.value)
