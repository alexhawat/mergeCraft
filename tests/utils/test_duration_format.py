"""Duration formatting for LLM review timing (#983 task 6)."""

from __future__ import annotations

import pytest

from mergecraft.utils.duration import format_duration


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.0, "0s"),
        (11.0, "11s"),
        (59.9, "59s"),
        (60.0, "1m 0s"),
        (191.0, "3m 11s"),
        (3661.0, "1h 1m 1s"),
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected
