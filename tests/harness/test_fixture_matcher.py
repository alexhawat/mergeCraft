"""RH1.1 RED — strict fixture matcher contract (``tests.support.provider_harness.matcher``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.harness._helpers import snapshot

_MIN_CHAT_BODY = {
    "id": "stub",
    "choices": [{"message": {"role": "assistant", "content": "{}"}}],
}


def _fixture(
    *,
    name: str,
    provider: str = "default",
    model: str = "dummy",
    mode: str | None = "review",
    streaming: bool = False,
    turn_index: int = 0,
    body_fields: dict[str, object] | None = None,
    max_uses: int = 1,
) -> object:
    from tests.support.provider_harness.schema import FixtureSpec, MatchSpec, ResponseSpec

    return FixtureSpec(
        name=name,
        match=MatchSpec(
            provider=provider,
            model=model,
            mode=mode,
            streaming=streaming,
            turn_index=turn_index,
            body_fields=body_fields or {},
        ),
        response=ResponseSpec(body=_MIN_CHAT_BODY),
        max_uses=max_uses,
    )


def test_matching_uses_provider_model_and_mode() -> None:
    from tests.support.provider_harness.matcher import NoFixtureMatch, match_fixture

    fixtures = [
        _fixture(name="default-review", provider="default", model="dummy", mode="review"),
        _fixture(name="other-model", provider="default", model="other", mode="review"),
    ]

    matched = match_fixture(snapshot(), fixtures, strict=True)
    assert matched.name == "default-review"

    with pytest.raises(NoFixtureMatch):
        match_fixture(snapshot(model="unknown"), fixtures, strict=True)


def test_streaming_flag_participates_in_matching() -> None:
    from tests.support.provider_harness.matcher import match_fixture

    fixtures = [
        _fixture(name="non-stream", streaming=False),
        _fixture(name="stream", streaming=True),
    ]

    matched = match_fixture(snapshot(streaming=False), fixtures, strict=True)
    assert matched.name == "non-stream"

    matched_stream = match_fixture(snapshot(streaming=True), fixtures, strict=True)
    assert matched_stream.name == "stream"


def test_body_field_matchers_are_explicit() -> None:
    from tests.support.provider_harness.matcher import NoFixtureMatch, match_fixture

    fixtures = [
        _fixture(
            name="temperature-zero",
            body_fields={"temperature": 0},
        ),
        _fixture(
            name="temperature-one",
            body_fields={"temperature": 1},
        ),
    ]

    matched = match_fixture(snapshot(body={"temperature": 0}), fixtures, strict=True)
    assert matched.name == "temperature-zero"

    with pytest.raises(NoFixtureMatch):
        match_fixture(snapshot(body={"temperature": 0.5}), fixtures, strict=True)


def test_no_fixture_match_is_an_error_in_strict_mode() -> None:
    from tests.support.provider_harness.matcher import NoFixtureMatch, match_fixture

    fixtures = [_fixture(name="only-one", model="other-model")]

    with pytest.raises(NoFixtureMatch):
        match_fixture(snapshot(model="dummy"), fixtures, strict=True)


def test_multiple_matches_are_an_error() -> None:
    from tests.support.provider_harness.matcher import AmbiguousFixtureMatch, match_fixture

    fixtures = [
        _fixture(name="dup-a"),
        _fixture(name="dup-b"),
    ]

    with pytest.raises(AmbiguousFixtureMatch):
        match_fixture(snapshot(), fixtures, strict=True)


def test_unexpected_fixture_reuse_is_an_error() -> None:
    from tests.support.provider_harness.matcher import FixtureReuseError, match_fixture

    fixtures = [_fixture(name="single-use", max_uses=1)]
    req = snapshot()

    first = match_fixture(req, fixtures, strict=True)
    assert first.name == "single-use"

    with pytest.raises(FixtureReuseError):
        match_fixture(req, fixtures, strict=True)


def test_lenient_mode_is_not_the_ci_default() -> None:
    """CI pin — lenient env must not be set in pytest defaults (D7/D16)."""
    repo_root = Path(__file__).resolve().parents[2]
    pyproject = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    conftest = (repo_root / "tests" / "conftest.py").read_text(encoding="utf-8")

    assert "MERGECRAFT_PROVIDER_HARNESS_LENIENT" not in pyproject
    assert "MERGECRAFT_PROVIDER_HARNESS_LENIENT" not in conftest
