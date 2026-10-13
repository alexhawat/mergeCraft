"""The canary assertion lives in a tests helper, not in the shipped redaction module.

``assert_no_canary`` is a test hook; it belongs with the analyzer suite. The
shipped redactors keep redacting secret material.
"""

from __future__ import annotations

import pytest

import mergecraft.analyzers.redact as redact_module
import tests.analyzers.support as analyzer_support

_CANARY = "sk-canary-dead-code-hygiene-7f3a9b2c1d4e5f6a"


def test_redact_module_no_longer_ships_assert_no_canary() -> None:
    """The shipped module has no canary hook; the redactors still redact."""
    assert not hasattr(redact_module, "assert_no_canary")
    assert "assert_no_canary" not in redact_module.__all__
    # Surviving surface: the shipped redactor removes the canary from output.
    redacted = redact_module.redact_analyzer_output(f"token={_CANARY}", tool_id="gitleaks")
    assert _CANARY not in redacted


def test_tests_helper_provides_assert_no_canary() -> None:
    """A tests helper owns the canary assertion and still fails on a leak."""
    helper = getattr(analyzer_support, "assert_no_canary", None)
    assert callable(helper)
    with pytest.raises(AssertionError):
        helper(f"leaked {_CANARY}", _CANARY)
    # Surviving surface: clean text passes the helper.
    helper("clean analyzer output", _CANARY)
