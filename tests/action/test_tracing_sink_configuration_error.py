"""A mistyped tracing sink is a configuration error, not infrastructure noise (#930).

Every other malformed tracing value (the enable flag, region, content level and
untrusted-content export) fails closed as ``configuration_error`` naming the
variable. The sink selector was the one control-carrying value that still raised
a plain ``ValueError`` during run setup, so an operator typo ended the run as
``infra_error`` — the same outcome as an unclassified crash.

With tracing **off**, a mistyped sink changes nothing about the run, so it stays
ignored; the operator still gets a ``warning`` naming it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from loguru import logger
from tests.support.run_main_harness import run_main_for_test

from mergecraft.run_outcome import RunOutcome

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_EVENT = "workflow_dispatch"
_PAYLOAD = {"action": "workflow_dispatch"}
_TYPO = "logfier"


@pytest.fixture
def warnings() -> Iterator[list[str]]:
    captured: list[str] = []
    handler_id = logger.add(lambda message: captured.append(str(message)), level="WARNING")
    try:
        yield captured
    finally:
        logger.remove(handler_id)


@pytest.mark.parametrize(
    ("env", "variable"),
    [
        ({"INPUT_TRACING": "true", "INPUT_TRACING_TO": _TYPO}, "INPUT_TRACING_TO"),
        ({"MERGECRAFT_TRACING": "true", "INPUT_TRACING_TO": _TYPO}, "INPUT_TRACING_TO"),
        ({"MERGECRAFT_TRACING": "true", "MERGECRAFT_TRACING_TO": _TYPO}, "MERGECRAFT_TRACING_TO"),
    ],
    ids=["action-input", "action-input-env-enabled", "env-variable"],
)
async def test_unknown_sink_with_tracing_on_fails_as_a_configuration_error(
    env: dict[str, str],
    variable: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env=env,
        event_name=_EVENT,
        event_payload=_PAYLOAD,
    )

    assert rec.result is not None, f"main() raised instead of returning: {rec.raised!r}"
    assert rec.result.outcome is RunOutcome.configuration_error, (
        f"a mistyped sink must be configuration_error, got {rec.result.outcome!r} "
        f"(error={rec.result.error!r})"
    )
    assert rec.result.success is False
    assert rec.agent_runs == [], "no agent may be spawned after a configuration error"
    error = rec.result.error or ""
    assert variable in error, f"the error must name {variable}: {error!r}"
    assert _TYPO in error, f"the error must name the offending value: {error!r}"


@pytest.mark.parametrize(
    "env",
    [
        {"INPUT_TRACING": "false", "INPUT_TRACING_TO": _TYPO},
        {"INPUT_TRACING_TO": _TYPO},
        {"MERGECRAFT_TRACING": "false", "MERGECRAFT_TRACING_TO": _TYPO},
    ],
    ids=["input-disabled", "input-unset", "env-disabled"],
)
async def test_unknown_sink_with_tracing_off_is_ignored_but_warned(
    env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    warnings: list[str],
) -> None:
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env=env,
        event_name=_EVENT,
        event_payload=_PAYLOAD,
    )

    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    assert rec.result.outcome is not RunOutcome.configuration_error
    assert rec.agent_runs, "a tracing-off typo must not stop the run"
    named = [line for line in warnings if _TYPO in line]
    assert named, f"expected a warning naming {_TYPO!r}; saw {warnings!r}"


@pytest.mark.parametrize("sink", ["logfire", "otel", "local_files"])
async def test_known_sinks_still_run(
    sink: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    warnings: list[str],
) -> None:
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        env={"INPUT_TRACING": "true", "INPUT_TRACING_TO": sink},
        event_name=_EVENT,
        event_payload=_PAYLOAD,
    )

    assert rec.result is not None, f"main() raised: {rec.raised!r}"
    assert rec.result.outcome is not RunOutcome.configuration_error
    assert not [line for line in warnings if "tracing sink" in line.lower()]
