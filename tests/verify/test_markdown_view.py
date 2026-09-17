"""Markdown rendering is a view over the JSON report — it invents no fields."""

from __future__ import annotations

from tests.verify.support import (
    V2_XFAIL,
    import_verify,
    make_blocked_report,
    make_report,
    require_symbol,
)


@V2_XFAIL
def test_markdown_render_is_a_view_of_the_json() -> None:
    """Two reports that differ only in ``observed`` differ in markdown only there."""
    models = import_verify("models")
    render = require_symbol(models, "render_verification_markdown")
    alpha = make_report(observed="UNIQUE_OBS_ALPHA")
    beta = make_report(observed="UNIQUE_OBS_BETA")
    text_a = render(alpha)
    text_b = render(beta)
    assert "UNIQUE_OBS_ALPHA" in text_a
    assert "UNIQUE_OBS_ALPHA" not in text_b
    assert "UNIQUE_OBS_BETA" in text_b
    assert "UNIQUE_OBS_BETA" not in text_a
    stripped_a = text_a.replace("UNIQUE_OBS_ALPHA", "")
    stripped_b = text_b.replace("UNIQUE_OBS_BETA", "")
    assert stripped_a == stripped_b


@V2_XFAIL
def test_markdown_includes_status_and_criteria() -> None:
    models = import_verify("models")
    render = require_symbol(models, "render_verification_markdown")
    report = make_report(status="fail")
    text = render(report)
    assert "fail" in text.lower()
    assert "Clear button removes the image" in text
    assert "## Behavior verification" in text or "## Reproduction attempt" in text


@V2_XFAIL
def test_markdown_blocked_names_missing_input() -> None:
    models = import_verify("models")
    render = require_symbol(models, "render_verification_markdown")
    report = make_blocked_report(missing=["APP_TEST_PASSWORD"])
    text = render(report)
    assert "blocked" in text.lower()
    assert "APP_TEST_PASSWORD" in text
