"""A PR's own ``analyzers.*`` config is reported, never applied to its own review (#942)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

_GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false"]
_BASE_CONFIG = "analyzers:\n  inlineBudget: 8\n  overrides:\n    trufflehog:\n      enabled: true\n"
_HEAD_CONFIG = dedent(
    """\
    analyzers:
      inlineBudget: 1
      impact: true
      overrides:
        trufflehog:
          enabled: false
        antislop:
          ignore: ["src/**"]
    """
)


@pytest.fixture(autouse=True)
def _isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [*_GIT, "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _pr_checkout(tmp_path: Path, *, base: str | None = _BASE_CONFIG, head: str = _HEAD_CONFIG):
    """A checkout whose run-start tree is the PR head, plus the base commit's sha."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    if base is not None:
        (repo / ".mergecraft").mkdir()
        (repo / ".mergecraft" / "config.yaml").write_text(base, encoding="utf-8")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")
    (repo / ".mergecraft").mkdir(exist_ok=True)
    (repo / ".mergecraft" / "config.yaml").write_text(head, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "head")
    return repo, base_sha


def _ctx(repo: Path, *, base_sha: str | None, trigger: str = "pull_request") -> ToolContext:
    event: dict[str, Any] | None = None
    if base_sha is not None:
        event = {"pull_request": {"number": 7, "base": {"sha": base_sha, "ref": "main"}}}
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger=trigger, issue_number=7, is_pr=True),  # type: ignore[arg-type]
            shell="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(repo)),
        mcp_server_url="",
        tmpdir=str(repo),
        trust_tier="trusted",
        analyzers_settings_enabled=True,
        gh_event=event,
    )


def _pin_run_start_snapshot(ctx: ToolContext, repo: Path, *, operator_owned: bool = False) -> None:
    """Mirror ``main.py``: the run-start tree is read once, before ``checkout_pr``."""
    from mergecraft.config.settings_snapshot import capture_run_scope_snapshot

    capture_run_scope_snapshot(ctx, root=repo, operator_owned=operator_owned)


# --------------------------------------------------------------------------- resolver


def test_pull_request_settings_come_from_the_base_sha_not_the_head_checkout(
    tmp_path: Path,
) -> None:
    from mergecraft.analyzers.settings_pin import resolve_pinned_analyzer_settings

    repo, base_sha = _pr_checkout(tmp_path)
    ctx = _ctx(repo, base_sha=base_sha)
    _pin_run_start_snapshot(ctx, repo)  # the snapshot is the PR head — the problem under test

    pinned = resolve_pinned_analyzer_settings(ctx, repo)

    assert pinned.resolved_from == "base_sha"
    assert pinned.settings.inline_budget == 8
    assert pinned.settings.overrides["trufflehog"].enabled is True
    assert "antislop" not in pinned.settings.overrides
    assert pinned.settings.impact is False


def test_operator_owned_base_snapshot_is_used_as_is(tmp_path: Path) -> None:
    from mergecraft.analyzers.settings_pin import resolve_pinned_analyzer_settings

    repo, base_sha = _pr_checkout(tmp_path, head=_BASE_CONFIG)
    ctx = _ctx(repo, base_sha=base_sha, trigger="pull_request_target")
    _pin_run_start_snapshot(ctx, repo, operator_owned=True)

    pinned = resolve_pinned_analyzer_settings(ctx, repo)

    assert pinned.resolved_from == "base_snapshot"
    assert pinned.settings.inline_budget == 8


def test_event_without_a_base_falls_back_to_the_run_start_snapshot(tmp_path: Path) -> None:
    from mergecraft.analyzers.settings_pin import resolve_pinned_analyzer_settings

    repo, _ = _pr_checkout(tmp_path)
    ctx = _ctx(repo, base_sha=None, trigger="unknown")
    _pin_run_start_snapshot(ctx, repo)

    pinned = resolve_pinned_analyzer_settings(ctx, repo)

    assert pinned.resolved_from == "run_start_snapshot"


