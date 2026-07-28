"""MainResult shape tests."""

from __future__ import annotations

from mergecraft.main import MainResult


def test_main_result_success_shape() -> None:
    result = MainResult(success=True, output="ok", result="ok")
    assert result.success is True
    assert result.output == "ok"
    assert result.result == "ok"
    assert result.error is None


def test_main_result_failure_shape() -> None:
    result = MainResult(success=False, error="boom")
    assert result.success is False
    assert result.error == "boom"
    assert result.output is None
    assert result.result is None
