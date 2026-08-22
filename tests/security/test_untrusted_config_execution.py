"""TS2 — untrusted-source executable config is dropped (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Pairs with TS1 trust tier: repo-declared ``setupScript``, ``prepushScript``, ``stopScript`` and
``staticChecks[].command`` must not reach executors on an untrusted source (D4). Declarative
config (analyzers, budgets, severity) survives.

Authoring wave: **TS2.1** (RED). Implementation: **TS2.2**.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from mergecraft.config.settings import RepoInfo, RepoSettings, load_repo_settings
from mergecraft.main import RunContext, _run_setup_script_phase
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.utils.instructions import resolve_instructions
from tests.analyzers.support import SAME_REPO_PULL_REQUEST_EVENT, import_module
from tests.security.test_trust_ordering_attacks import (
    FORK_PR_PAYLOAD,
)
from tests.support.run_main_harness import run_main_for_test


def _settings_mod() -> Any:
    return import_module("mergecraft.config.settings")


def _apply_trust_tier_to_repo_settings() -> Any:
    fn = getattr(_settings_mod(), "apply_trust_tier_to_repo_settings", None)
    if fn is None:
        pytest.fail("apply_trust_tier_to_repo_settings not defined in mergecraft.config.settings")
    return fn


def _build_executable_config_skip_reason() -> Any:
    fn = getattr(_settings_mod(), "build_executable_config_skip_reason", None)
    if fn is None:
        pytest.fail("build_executable_config_skip_reason not defined in mergecraft.config.settings")
    return fn


def _git(repo: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _init_git_repo(tmp_path: Path, name: str = "hostile") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def _write_config(repo: Path, yaml_body: str) -> None:
    config_dir = repo / ".mergecraft"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "config.yaml").write_text(yaml_body, encoding="utf-8")


async def _run_setup_phase_real(
    *,
    settings: RepoSettings,
    trust_tier: str,
    tmp_path: Path,
) -> None:
    """Drive ``_run_setup_script_phase`` with a real subprocess (no harness mock)."""
    tool_state = init_tool_state(owner="local", name="repo", dir=str(tmp_path))
    ctx = RunContext(
        settings=settings,
        tool_state=tool_state,
        trust_tier=trust_tier,
        timeout_ms=None,
    )
    await _run_setup_script_phase(ctx)


@pytest.mark.asyncio
async def test_untrusted_setup_script_is_not_executed(tmp_path: Path) -> None:
    """Untrusted tier drops ``setup_script`` before any subprocess can run it."""
    sentinel = tmp_path / "sentinel-setup"
    repo = _init_git_repo(tmp_path)
    _write_config(
        repo,
        f'setupScript: "touch {sentinel}"\n',
    )
    raw = load_repo_settings(root=repo)
    apply = _apply_trust_tier_to_repo_settings()
    filtered, _ = apply(raw, "untrusted", source_label="CLI offline review")

    await _run_setup_phase_real(settings=filtered, trust_tier="untrusted", tmp_path=repo)

    assert not sentinel.exists()
    assert filtered.setup_script is None


def test_untrusted_prepush_script_is_not_executed(tmp_path: Path) -> None:
    """``prepush_script`` is dropped on untrusted tier — no shell invocation possible."""
    sentinel = tmp_path / "sentinel-prepush"
    repo = _init_git_repo(tmp_path)
    _write_config(
        repo,
        f'prepushScript: "touch {sentinel}"\n',
    )
    raw = load_repo_settings(root=repo)
    apply = _apply_trust_tier_to_repo_settings()
    filtered, drops = apply(raw, "untrusted", source_label="untrusted CLI source")

    assert filtered.prepush_script is None
    assert "prepush_script" in drops
    if filtered.prepush_script:
        subprocess.run(filtered.prepush_script, shell=True, check=False)
    assert not sentinel.exists()


def test_untrusted_stop_script_is_not_executed(tmp_path: Path) -> None:
    """``stop_script`` is dropped on untrusted tier — no shell invocation possible."""
    sentinel = tmp_path / "sentinel-stop"
    repo = _init_git_repo(tmp_path)
    _write_config(
        repo,
        f'stopScript: "touch {sentinel}"\n',
    )
    raw = load_repo_settings(root=repo)
    apply = _apply_trust_tier_to_repo_settings()
    filtered, drops = apply(raw, "untrusted", source_label="untrusted CLI source")

    assert filtered.stop_script is None
    assert "stop_script" in drops
    if filtered.stop_script:
        subprocess.run(filtered.stop_script, shell=True, check=False)
    assert not sentinel.exists()


def test_untrusted_static_check_commands_are_dropped(tmp_path: Path) -> None:
    """``staticChecks[].command`` is dropped while gate metadata survives (D4)."""
    repo = _init_git_repo(tmp_path)
    _write_config(
        repo,
        (
            "staticChecks:\n"
            "  - name: lint\n"
            "    command: touch /tmp/pwned-static\n"
            '    suffixes: [".py"]\n'
        ),
    )
    raw = load_repo_settings(root=repo)
    assert raw.static_checks
    assert raw.static_checks[0].command

    apply = _apply_trust_tier_to_repo_settings()
    filtered, drops = apply(raw, "untrusted", source_label="untrusted CLI source")

    assert filtered.static_checks
    assert filtered.static_checks[0].name == "lint"
    assert filtered.static_checks[0].suffixes == [".py"]
    assert not filtered.static_checks[0].command
    assert any("static_checks" in key or "command" in key for key in drops)


def test_declarative_config_survives(tmp_path: Path) -> None:
    """D4 — analyzer selection and declarative knobs survive tier filtering."""
    repo = _init_git_repo(tmp_path)
    _write_config(
        repo,
        (
            "setupScript: echo hostile\n"
            "analyzers:\n"
            "  enabled: true\n"
            "  inlineBudget: 12\n"
            "  overrides:\n"
            "    actionlint:\n"
            "      enabled: false\n"
            "setupFailurePolicy: warn\n"
        ),
    )
    raw = load_repo_settings(root=repo)
    apply = _apply_trust_tier_to_repo_settings()
    filtered, _ = apply(raw, "untrusted", source_label="untrusted CLI source")

    assert filtered.setup_script is None
    assert filtered.analyzers.enabled is True
    assert filtered.analyzers.inline_budget == 12
    assert "actionlint" in filtered.analyzers.overrides
    assert filtered.analyzers.overrides["actionlint"].enabled is False
    assert filtered.setup_failure_policy == "warn"


@pytest.mark.asyncio
async def test_drop_reason_is_logged_and_reaches_the_prompt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Drop reasons are logged and threaded into the prompt for under-provisioned trees."""
    from loguru import logger

    repo = _init_git_repo(tmp_path)
    _write_config(repo, "setupScript: echo hostile\n")

    records: list[str] = []
    sink_id = logger.add(lambda message: records.append(str(message)), level="WARNING")

    try:
        raw = load_repo_settings(root=repo)
        apply = _apply_trust_tier_to_repo_settings()
        filtered, drops = apply(raw, "untrusted", source_label="untrusted CLI source")
        build_reason = _build_executable_config_skip_reason()
        skip_reason = build_reason(drops)
        for reason in drops.values():
            logger.warning("» {}", reason)
    finally:
        logger.remove(sink_id)

    assert skip_reason
    assert any(skip_reason in record for record in records)

    resolved = resolve_instructions(
        payload={
            "~mergecraft": True,
            "prompt": "review",
            "shell": "disabled",
            "push": "disabled",
            "event": {"trigger": "unknown"},
        },
        repo=RepoInfo(owner="local", name=repo.name, data={}),
        modes=[],
        agent_id="claude",
        setup_script_skip_reason=skip_reason,
    )
    assert "SETUP SCRIPT SKIPPED" in resolved.system
    assert skip_reason in resolved.system
    assert filtered.setup_script is None


