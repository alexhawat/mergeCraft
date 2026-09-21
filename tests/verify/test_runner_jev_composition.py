"""Positive Jev composition through ``run_verify_behavior``.

``test_jev_seam.py`` pins the seam in isolation; these tests pin the wiring from
``run_verify_behavior(..., jev_client=...)`` through to the observable report.
A recorded transport replays a real envelope, so a runner that ignored its
``jev_client`` and fell back to the local text heuristic would diverge from the
recorded verdict and fail — the local heuristic is deliberately given page text
that would decide the *opposite* way.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mergecraft.jev.client import AsyncJevClient, RecordedTransport
from tests.verify.fake_driver import FakeBrowserDriver
from tests.verify.support import import_verify, make_input, require_symbol

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transport"
_TEST_API_KEY = "mc-test-runner-jev"


def _run() -> Any:
    """Return ``run_verify_behavior`` with a named-deliverable failure."""
    return require_symbol(import_verify("runner"), "run_verify_behavior")


def _client(fixture: str) -> tuple[AsyncJevClient, RecordedTransport]:
    transport = RecordedTransport.from_fixture(_FIXTURES / fixture)
    return AsyncJevClient(api_key=_TEST_API_KEY, transport=transport), transport


async def test_scored_criterion_pass_reaches_report_status() -> None:
    """A recorded Jev pass drives the report status, not the local heuristic.

    The page text matches none of the criterion's significant tokens, so the
    local heuristic would score ``fail``; only composition through the scored
    seam can produce ``pass``.
    """
    run = _run()
    client, transport = _client("criterion_satisfied.json")
    report = await run(
        make_input(
            mode="verify",
            acceptance_criteria=["Clear removes the image"],
            credential_env_names=[],
            artifacts_dir="",
        ),
        driver=FakeBrowserDriver(page_text="picture gone"),
        jev_client=client,
        offline=True,
    )
    assert transport.calls >= 1
    assert report.status == "pass"
    assert [criterion.status for criterion in report.acceptance_criteria] == ["pass"]
    assert report.skipped_or_unverified == []


async def test_scored_criterion_fail_reaches_report_status() -> None:
    """A below-floor recorded answer drives a ``fail`` report through the runner."""
    run = _run()
    client, transport = _client("criterion_unsatisfied.json")
    report = await run(
        make_input(
            mode="verify",
            acceptance_criteria=["Clear removes the image"],
            credential_env_names=[],
            artifacts_dir="",
        ),
        driver=FakeBrowserDriver(page_text="image still visible"),
        jev_client=client,
        offline=True,
    )
    assert transport.calls >= 1
    assert report.status == "fail"
    assert [criterion.status for criterion in report.acceptance_criteria] == ["fail"]


async def test_scored_repro_claim_reaches_report_status() -> None:
    """A recorded ``reproduced`` verdict drives the reproduce report status."""
    run = _run()
    client, transport = _client("repro_reproduced.json")
    report = await run(
        make_input(
            mode="reproduce",
            acceptance_criteria=[],
            repro_notes="clicking Clear leaves the image",
            credential_env_names=[],
            artifacts_dir="",
        ),
        driver=FakeBrowserDriver(page_text="image still visible"),
        jev_client=client,
        offline=True,
    )
    assert transport.calls == 1
    assert report.mode == "reproduce"
    assert report.status == "reproduced"