def test_base_without_a_config_file_means_defaults_not_the_head_config(tmp_path: Path) -> None:
    from mergecraft.analyzers.settings_pin import resolve_pinned_analyzer_settings

    repo, base_sha = _pr_checkout(tmp_path, base=None)
    ctx = _ctx(repo, base_sha=base_sha)
    _pin_run_start_snapshot(ctx, repo)

    pinned = resolve_pinned_analyzer_settings(ctx, repo)

    assert pinned.resolved_from == "base_sha"
    assert pinned.settings.inline_budget == 8  # the schema default, not the head's 1
    assert pinned.settings.overrides == {}


def test_a_symlinked_base_config_fails_closed_with_a_named_reason(tmp_path: Path) -> None:
    from mergecraft.analyzers.settings_pin import resolve_pinned_analyzer_settings

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / ".mergecraft").mkdir()
    (repo / "elsewhere.yaml").write_text(_BASE_CONFIG, encoding="utf-8")
    (repo / ".mergecraft" / "config.yaml").symlink_to("../elsewhere.yaml")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")
    (repo / ".mergecraft" / "config.yaml").unlink()
    (repo / ".mergecraft" / "config.yaml").write_text(_HEAD_CONFIG, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "head")
    ctx = _ctx(repo, base_sha=base_sha)
    _pin_run_start_snapshot(ctx, repo)

    pinned = resolve_pinned_analyzer_settings(ctx, repo)

    assert pinned.resolved_from == "defaults"
    assert pinned.detail
    assert "symlink" in pinned.detail.casefold()
    assert pinned.settings.overrides == {}
    assert pinned.settings.inline_budget == 8


def test_unreadable_base_fails_closed_to_defaults_with_a_reason(tmp_path: Path) -> None:
    from mergecraft.analyzers.settings_pin import resolve_pinned_analyzer_settings

    repo, _ = _pr_checkout(tmp_path)
    ctx = _ctx(repo, base_sha="0" * 40)
    _pin_run_start_snapshot(ctx, repo)

    pinned = resolve_pinned_analyzer_settings(ctx, repo)

    assert pinned.resolved_from == "defaults"
    assert pinned.detail
    assert pinned.settings.overrides == {}


# --------------------------------------------------------------------------- consumers