@pytest.mark.asyncio
async def test_trusted_source_still_executes_scripts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Regression pin — trusted tier still runs ``setup_script``."""
    sentinel = tmp_path / "sentinel-trusted"
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script=f"touch {sentinel}"),
        event_name="pull_request",
        event_payload={
            "action": "opened",
            "pull_request": {"head": {"sha": "abc", "repo": {"fork": False}}},
        },
        env={"INPUT_SHELL": "restricted", "INPUT_PUSH": "restricted"},
    )
    assert rec.tool_context is not None
    assert rec.tool_context.trust_tier == "trusted"
    assert rec.setup_script_commands == [f"touch {sentinel}"]


def test_action_path_behaviour_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression pin — ``derive_trust_tier`` event logic is untouched."""
    from mergecraft.analyzers.trust import derive_trust_tier

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    tier = derive_trust_tier(event=SAME_REPO_PULL_REQUEST_EVENT)
    assert tier == "trusted"

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request_target")
    tier = derive_trust_tier(event={"pull_request": {"head": {"repo": {"fork": False}}}})
    assert tier == "untrusted"


@pytest.mark.asyncio
async def test_untrusted_offline_review_withholds_makefile_static_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D7 — Makefile discovery must not be reachable on untrusted CLI offline reviews."""
    import mergecraft.review.offline_agent as offline_agent
    from mergecraft.agents.shared import AgentResult
    from mergecraft.mcp.server import build_common_tools
    from mergecraft.utils.offline_diff import DiffMaterialization

    repo = _init_git_repo(tmp_path, name="hostile-make")
    (repo / "Makefile").write_text("lint:\n\techo hostile\n", encoding="utf-8")
    _git(repo, "add", "Makefile")
    _git(repo, "commit", "-m", "add makefile")

    captured: dict[str, object] = {}

    def fake_start_mcp(ctx: object, **kwargs: object) -> tuple[str, object]:
        from mergecraft.mcp.context import ToolContext

        assert isinstance(ctx, ToolContext)
        captured["static_checks_enabled"] = ctx.static_checks_enabled
        captured["tool_names"] = {tool.name for tool in build_common_tools(ctx)}
        captured["budget_tracker"] = ctx.budget_tracker
        return "http://127.0.0.1:1/mcp", lambda: None

    class FakeAgent:
        name = "claude"

        async def install(self) -> None:
            return None

        async def run(self, _ctx: object) -> AgentResult:
            return AgentResult(success=True, output="ok")

    monkeypatch.setattr(offline_agent, "start_mcp_http_server", fake_start_mcp)
    monkeypatch.setattr(offline_agent, "resolve_runtime_agent", lambda **_: FakeAgent())
    monkeypatch.setattr(offline_agent, "resolve_model", lambda slug: slug or "claude")
    monkeypatch.setattr(offline_agent, "install_bundled_skills", lambda **_: None)

    diff_file = tmp_path / "diff.patch"
    diff_file.write_text("diff --git a/Makefile b/Makefile\n", encoding="utf-8")
    materialization = DiffMaterialization(
        path=diff_file,
        base_ref="origin/main",
        line_count=1,
        empty=False,
    )

    await offline_agent.run_offline_agent_review(
        cwd=repo,
        materialization=materialization,
        prompt="review",
        model=None,
        tmpdir=tmp_path / "tmpdir",
        trust_tier="untrusted",
    )

    assert captured["static_checks_enabled"] is False
    assert "run_static_checks" not in captured["tool_names"]
    assert captured.get("budget_tracker") is not None


@pytest.mark.asyncio
async def test_config_cannot_escalate_its_own_tier(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Hostile repo config cannot execute scripts on an untrusted Action event."""
    sentinel = tmp_path / "sentinel-escalation"
    rec = await run_main_for_test(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        settings=RepoSettings(setup_script=f"touch {sentinel}"),
        env={"INPUT_SHELL": "enabled", "INPUT_PUSH": "restricted"},
        event_name="pull_request",
        event_payload=FORK_PR_PAYLOAD,
    )
    assert rec.tool_context is not None
    assert rec.tool_context.trust_tier == "untrusted"
    assert not sentinel.exists()
    assert rec.setup_script_commands == []
    skip = rec.tool_context.tool_state.setup_script_skip_reason or ""
    assert "setup_script" in skip.lower() or "dropped" in skip.lower()
