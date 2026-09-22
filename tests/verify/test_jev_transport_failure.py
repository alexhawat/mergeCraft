"""Client-failure composition: a failed Jev call is ``unverified``, never an abort.

``mergecraft.jev.client.AsyncJevClient.call`` raises on a transport failure — a
``TypeSafeAPIError`` once the 5xx retries are exhausted, or a structured
``JevError`` for ``invalid_state`` / ``credential_absent``. ``jev_seam`` catches
both and returns a named ``unverified`` result with reason ``transport_error``,
so the failure never escapes: the criterion loop keeps judging, the repro judge
still answers, and the runner reports ``partial`` instead of aborting with no
partial report at all.

``test_jev_seam.py`` pins the seam's happy paths and honest skips; these tests
pin the failure path end to end. The TypeSafe case replays the recorded 500
envelope (``RecordedTransport``); a structured ``JevError`` has no recorded
envelope form, so its transport is injected directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tenacity import wait_none

from mergecraft.jev.client import AsyncJevClient, RecordedTransport
from mergecraft.jev.types import JevError, SystemOneResponse
from tests.verify.fake_driver import FakeBrowserDriver
from tests.verify.support import import_verify, make_input, require_symbol

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transport"
_TEST_API_KEY = "mc-test-transport-failure"
_500_FIXTURE = "client_transport_error.json"
_TRANSPORT_ERROR_REASON = "transport_error"
_FAILURE_KINDS = ("typesafe_500", "credential_absent")

_VERIFY_INPUT: dict[str, Any] = {
    "mode": "verify",
    "acceptance_criteria": ["Clear removes the image"],
    "credential_env_names": [],
    "artifacts_dir": "",
}
_REPRODUCE_INPUT: dict[str, Any] = {
    "mode": "reproduce",
    "acceptance_criteria": [],
    "repro_notes": "clicking Clear leaves the image",
    "credential_env_names": [],
    "artifacts_dir": "",
}


def _seam() -> Any:
    """Import ``mergecraft.verify.jev_seam`` or fail with a named deliverable."""
    return import_verify("jev_seam")


def _run() -> Any:
    """Return ``run_verify_behavior`` with a named-deliverable failure."""
    return require_symbol(import_verify("runner"), "run_verify_behavior")


class _RaisingTransport:
    """Jev transport whose every dispatch raises the injected failure.

    Mirrors ``RecordedTransport``'s protocol surface (``calls`` / ``last_model``
    plus async ``system_one``) so it drives the real ``AsyncJevClient`` dispatch
    and retry path, and records the call count so a test can assert the seam
    kept dispatching.
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.calls = 0
        self.last_model: str | None = None

    async def system_one(
        self,
        *,
        state: dict[str, Any],
        questions: dict[str, Any],
        model: str,
    ) -> SystemOneResponse:
        del state, questions
        self.calls += 1
        self.last_model = model
        raise self._exc


def _failing_client(kind: str) -> tuple[AsyncJevClient, Any]:
    """A real ``AsyncJevClient`` whose transport always fails with ``kind``.

    ``typesafe_500`` replays a recorded 500 envelope: ``AsyncJevClient.call``
    retries the 5xx and then raises
    ``TypeSafeAPIError(status_code=500, code="server_error")``.
    ``credential_absent`` injects a structured ``JevError``, which has no
    recorded envelope form.
    """
    if kind == "typesafe_500":
        transport: Any = RecordedTransport.from_fixture(_FIXTURES / _500_FIXTURE)
    elif kind == "credential_absent":
        transport = _RaisingTransport(JevError("credential_absent", code="credential_absent"))
    else:
        msg = f"unknown failure kind {kind!r}"
        raise AssertionError(msg)
    return AsyncJevClient(api_key=_TEST_API_KEY, transport=transport), transport


@pytest.fixture(params=_FAILURE_KINDS)
def failing_client(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[AsyncJevClient, Any]:
    """A failing client per failure kind, with retry waits neutralised."""
    monkeypatch.setattr("mergecraft.jev.client.DEFAULT_WAIT", wait_none())
    return _failing_client(request.param)


async def test_judge_criteria_transport_failure_is_unverified_and_keeps_judging(
    failing_client: tuple[AsyncJevClient, Any],
) -> None:
    """One ``unverified`` per criterion, named ``transport_error``; the loop continues."""
    seam = _seam()
    client, transport = failing_client
    judgments = await seam.judge_criteria(
        ["Clear removes the image", "Undo restores it"],
        page_text="image still visible",
        client=client,
    )
    assert [judgment.criterion for judgment in judgments] == [
        "Clear removes the image",
        "Undo restores it",
    ]
    assert [judgment.verdict for judgment in judgments] == ["unverified", "unverified"]
    assert [judgment.reason for judgment in judgments] == [_TRANSPORT_ERROR_REASON] * 2
    assert transport.calls >= 1


async def test_judge_repro_claim_transport_failure_is_unverified(
    failing_client: tuple[AsyncJevClient, Any],
) -> None:
    """The repro judge answers ``unverified`` with the named transport reason."""
    seam = _seam()
    client, transport = failing_client
    judgment = await seam.judge_repro_claim(
        "clicking Clear leaves the image",
        page_text="image still visible",
        client=client,
    )
    assert judgment.claim == "clicking Clear leaves the image"
    assert judgment.verdict == "unverified"
    assert judgment.reason == _TRANSPORT_ERROR_REASON
    assert transport.calls >= 1


@pytest.mark.parametrize(
    ("mode", "overrides"),
    [("verify", _VERIFY_INPUT), ("reproduce", _REPRODUCE_INPUT)],
    ids=["verify", "reproduce"],
)
async def test_runner_reports_partial_when_the_jev_transport_fails(
    failing_client: tuple[AsyncJevClient, Any],
    mode: str,
    overrides: dict[str, Any],
) -> None:
    """The failure never escapes the runner: a completed run is ``partial``."""
    run = _run()
    client, _ = failing_client
    report = await run(
        make_input(**overrides),
        driver=FakeBrowserDriver(page_text="image still visible"),
        jev_client=client,
        offline=True,
    )
    assert report.mode == mode
    assert report.status == "partial"
    assert any(_TRANSPORT_ERROR_REASON in reason for reason in report.skipped_or_unverified), (
        report.skipped_or_unverified
    )
    if mode == "verify":
        assert [item.status for item in report.acceptance_criteria] == ["unverified"]
    else:
        assert report.acceptance_criteria == []
        assert any(
            reason.startswith("repro unverified:") for reason in report.skipped_or_unverified
        ), report.skipped_or_unverified
