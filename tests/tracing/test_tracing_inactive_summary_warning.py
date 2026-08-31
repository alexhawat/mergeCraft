"""W1.4 / D12 — visible tracing inactive warning (wave plan 15, green after W5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.trust_credentials.support import import_action_symbol

if TYPE_CHECKING:
    import pytest


def test_tracing_enabled_without_token_surfaces_run_summary_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D12 — configured tracing with no resolvable token warns on the run summary surface."""
    collect = import_action_symbol("collect_tracing_warnings_for_summary")
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "logfire")
    monkeypatch.delenv("INPUT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)

    warnings = collect()
    assert warnings, "expected at least one operator-visible tracing warning"
    joined = "\n".join(warnings).lower()
    assert "logfire" in joined or "tracing" in joined
    assert "token" in joined or "no-op" in joined or "inactive" in joined
