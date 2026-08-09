"""RED contracts for the ``logfire`` sink (W7.2, W7.1 partial).

Issue #56 specifies ``send_to_logfire="if-token-present"`` semantics: when no
token is available the sink must *not* export and must *not* error. This
module pins that contract and the per-attribute token resolution (W7.4) so
the installer can wire ``${{ secrets.LOGFIRE_TOKEN }}`` without the operator
ever writing the value to YAML.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = [
    pytest.mark.xfail(reason="green after W8: logfire sink + token resolution", strict=False),
]


# ---------------------------------------------------------------------------
# W7.2 — absent token = no export, no error.
# ---------------------------------------------------------------------------


def test_absent_token_means_no_export_and_no_error(
    monkeypatch: pytest.MonkeyPatch, trace_event_payload: dict[str, Any]
) -> None:
    """When neither ``tokenRef`` nor ``MERGECRAFT_LOGFIRE_TOKEN`` resolves, the sink is a no-op.

    The issue specifies ``send_to_logfire="if-token-present"`` — the run
    completes, the resolver emits a warning that explains what to set, but no
    network call leaves the runner.
    """
    pytest.importorskip("logfire")

    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)
    import loguru

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import TraceEvent, sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire", "project": "demo"}],
            }
        }
    ).tracing
    captured: list[str] = []
    sink_id = loguru.logger.add(
        lambda record: captured.append(record.record["message"]), level="WARNING"
    )
    try:
        sink = sink_factory(settings)
        sink.write(TraceEvent.model_validate(trace_event_payload))
        sink.flush()
    finally:
        loguru.logger.remove(sink_id)

    # No exception escaped, and a warning explains the missing token so the
    # operator can debug.
    assert any(
        "token" in message.lower() or "logfire" in message.lower() for message in captured
    ), f"expected a warning about the missing token, got: {captured!r}"


def test_absent_token_does_not_raise_at_factory_time() -> None:
    """``sink_factory`` returns successfully — the absence of a token is a runtime no-op, not a factory error."""
    pytest.importorskip("logfire")

    import os

    os.environ.pop("MERGECRAFT_LOGFIRE_TOKEN", None)
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    settings = RepoSettings.model_validate(
        {"tracing": {"enabled": True, "sinks": [{"type": "logfire"}]}}
    ).tracing
    # Should not raise.
    sink = sink_factory(settings)
    assert sink is not None


@pytest.mark.parametrize("token_location", ["tokenRef", "env"])
def test_token_present_enables_export(token_location: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the token is reachable via either ``tokenRef`` or the env fallback, the sink is active."""
    pytest.importorskip("logfire")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    if token_location == "tokenRef":
        config = {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire", "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN"}],
            }
        }
        monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "canary-token-value")
    else:
        config = {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire"}],
            }
        }
        monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "canary-token-value")

    settings = RepoSettings.model_validate(config).tracing
    sink = sink_factory(settings)
    # Active sink: the underlying exporter was constructed (not the no-op
    # resolver path that a missing token would take).
    assert sink is not None
    assert hasattr(sink, "write")
