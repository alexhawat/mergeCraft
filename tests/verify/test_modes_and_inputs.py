"""``verify`` / ``reproduce`` flows and missing-input ``blocked`` cases against the fake."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from tests.verify.fake_driver import FakeBrowserDriver, FakeUnreachableError
from tests.verify.support import (
    CRITERION_STATUSES,
    REPRODUCE_STATUSES,
    SECRET_ENV_NAME,
    SECRET_ENV_VALUE,
    import_verify,
    make_input,
    require_symbol,
)


def _run() -> Any:
    return require_symbol(import_verify("runner"), "run_verify_behavior")


async def test_verify_mode_produces_per_criterion_status() -> None:
    run = _run()
    fake = FakeBrowserDriver(page_text="image still visible")
    report = await run(
        make_input(
            mode="verify",
            acceptance_criteria=["Clear button removes the image", "Upload accepts PNG"],
            credential_env_names=[],
        ),
        driver=fake,
        offline=True,
    )
    assert report.mode == "verify"
    assert len(report.acceptance_criteria) == 2
    for criterion in report.acceptance_criteria:
        assert criterion.status in CRITERION_STATUSES
        assert isinstance(criterion.evidence, list)
        assert all(isinstance(path, str) for path in criterion.evidence)


async def test_reproduce_mode_reports_observed_versus_expected() -> None:
    run = _run()
    fake = FakeBrowserDriver(page_text="image still visible")
    report = await run(
        make_input(
            mode="reproduce",
            repro_notes="click Clear after upload",
            acceptance_criteria=["Clear does nothing"],
            credential_env_names=[],
        ),
        driver=fake,
        offline=True,
    )
    assert report.mode == "reproduce"
    assert report.status in REPRODUCE_STATUSES
    assert report.observed
    assert report.expected
    assert isinstance(report.steps, list)
    assert report.steps


async def test_unreachable_url_yields_blocked_naming_the_url() -> None:
    run = _run()
    url = "http://127.0.0.1:1/does-not-listen"
    fake = FakeBrowserDriver(unreachable_urls={url})
    report = await run(
        make_input(mode="verify", base_url=url, credential_env_names=[]),
        driver=fake,
        offline=True,
    )
    assert report.status == "blocked"
    assert report.status != "fail"
    named = " ".join(report.blocked.missing)
    assert url in named


async def test_missing_credentials_yields_blocked_not_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SECRET_ENV_NAME, raising=False)
    run = _run()
    report = await run(
        make_input(
            mode="verify",
            auth={"strategy": "env"},
            credential_env_names=[SECRET_ENV_NAME],
        ),
        driver=FakeBrowserDriver(),
        offline=True,
    )
    assert report.status == "blocked"
    assert report.status != "fail"
    named = " ".join(report.blocked.missing)
    assert SECRET_ENV_NAME in named


async def test_credential_values_never_appear_in_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV_NAME, SECRET_ENV_VALUE)
    run = _run()
    report = await run(
        make_input(credential_env_names=[SECRET_ENV_NAME], auth={"strategy": "env"}),
        driver=FakeBrowserDriver(),
        offline=True,
    )
    dumped = report.model_dump_json()
    assert SECRET_ENV_NAME in report.credential_names
    assert SECRET_ENV_VALUE not in dumped
    assert SECRET_ENV_VALUE not in str(report.model_dump())


async def test_verify_scores_each_criterion_against_its_own_text() -> None:
    run = _run()
    fake = FakeBrowserDriver(page_text="Welcome to the app")
    report = await run(
        make_input(
            mode="verify",
            acceptance_criteria=["Welcome to the app", "layout mismatch in footer"],
            credential_env_names=[],
        ),
        driver=fake,
        offline=True,
    )
    by_text = {item.text: item.status for item in report.acceptance_criteria}
    assert by_text["Welcome to the app"] == "pass"
    assert by_text["layout mismatch in footer"] == "pass"
    assert report.status == "pass"


async def test_reproduce_requires_notes_to_match_page_text() -> None:
    run = _run()
    fake = FakeBrowserDriver(page_text="homepage")
    report = await run(
        make_input(
            mode="reproduce",
            repro_notes="bug: crash on save",
            acceptance_criteria=[],
            credential_env_names=[],
        ),
        driver=fake,
        offline=True,
    )
    assert report.status == "not_reproduced"
    assert report.observed == "homepage"


async def test_runner_calls_click_fill_and_type_from_actions() -> None:
    run = _run()
    fake = FakeBrowserDriver(page_text="saved Ada")
    report = await run(
        make_input(
            mode="verify",
            acceptance_criteria=["saved Ada"],
            credential_env_names=[],
            actions=[
                {"action": "click", "selector": "#go"},
                {"action": "fill", "selector": "#name", "text": "Ada"},
                {"action": "type", "text": "more"},
            ],
        ),
        driver=fake,
        offline=True,
    )
    assert ("click", ("#go",)) in fake.calls
    assert ("fill", ("#name",)) in fake.calls
    assert ("type_text", ("more",)) in fake.calls
    recorded = {step.action for step in report.steps}
    assert {"navigate", "click", "fill", "type"} <= recorded


async def test_navigate_until_ready_retries_connection_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Startup readiness must retry ``ConnectionRefusedError``, not block immediately."""
    monkeypatch.setattr("mergecraft.verify.runner._NAVIGATE_RETRY_S", 0.01)
    navigate = require_symbol(import_verify("runner"), "_navigate_until_ready")
    attempts = 0

    class Driver(FakeBrowserDriver):
        async def navigate(self, url: str) -> None:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionRefusedError(url)
            await super().navigate(url)

    await navigate(Driver(), "http://127.0.0.1:8765/", wait=True)
    assert attempts == 3


async def test_navigate_until_ready_does_not_retry_other_connection_errors() -> None:
    navigate = require_symbol(import_verify("runner"), "_navigate_until_ready")
    fake = FakeBrowserDriver(unreachable_urls={"http://bad/"})
    with pytest.raises(FakeUnreachableError):
        await navigate(fake, "http://bad/", wait=True)


async def test_concurrent_same_credential_records_name_not_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SECRET_ENV_NAME, SECRET_ENV_VALUE)
    run = _run()
    spec = make_input(credential_env_names=[SECRET_ENV_NAME], auth={"strategy": "env"})
    first, second = await asyncio.gather(
        run(spec, driver=FakeBrowserDriver(), offline=True),
        run(spec, driver=FakeBrowserDriver(), offline=True),
    )
    for report in (first, second):
        assert SECRET_ENV_NAME in report.credential_names
        assert SECRET_ENV_VALUE not in report.model_dump_json()