def _fake_adapter(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from mergecraft.analyzers import adapters

    ran: list[str] = []

    def _run_adapter(**kwargs: Any) -> adapters.AdapterRunResult:
        ran.append(str(kwargs["tool_id"]))
        return adapters.AdapterRunResult(findings=[])

    monkeypatch.setattr(adapters, "run_adapter", _run_adapter)
    return ran


@pytest.mark.asyncio
async def test_run_analyzers_ignores_a_head_only_analyzer_config_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The PR disables trufflehog in its own config; trufflehog still runs on that PR."""
    from mergecraft.analyzers import pipeline
    from mergecraft.analyzers.registry import get_manifest
    from mergecraft.mcp.analyzers import run_analyzers_tool

    repo, base_sha = _pr_checkout(tmp_path)
    ctx = _ctx(repo, base_sha=base_sha)
    _pin_run_start_snapshot(ctx, repo)
    ran = _fake_adapter(monkeypatch)
    selected: list[dict[str, Any]] = []

    def _detect(**kwargs: Any) -> list[Any]:
        selected.append(kwargs["settings_overrides"])
        return [get_manifest("trufflehog")]

    monkeypatch.setattr(pipeline, "detect_enabled", _detect)

    result = await run_analyzers_tool(ctx).execute({"changed_files": ["src/app.py"]})
    payload = json.loads(result.content[0]["text"])

    assert payload["analyzers"], payload
    overrides = selected[0]["analyzers"]["overrides"]
    assert overrides.get("trufflehog", {}).get("enabled") is not False
    assert selected[0]["analyzers"]["inlineBudget"] == 8
    assert ran


@pytest.mark.asyncio
async def test_resolved_from_is_recorded_on_the_analyzer_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.analyzers import pipeline
    from mergecraft.analyzers.registry import get_manifest
    from mergecraft.mcp.analyzers import run_analyzers_tool

    repo, base_sha = _pr_checkout(tmp_path)
    ctx = _ctx(repo, base_sha=base_sha)
    _pin_run_start_snapshot(ctx, repo)
    _fake_adapter(monkeypatch)
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [get_manifest("ruff")])

    await run_analyzers_tool(ctx).execute({"changed_files": ["src/app.py"]})

    assert ctx.tool_state.analyzer_run is not None
    assert ctx.tool_state.analyzer_run.settings_resolved_from == "base_sha"


def test_pipeline_uses_the_settings_it_is_given_not_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.analyzers import pipeline
    from mergecraft.analyzers.registry import get_manifest
    from mergecraft.config.settings import AnalyzersSettings

    repo, _ = _pr_checkout(tmp_path)  # the checkout carries the loosened head config
    _fake_adapter(monkeypatch)
    seen: list[dict[str, Any]] = []

    def _detect(**kwargs: Any) -> list[Any]:
        seen.append(kwargs["settings_overrides"])
        return [get_manifest("ruff")]

    monkeypatch.setattr(pipeline, "detect_enabled", _detect)
    pinned = AnalyzersSettings.model_validate({"inlineBudget": 8})

    pipeline.run_analyzer_pipeline(
        repo_root=repo,
        changed_files=["a.py"],
        tier="trusted",
        shell="restricted",
        analyzers_settings=pinned,
    )

    assert seen[0]["analyzers"]["inlineBudget"] == 8
    assert seen[0]["analyzers"]["overrides"] == {}


def test_pipeline_never_reads_the_head_config_when_settings_are_pinned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mergecraft.analyzers import pipeline
    from mergecraft.config.settings import AnalyzersSettings

    repo, _ = _pr_checkout(tmp_path)

    def _boom(*_a: Any, **_kw: Any) -> Any:
        msg = "head checkout config must not be loaded"
        raise AssertionError(msg)

    monkeypatch.setattr(pipeline, "load_repo_settings", _boom, raising=False)
    monkeypatch.setattr(pipeline, "detect_enabled", lambda **_: [])

    pipeline.run_analyzer_pipeline(
        repo_root=repo,
        changed_files=["a.py"],
        tier="trusted",
        shell="restricted",
        analyzers_settings=AnalyzersSettings(),
    )


def test_antislop_takes_rules_and_ignore_from_the_pinned_settings(tmp_path: Path) -> None:
    from mergecraft.analyzers.antislop import scan_changed_files
    from mergecraft.config.settings import AnalyzersSettings

    repo, _ = _pr_checkout(tmp_path)  # head config ignores src/**
    (repo / "src").mkdir()
    (repo / "src" / "slop.py").write_text("def f():\n    pass  # TODO\n", encoding="utf-8")
    pinned = AnalyzersSettings()  # the base has no antislop override

    result = scan_changed_files(
        repo_root=repo, changed_files=["src/slop.py"], analyzers_settings=pinned
    )

    assert result.skip_reason != "skipped antislop: all changed paths ignored"


def test_impact_toggle_is_read_from_the_pinned_settings(tmp_path: Path) -> None:
    from mergecraft.analyzers.settings_pin import resolve_pinned_analyzer_settings

    repo, base_sha = _pr_checkout(tmp_path)  # head turns impact on
    ctx = _ctx(repo, base_sha=base_sha)
    _pin_run_start_snapshot(ctx, repo)

    assert resolve_pinned_analyzer_settings(ctx, repo).settings.impact is False


def test_a_head_side_global_disable_does_not_switch_the_analyzer_surface_off(
    tmp_path: Path,
) -> None:
    from mergecraft.analyzers.trust import analyzers_enabled

    repo, base_sha = _pr_checkout(
        tmp_path, head="analyzers:\n  enabled: false\n", base="analyzers:\n  enabled: true\n"
    )
    ctx = _ctx(repo, base_sha=base_sha)
    ctx.analyzers_settings_enabled = False  # what main.py records from the head tree
    _pin_run_start_snapshot(ctx, repo)

    assert analyzers_enabled(ctx) is True


def test_an_operator_off_switch_still_wins(tmp_path: Path) -> None:
    from mergecraft.analyzers.trust import analyzers_enabled

    repo, base_sha = _pr_checkout(tmp_path)
    ctx = _ctx(repo, base_sha=base_sha)
    ctx.analyzers_mode = "off"  # type: ignore[assignment]

    assert analyzers_enabled(ctx) is False
