"""Trust-tier derivation from real GHA event shape (D7)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from tests.analyzers.support import import_module

if TYPE_CHECKING:
    import pytest


def test_missing_github_event_defaults_untrusted() -> None:
    trust = import_module("mergecraft.analyzers.trust")
    assert trust.derive_trust_tier(event=None, shell="restricted") == "untrusted"


def test_same_repo_pull_request_is_trusted(
    monkeypatch: pytest.MonkeyPatch, same_repo_event: dict[str, object]
) -> None:
    trust = import_module("mergecraft.analyzers.trust")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = trust.derive_trust_tier(event=same_repo_event, shell="restricted")
    assert tier == "trusted"


def test_fork_pull_request_is_untrusted(
    monkeypatch: pytest.MonkeyPatch, fork_pr_event: dict[str, object]
) -> None:
    trust = import_module("mergecraft.analyzers.trust")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = trust.derive_trust_tier(event=fork_pr_event, shell="restricted")
    assert tier == "untrusted"


def test_untrusted_run_strips_secret_env(monkeypatch, fork_pr_event: dict[str, object]) -> None:
    trust = import_module("mergecraft.analyzers.trust")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk_secret")
    env = trust.build_analyzer_env(tier="untrusted", repo_env={"GITHUB_TOKEN": "ghp_secret"})
    values = " ".join(f"{k}={v}" for k, v in env.items())
    assert "ghp_secret" not in values
    assert "sk_secret" not in values


def test_trusted_only_manifest_skipped_on_untrusted_tier(fork_pr_event: dict[str, object]) -> None:
    trust = import_module("mergecraft.analyzers.trust")
    manifest = import_module("mergecraft.analyzers.manifest")
    raw = Path("tests/analyzers/fixtures/manifests/valid-actionlint.yaml").read_text(
        encoding="utf-8"
    )
    m = manifest.load_manifest_yaml(raw.replace("trust: untrusted", "trust: trusted"))
    decision = trust.evaluate_manifest_for_tier(manifest=m, tier="untrusted")
    assert decision.skipped is True
    assert decision.reason


def test_shell_disabled_keeps_the_analyzer_surface(tmp_path: Path) -> None:
    """#35 — `shell: disabled` no longer withholds mergeCraft's own catalog.

    It used to return ``False`` here, which is the whole defect: the withhold
    was aimed at repo-declared ``staticChecks`` and took the pinned catalog
    with it. Per-manifest eligibility now lives in
    ``evaluate_manifest_for_shell`` (see ``test_shell_disabled_split.py``).
    """
    trust = import_module("mergecraft.analyzers.trust")
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell="disabled",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        static_checks_enabled=False,
        analyzers_mode="auto",
        analyzers_settings_enabled=True,
    )
    assert trust.analyzers_enabled(ctx) is True


def test_w0_probe_event_shape_matches_trusted(
    monkeypatch: pytest.MonkeyPatch, same_repo_event: dict[str, object]
) -> None:
    """W0.4 probe: ``pull_request`` same-repo PR #1, ``fork=false``."""
    trust = import_module("mergecraft.analyzers.trust")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    assert same_repo_event["pull_request"]["head"]["repo"]["fork"] is False  # type: ignore[index]
    assert trust.derive_trust_tier(event=same_repo_event, shell="restricted") == "trusted"
