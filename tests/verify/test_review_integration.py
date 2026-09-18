"""Review consumes a report: fenced, separate section, not Findings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding
from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.offline_review import build_offline_review_prompt
from tests.verify.support import (
    INJECTION_STRING,
    import_verify,
    make_blocked_report,
    make_report,
    require_symbol,
    untrusted_fork_event,
)

if TYPE_CHECKING:
    import pytest

_DIFF = "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"


def _review() -> Any:
    return import_verify("review")


def _write_diff(tmp_path: Path) -> Path:
    path = tmp_path / "change.diff"
    path.write_text(_DIFF, encoding="utf-8")
    return path


def test_offline_prompt_without_report_has_no_behavior_section(tmp_path: Path) -> None:
    """The no-report path has no behaviour section."""
    prompt = build_offline_review_prompt(diff_path=_write_diff(tmp_path), base_ref="HEAD")
    assert "## Behavior verification" not in prompt
    assert "select_mode" in prompt


def test_report_enters_the_prompt_fenced(tmp_path: Path) -> None:
    review = _review()
    prepare = require_symbol(review, "prepare_verification_report_for_prompt")
    injected = make_report(observed=INJECTION_STRING, status="fail")
    benign = make_report(observed="button works", status="fail")
    fenced = prepare(injected)
    assert "<<<UNTRUSTED-MERGECRAFT-CONTENT" in fenced
    assert "<<<END-UNTRUSTED-MERGECRAFT-CONTENT" in fenced
    assert "nonce=" in fenced
    assert INJECTION_STRING in fenced
    to_findings = require_symbol(review, "verification_report_to_findings")
    assert to_findings(injected) == []
    assert to_findings(benign) == []

    prompt = build_offline_review_prompt(
        diff_path=_write_diff(tmp_path),
        base_ref="HEAD",
        verification_report=injected,
    )
    assert "<<<UNTRUSTED-MERGECRAFT-CONTENT" in prompt
    assert INJECTION_STRING in prompt


def test_review_includes_a_behavior_section() -> None:
    review = _review()
    render = require_symbol(review, "render_behavior_section")
    report = make_report(status="fail")
    text = render(report)
    assert "## Behavior verification" in text
    assert "fail" in text.lower()
    assert "Clear button removes the image" in text


def test_blocked_report_is_surfaced_not_swallowed() -> None:
    review = _review()
    render = require_symbol(review, "render_behavior_section")
    report = make_blocked_report(missing=["APP_TEST_PASSWORD"])
    text = render(report)
    assert "blocked" in text.lower()
    assert "APP_TEST_PASSWORD" in text
    assert "## Behavior verification" in text


def test_skipped_when_no_report_supplied() -> None:
    review = _review()
    consume = require_symbol(review, "consume_verification_report")
    assert consume(None) is None
    render = require_symbol(review, "render_behavior_section")
    assert render(None) == ""


def test_consume_defaults_to_untrusted(tmp_path: Path) -> None:
    review = _review()
    consume = require_symbol(review, "consume_verification_report")
    report_path = tmp_path / "report.json"
    report_path.write_text(make_report().model_dump_json(), encoding="utf-8")
    assert consume(report_path) is None
    assert consume(report_path, trust_tier="trusted") is not None


def test_consume_skips_when_fork_event_env_overrides_trusted_kwarg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(untrusted_fork_event()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    review = _review()
    consume = require_symbol(review, "consume_verification_report")
    report_path = tmp_path / "report.json"
    report_path.write_text(make_report().model_dump_json(), encoding="utf-8")
    assert consume(report_path, trust_tier="trusted") is None


def test_behavioural_results_do_not_become_findings() -> None:
    review = _review()
    to_findings = require_symbol(review, "verification_report_to_findings")
    report = make_report(status="fail", observed="Clear does nothing")
    findings = to_findings(report)
    assert findings == []
    assert not any(isinstance(item, Finding) for item in findings)


async def test_untrusted_run_neither_produces_nor_consumes_a_report(
    tmp_path: Path,
) -> None:
    event = untrusted_fork_event()
    assert derive_trust_tier(event, event_name="pull_request") == "untrusted"
    review = _review()
    consume = require_symbol(review, "consume_verification_report")
    report_path = tmp_path / "report.json"
    report_path.write_text(make_report().model_dump_json(), encoding="utf-8")
    assert consume(report_path, trust_tier="untrusted") is None

    from tests.verify.fake_driver import FakeBrowserDriver
    from tests.verify.support import make_input

    runner = require_symbol(import_verify("runner"), "run_verify_behavior")
    artifacts = tmp_path / "arts"
    result = await runner(
        make_input(artifacts_dir=str(artifacts), credential_env_names=[]),
        driver=FakeBrowserDriver(),
        event=event,
        event_name="pull_request",
    )
    assert result.status == "skipped"
    json_files = list(artifacts.rglob("*.json")) if artifacts.exists() else []
    assert json_files == []


def test_diff_review_accepts_verification_report_flag(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from mergecraft.cli.app import app

    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        [
            "diff-review",
            "--help",
        ],
    )
    assert result.exit_code == 0
    assert "--verification-report" in result.stdout
