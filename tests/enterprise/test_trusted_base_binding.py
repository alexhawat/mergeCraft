"""On untrusted tiers, enterprise controls bind from the operator-side config.

Telemetry, the residency allow-list and retention come from the PR base
(``git show <base>:.mergecraft/config.yaml``), from the run-start tree on a
``pull_request_target`` run, and from built-in defaults when an untrusted run has
no operator-owned config at all. Trusted runs keep binding their own settings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.config.settings import RepoSettings, load_repo_settings
from mergecraft.enterprise.controls import EnterpriseSettings
from mergecraft.enterprise.runtime import (
    bind_enterprise_after_trust,
    current_enterprise_settings,
    remote_export_allowed,
    scoped_enterprise_binding,
)
from tests.enterprise.base_config_repo import make_pr_checkout, pull_request_event, write_event

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_BASE = 'enterprise:\n  telemetry: "off"\n  allowedRegions: [eu]\n  retentionDays: 7\n'
_HEAD = 'enterprise:\n  telemetry: "on"\n  allowedRegions: [us]\n  retentionDays: 365\n'


def _head_settings(root: Path) -> RepoSettings:
    return load_repo_settings(root=root, load_learnings_files=False)


def test_untrusted_pr_binds_base_controls(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    base_sha = make_pr_checkout(root, base_config=_BASE, head_config=_HEAD)
    head = _head_settings(root)
    assert head.enterprise.allowed_regions == ("us",)

    bind_enterprise_after_trust(
        head,
        "untrusted",
        event=pull_request_event(base_sha),
        event_name="pull_request",
        repo_root=root,
    )

    bound = current_enterprise_settings()
    assert bound.allowed_regions == ("eu",)
    assert bound.telemetry == "off"
    assert bound.retention_days == 7
    assert remote_export_allowed() is False


def test_untrusted_pr_base_without_config_binds_defaults(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    base_sha = make_pr_checkout(root, base_config=None, head_config=_HEAD)

    bind_enterprise_after_trust(
        _head_settings(root),
        "untrusted",
        event=pull_request_event(base_sha),
        event_name="pull_request",
        repo_root=root,
    )

    assert current_enterprise_settings() == EnterpriseSettings()


def test_untrusted_pr_with_unreadable_base_turns_remote_telemetry_off(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    make_pr_checkout(root, base_config=_BASE, head_config=_HEAD)

    bind_enterprise_after_trust(
        _head_settings(root),
        "untrusted",
        event=pull_request_event("0" * 40, base_ref="missing-branch"),
        event_name="pull_request",
        repo_root=root,
    )

    bound = current_enterprise_settings()
    assert bound.telemetry == "off"
    assert bound.allowed_regions == ()
    assert bound.retention_days is None


def test_untrusted_run_without_pr_base_ignores_checkout_controls(tmp_path: Path) -> None:
    """An offline review of a clone: nothing in the tree is operator-owned."""
    root = tmp_path / "repo"
    make_pr_checkout(root, base_config=_BASE, head_config=_HEAD)

    bind_enterprise_after_trust(_head_settings(root), "untrusted")

    assert current_enterprise_settings() == EnterpriseSettings()


def test_pull_request_target_binds_run_start_controls(tmp_path: Path) -> None:
    """The run-start tree of a ``pull_request_target`` run is the base checkout."""
    root = tmp_path / "repo"
    make_pr_checkout(root, base_config=_HEAD, head_config=_BASE)
    run_start = _head_settings(root)

    bind_enterprise_after_trust(
        run_start,
        "untrusted",
        event=pull_request_event("0" * 40),
        event_name="pull_request_target",
        repo_root=root,
    )

    bound = current_enterprise_settings()
    assert bound.allowed_regions == ("eu",)
    assert bound.telemetry == "off"


def test_untrusted_tier_never_binds_checkout_proxy(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    base_sha = make_pr_checkout(
        root,
        base_config="enterprise:\n  httpsProxy: http://proxy.example.invalid:3128\n",
        head_config="enterprise: {}\n",
    )

    bind_enterprise_after_trust(
        _head_settings(root),
        "untrusted",
        event=pull_request_event(base_sha),
        event_name="pull_request",
        repo_root=root,
    )

    assert current_enterprise_settings().https_proxy == ""


def test_trusted_tier_binds_its_own_controls(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    base_sha = make_pr_checkout(root, base_config=_BASE, head_config=_HEAD)

    bind_enterprise_after_trust(
        _head_settings(root),
        "trusted",
        event=pull_request_event(base_sha),
        event_name="pull_request",
        repo_root=root,
    )

    assert current_enterprise_settings().allowed_regions == ("us",)


def test_untrusted_action_context_resolves_base_from_event_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Action call site passes no event: the review context and event file supply it."""
    from mergecraft.tracing.review_context import ReviewContext, bind_review_context

    root = tmp_path / "repo"
    base_sha = make_pr_checkout(root, base_config=_BASE, head_config=_HEAD)
    event_path = write_event(tmp_path / "event.json", pull_request_event(base_sha))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.chdir(root)

    context = ReviewContext(source="action", trigger="pull_request", trust_tier="untrusted")
    with bind_review_context(context):
        bind_enterprise_after_trust(_head_settings(root), "untrusted")

    assert current_enterprise_settings().allowed_regions == ("eu",)


def test_scoped_binding_under_untrusted_context_uses_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sink construction before trust resolution reads the base, not the checkout."""
    from mergecraft.tracing.review_context import ReviewContext, bind_review_context

    root = tmp_path / "repo"
    base_sha = make_pr_checkout(root, base_config=_BASE, head_config=_HEAD)
    event_path = write_event(tmp_path / "event.json", pull_request_event(base_sha))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.chdir(root)

    context = ReviewContext(
        source="action", trigger="pull_request", raw_event_trust_floor="untrusted"
    )
    with bind_review_context(context), scoped_enterprise_binding(_head_settings(root)):
        bound = current_enterprise_settings()
        assert bound.allowed_regions == ("eu",)
        assert remote_export_allowed() is False
    assert current_enterprise_settings() == EnterpriseSettings()
