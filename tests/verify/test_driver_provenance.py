"""Every report records which driver produced it (EV1 → EV3).

``--allow-stub`` used to skip the browser unconditionally and the report never
said so — the only trace was a debug log. The additive, optional
``VerificationReport.driver`` field (``"cdp"``, ``"stub"`` or ``None`` when not
recorded) makes a stub-produced report self-describing and leaves every
existing report valid: it is defaulted, so a JSON document written before the
field still parses, and ``schema_version`` stays ``1.0.0``.

Red today: the field does not exist, so ``report.driver`` raises
``AttributeError`` and ``make_report(driver=…)`` raises ``ValidationError`` at
call time, never at collection.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from tests.verify.fake_driver import FakeBrowserDriver
from tests.verify.support import (
    import_verify,
    make_input,
    make_report,
    require_symbol,
    sample_report_payload,
)


def _run() -> Any:
    return require_symbol(import_verify("runner"), "run_verify_behavior")


async def test_cdp_driven_run_stamps_the_cdp_driver() -> None:
    """A run driven by the live CDP driver records ``"cdp"`` on its report, and
    the value is a real serialised field (unlike the detection coverage rate)."""
    report = await _run()(
        make_input(
            mode="verify",
            acceptance_criteria=["Error shown"],
            credential_env_names=[],
        ),
        driver=FakeBrowserDriver(page_text="Error shown"),
        driver_kind="cdp",
        offline=True,
    )

    assert report.driver == "cdp"
    assert report.model_dump()["driver"] == "cdp"


async def test_stub_driven_run_stamps_the_stub_driver() -> None:
    """A stub-produced report says ``"stub"`` — the audit's whole point is that
    the stub must not be indistinguishable from a real browser run."""
    report = await _run()(
        make_input(
            mode="verify",
            acceptance_criteria=["Error shown"],
            credential_env_names=[],
        ),
        driver=FakeBrowserDriver(page_text="Error shown"),
        driver_kind="stub",
        offline=True,
    )

    assert report.driver == "stub"


def test_skipped_report_has_no_driver() -> None:
    """The skip path writes no driver: there was no run to attribute."""
    runner = import_verify("runner")
    write_skipped_report = require_symbol(runner, "write_skipped_report")

    report = write_skipped_report(
        make_input(credential_env_names=[]),
        reason="cdp_unavailable: set --remote-debugging-port",
    )
    assert report.status == "skipped"
    assert report.driver is None


def test_report_json_without_the_driver_key_still_validates() -> None:
    """EV-D7: additive and optional, so an older report — or any caller that
    does not record a driver — parses with ``driver is None``."""
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")

    payload = sample_report_payload()
    assert "driver" not in payload

    restored = report_cls.model_validate(payload)

    assert restored.driver is None


def test_driver_is_optional_and_rejects_unknown_kinds() -> None:
    """The field is a closed literal: ``cdp`` / ``stub`` / absent. Anything else
    is a contract violation, not a free-form string."""
    models = import_verify("models")
    report_cls = require_symbol(models, "VerificationReport")

    field = report_cls.model_fields.get("driver")
    assert field is not None, "VerificationReport has no driver field yet"
    assert field.default is None

    with pytest.raises(ValidationError):
        report_cls.model_validate({**sample_report_payload(), "driver": "playwright"})


def test_markdown_view_shows_the_driver_line() -> None:
    """The markdown view renders every model field, so the driver reaches the
    review prompt without a renderer change."""
    models = import_verify("models")
    render = require_symbol(models, "render_verification_markdown")

    text = render(make_report(driver="stub"))

    assert "driver" in text
    assert "stub" in text
