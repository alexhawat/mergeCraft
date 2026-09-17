"""``verify`` / ``reproduce`` flows and missing-input ``blocked`` cases against the fake."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

from tests.verify.fake_driver import FakeBrowserDriver
from tests.verify.support import (
    CRITERION_STATUSES,
    REPRODUCE_STATUSES,
    SECRET_ENV_NAME,
    SECRET_ENV_VALUE,
    V4_XFAIL,
    import_verify,
    make_input,
    require_symbol,
)


def _run() -> Any:
    return require_symbol(import_verify("runner"), "run_verify_behavior")


@V4_XFAIL
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


@V4_XFAIL
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


@V4_XFAIL
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


@V4_XFAIL
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


@V4_XFAIL
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


@V4_XFAIL
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
