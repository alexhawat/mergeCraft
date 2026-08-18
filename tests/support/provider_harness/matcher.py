"""Strict fixture matching for provider-harness requests."""

from __future__ import annotations

import os
from typing import Any

from tests.support.provider_harness.schema import FixtureSpec, MatchSpec


class NoFixtureMatch(Exception):
    def __init__(
        self,
        *,
        request: dict[str, Any],
        fixtures: list[FixtureSpec],
        candidate_reasons: dict[str, str],
    ) -> None:
        self.request = request
        self.fixtures = fixtures
        self.candidate_reasons = candidate_reasons
        super().__init__("no fixture matched the request")


class AmbiguousFixtureMatch(Exception):
    def __init__(self, *, matches: list[FixtureSpec]) -> None:
        self.matches = matches
        names = ", ".join(m.name for m in matches)
        super().__init__(f"ambiguous fixture match: {names}")


class FixtureReuseError(Exception):
    def __init__(self, *, fixture: FixtureSpec, used_count: int) -> None:
        self.fixture = fixture
        self.used_count = used_count
        super().__init__(f"fixture {fixture.name!r} exceeded max_uses={fixture.max_uses}")


def _env_lenient() -> bool:
    return os.environ.get("MERGECRAFT_PROVIDER_HARNESS_LENIENT", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _request_value(request: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in request:
        return request[key]
    body = request.get("body")
    if isinstance(body, dict) and key in body:
        return body[key]
    return default


def _match_spec(request: dict[str, Any], spec: MatchSpec) -> str | None:
    pairs: list[tuple[str, Any, Any]] = [
        ("provider", spec.provider, _request_value(request, "provider")),
        ("model", spec.model, _request_value(request, "model")),
        ("streaming", spec.streaming, _request_value(request, "streaming", False)),
        ("turn_index", spec.turn_index, _request_value(request, "turn_index", 0)),
    ]
    optional: list[tuple[str, Any | None, Any]] = [
        ("mode", spec.mode, _request_value(request, "mode")),
        ("has_tool_results", spec.has_tool_results, _request_value(request, "has_tool_results")),
        ("test_context_id", spec.test_context_id, _request_value(request, "test_context_id")),
        ("tool_call_id", spec.tool_call_id, _request_value(request, "tool_call_id")),
        (
            "tool_result_content",
            spec.tool_result_content,
            _request_value(request, "tool_result_content"),
        ),
    ]
    for field, expected, observed in optional:
        if expected is not None and observed != expected:
            return f"{field}: expected {expected!r}, got {observed!r}"
    for field, expected, observed in pairs:
        if observed != expected:
            return f"{field}: expected {expected!r}, got {observed!r}"
    body = request.get("body")
    if not isinstance(body, dict):
        body = {}
    for key, expected in spec.body_fields.items():
        observed = body.get(key)
        if observed != expected:
            return f"body_fields[{key!r}]: expected {expected!r}, got {observed!r}"
    return None


def match_fixture(
    request: dict[str, Any],
    fixtures: list[FixtureSpec],
    *,
    strict: bool = True,
    usage_counts: dict[str, int] | None = None,
) -> FixtureSpec:
    effective_strict = strict and not _env_lenient()

    counts = usage_counts if usage_counts is not None else {}
    candidate_reasons: dict[str, str] = {}
    matches: list[FixtureSpec] = []
    for fixture in fixtures:
        reason = _match_spec(request, fixture.match)
        used = counts.get(fixture.name, 0)
        if reason is None:
            if used >= fixture.max_uses:
                if effective_strict:
                    raise FixtureReuseError(fixture=fixture, used_count=used)
                candidate_reasons[fixture.name] = "max_uses exceeded"
                continue
            matches.append(fixture)
        else:
            candidate_reasons[fixture.name] = reason

    if not matches:
        raise NoFixtureMatch(
            request=request,
            fixtures=fixtures,
            candidate_reasons=candidate_reasons or {"": "no candidates"},
        )
    if len(matches) > 1 and effective_strict:
        raise AmbiguousFixtureMatch(matches=matches)
    if len(matches) > 1:
        matches = [matches[0]]
    chosen = matches[0]
    counts[chosen.name] = counts.get(chosen.name, 0) + 1
    return chosen
