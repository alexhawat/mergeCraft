"""Test-only provider harness — deterministic fixture replay for review tests."""

from __future__ import annotations

import tests.support.provider_harness.profiles  # noqa: F401 — register profile names
from tests.support.provider_harness.diagnostics import format_mismatch
from tests.support.provider_harness.matcher import (
    AmbiguousFixtureMatch,
    FixtureReuseError,
    NoFixtureMatch,
    match_fixture,
)
from tests.support.provider_harness.schema import (
    FixtureSpec,
    MalformedFixtureError,
    MatchSpec,
    ResponseBlock,
    ResponseSpec,
    load_fixture_file,
)

DUMMY_API_KEY = "sk-mergecraft-test"

__all__ = [
    "DUMMY_API_KEY",
    "AmbiguousFixtureMatch",
    "FixtureReuseError",
    "FixtureSpec",
    "MalformedFixtureError",
    "MatchSpec",
    "NoFixtureMatch",
    "ResponseBlock",
    "ResponseSpec",
    "format_mismatch",
    "load_fixture_file",
    "match_fixture",
]
