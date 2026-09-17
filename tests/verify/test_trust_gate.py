"""Trusted-tier only: untrusted and ``shell: disabled`` make the capability inert."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mergecraft.analyzers.trust import derive_trust_tier
from tests.verify.fake_driver import FakeBrowserDriver
from tests.verify.support import (
    import_verify,
    make_input,
    require_symbol,
    trusted_same_repo_event,
    untrusted_fork_event,
)


def _runner() -> Any:
    return require_symbol(import_verify("runner"), "run_verify_behavior")


async def test_untrusted_tier_is_inert_and_reports_skipped() -> None:
    """``derive_trust_tier`` → ``untrusted`` skips; reason names the tier."""
    event = untrusted_fork_event()
    assert derive_trust_tier(event, event_name="pull_request") == "untrusted"
    run = _runner()
    report = await run(
        make_input(credential_env_names=[]),
        driver=FakeBrowserDriver(),
        event=event,
        event_name="pull_request",
    )
    assert report.status == "skipped"
    assert any("untrusted" in item.lower() for item in report.skipped_or_unverified)


async def test_pull_request_target_is_inert() -> None:
    event: dict[str, object] = {}
    assert derive_trust_tier(event, event_name="pull_request_target") == "untrusted"
    run = _runner()
    report = await run(
        make_input(credential_env_names=[]),
        driver=FakeBrowserDriver(),
        event=event,
        event_name="pull_request_target",
    )
    assert report.status == "skipped"
    assert any("untrusted" in item.lower() for item in report.skipped_or_unverified)


async def test_untrusted_does_not_execute_startup_command(tmp_path: Path) -> None:
    """Guard deletion: if the trust check is removed, the sentinel is created and this fails."""
    sentinel = tmp_path / "started"
    run = _runner()
    report = await run(
        make_input(startup_command=f"touch {sentinel}", credential_env_names=[]),
        driver=FakeBrowserDriver(),
        event=untrusted_fork_event(),
        event_name="pull_request",
    )
    assert report.status == "skipped"
    assert not sentinel.exists()


async def test_shell_disabled_is_inert_even_when_trusted(tmp_path: Path) -> None:
    """``shell: disabled`` skips on a trusted tier and names ``shell``."""
    sentinel = tmp_path / "started"
    event = trusted_same_repo_event()
    assert derive_trust_tier(event, event_name="pull_request") == "trusted"
    run = _runner()
    report = await run(
        make_input(startup_command=f"touch {sentinel}", credential_env_names=[]),
        driver=FakeBrowserDriver(),
        event=event,
        event_name="pull_request",
        shell="disabled",
    )
    assert report.status == "skipped"
    reasons = " ".join(report.skipped_or_unverified).lower()
    assert "shell" in reasons
    assert "disabled" in reasons
    assert not sentinel.exists()


async def test_config_cannot_reenable_on_untrusted() -> None:
    """``verify_behavior.enabled: true`` does not override an untrusted tier."""
    from mergecraft.config.settings import RepoSettings, VerifyBehaviorSettings

    settings = RepoSettings.model_validate({"verify_behavior": {"enabled": True}})
    assert isinstance(settings.verify_behavior, VerifyBehaviorSettings)
    assert settings.verify_behavior.enabled is True
    run = _runner()
    report = await run(
        make_input(credential_env_names=[]),
        driver=FakeBrowserDriver(),
        event=untrusted_fork_event(),
        event_name="pull_request",
        settings=settings,
    )
    assert report.status == "skipped"
    assert any("untrusted" in item.lower() for item in report.skipped_or_unverified)


async def test_trusted_offline_is_not_skipped_for_trust() -> None:
    """A trusted local run may proceed (fake driver); skip reason is not untrusted."""
    run = _runner()
    report = await run(
        make_input(base_url="http://127.0.0.1:8765/", credential_env_names=[]),
        driver=FakeBrowserDriver(page_text="ok"),
        offline=True,
        shell="restricted",
    )
    assert "untrusted" not in " ".join(report.skipped_or_unverified).lower()
    assert report.status != "skipped" or not any(
        "untrusted" in item.lower() for item in report.skipped_or_unverified
    )
