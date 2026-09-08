"""Plan W2 — credentials as capabilities + secret lifecycle (D2, punch ``#5/#6/#13/#15``).

Contracts:

- Agent subprocess env is an explicit allowlist: no ``GIT_ASKPASS``,
  ``GITHUB_TOKEN``/``GH_TOKEN``, no non-active provider keys, no
  ``ACTIONS_ID_TOKEN_*`` (W2.1/D2).
- ``GIT_ASKPASS`` is removed from the shared environment; any retained askpass
  file is ``0o600`` inside a ``0o700`` dir the agent UID cannot read (W2.2).
- The run temp dir is removed on success **and** on failure (W2.3).
- ``wipe_runner_leak_surface`` only unlinks mergeCraft-owned paths — foreign
  ``*.sh`` / ``git-credentials-*.config`` files survive (W2.4).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from loguru import logger

from mergecraft.agents import claude, codex, gemini
from mergecraft.agents import opencode as opencode_mod
from mergecraft.security.broker import CODEX_BROKER_BEARER_ENV
from mergecraft.utils.git_setup import (
    register_created_path,
    reviewer_askpass_credentials_dir,
    setup_git,
    wipe_runner_leak_surface,
    write_askpass_script,
)
from tests.support.run_main_harness import FakeAgent, run_main_for_test


def _path_exists(path: str) -> bool:
    """Sync helper — keeps blocking FS calls out of async test bodies."""
    return Path(path).exists()


def _rmtree(path: str) -> None:
    """Sync helper — remove a leftover temp dir without blocking the loop inline."""
    import shutil

    shutil.rmtree(path, ignore_errors=True)


# Credential-shaped names a W2-compliant agent env must never contain.
# ``ANTHROPIC_API_KEY`` is the *active* provider key for claude and is allowed
# for that agent only (D2); each parametrized case lists its own allowlist.
_PLANTED_SECRETS = {
    "GIT_ASKPASS": "/run/secrets/git-askpass.sh",
    "GITHUB_TOKEN": "gho_planted_github_token",
    "GH_TOKEN": "gho_planted_gh_token",
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.example/abc",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "planted-oidc-token",
    "ANTHROPIC_API_KEY": "sk-ant-planted",
    "OPENAI_API_KEY": "sk-openai-planted",
    "GEMINI_API_KEY": "gemini-planted",
    "GOOGLE_API_KEY": "google-planted",
    "CURSOR_API_KEY": "cursor-planted",
}

_ALWAYS_FORBIDDEN = (
    "GIT_ASKPASS",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
)

#: agent id → provider key that agent alone may keep (D2: active provider only)
_ACTIVE_PROVIDER_KEY = {
    "claude": "ANTHROPIC_API_KEY",
    "codex": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "opencode": None,
}


def _assert_no_credentials(env: dict[str, str], *, active_key: str | None) -> None:
    for name in _ALWAYS_FORBIDDEN:
        assert name not in env, f"agent env leaks {name}"
    for name in _PLANTED_SECRETS:
        if name == active_key:
            continue
        assert name not in env, f"agent env leaks non-active provider key {name}"
    allowed_token_shaped = {CODEX_BROKER_BEARER_ENV}
    if active_key is not None:
        allowed_token_shaped.add(active_key)
    for name in env:
        assert "TOKEN" not in name or name in allowed_token_shaped, (
            f"agent env carries unexpected token-shaped variable {name}"
        )


@pytest.mark.parametrize("agent_id", ["claude", "codex", "gemini"])
def test_agent_env_contains_no_credentials(
    agent_id: str, make_agent_run_ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W2.1 — the env handed to the agent CLI carries no usable credential.

    Fails if the allowlist is deleted: ``_build_env`` falling back to
    ``dict(os.environ)`` re-leaks every planted name and turns this red.
    """
    for key, value in _PLANTED_SECRETS.items():
        monkeypatch.setenv(key, value)
    ctx = make_agent_run_ctx()
    builders = {
        "claude": claude._build_env,
        "codex": codex._build_env,
        "gemini": gemini._build_env,
    }
    env = builders[agent_id](ctx)
    _assert_no_credentials(env, active_key=_ACTIVE_PROVIDER_KEY[agent_id])


def test_codex_brokered_env_throwaway_in_openai_api_key_allowed(
    make_agent_run_ctx, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W2.1 broker path — throwaway in ``OPENAI_API_KEY`` satisfies the codex active-key guard."""
    from tests.agents.support_codex_credential_broker import (
        REAL_OPENAI_API_KEY_FIXTURE,
        brokered_codex_context,
        prepare_codex_brokered_run,
    )

    monkeypatch.setenv("OPENAI_API_KEY", REAL_OPENAI_API_KEY_FIXTURE)
    monkeypatch.delenv("CODEX_AUTH_JSON", raising=False)
    for key, value in _PLANTED_SECRETS.items():
        if key == "OPENAI_API_KEY":
            continue
        monkeypatch.setenv(key, value)

    ctx = brokered_codex_context(
        tmp_path,
        mcp_server_url="",
        mcp_auth_token="",
    )
    prepared = prepare_codex_brokered_run(ctx)
    _assert_no_credentials(prepared.agent_env, active_key=_ACTIVE_PROVIDER_KEY["codex"])
    throwaway = prepared.agent_env.get("OPENAI_API_KEY")
    assert throwaway, "broker throwaway must be routed through OPENAI_API_KEY for Codex 0.149"
    assert throwaway != REAL_OPENAI_API_KEY_FIXTURE


def test_opencode_agent_env_contains_no_credentials() -> None:
    """W2.1 — opencode must not pass the raw process environment to its CLI.

    opencode has no ``_build_env`` seam today; this pins the contract at the
    source level: the module must not build the child env from a verbatim
    ``os.environ`` copy. An allowlist builder (any name) satisfies it.
    """
    import ast

    source = Path(opencode_mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    verbatim_copies = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "dict"
        and node.args
        and isinstance(node.args[0], ast.Attribute)
        and isinstance(node.args[0].value, ast.Name)
        and node.args[0].value.id == "os"
        and node.args[0].attr == "environ"
    ]
    assert not verbatim_copies, (
        "opencode still copies os.environ verbatim into the agent environment"
    )


def test_setup_git_does_not_export_askpass_to_shared_env(
    planted_repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W2.2 — git auth is brokered per-op via http.extraHeader, not ambient askpass."""
    from mergecraft.mcp.tool_state import init_tool_state

    monkeypatch.delenv("GIT_ASKPASS", raising=False)
    monkeypatch.chdir(planted_repo.path)
    state = init_tool_state(owner="acme", name="demo", dir=str(planted_repo.path))
    setup_git(
        git_token="ghs_secret_token",
        owner="acme",
        name="demo",
        tool_state=state,
        shell="restricted",
        tmpdir=str(tmp_path),
    )
    assert "GIT_ASKPASS" not in os.environ, (
        "GIT_ASKPASS exported to the shared environment is readable by the agent"
    )


def test_askpass_file_not_world_or_group_readable(tmp_path: Path) -> None:
    """D2 — a retained askpass file must be unreadable by anyone but the owner."""
    askpass = Path(write_askpass_script(str(tmp_path), "ghs_secret_token"))
    file_mode = stat.S_IMODE(askpass.stat().st_mode)
    dir_mode = stat.S_IMODE(askpass.parent.stat().st_mode)
    assert file_mode == 0o600, f"askpass mode {file_mode:o} != 0o600"
    assert dir_mode == 0o700, f"askpass dir mode {dir_mode:o} != 0o700"
    assert not (file_mode & (stat.S_IRGRP | stat.S_IROTH)), "askpass readable by group/other"


def test_agent_cannot_locate_askpass_script(
    planted_repo, make_agent_run_ctx, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W2.5 — after setup, the agent's env must not reveal the askpass path.

    Combined contract: ``setup_git`` configures whatever the entrypoint needs,
    but the *agent* snapshot contains neither ``GIT_ASKPASS`` nor the file path.
    """
    from mergecraft.mcp.tool_state import init_tool_state

    monkeypatch.chdir(planted_repo.path)
    state = init_tool_state(owner="acme", name="demo", dir=str(planted_repo.path))
    setup_git(
        git_token="ghs_secret_token",
        owner="acme",
        name="demo",
        tool_state=state,
        shell="restricted",
        tmpdir=str(tmp_path),
    )
    askpass_path = str(reviewer_askpass_credentials_dir(str(tmp_path)) / "git-askpass.sh")
    assert not Path(askpass_path).exists(), "askpass helper must be shredded after setup_git"
    env = claude._build_env(make_agent_run_ctx())
    assert "GIT_ASKPASS" not in env
    assert askpass_path not in env.values()


async def test_tmpdir_removed_after_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W2.3 — the credential-bearing temp dir is removed on the success path."""
    rec = await run_main_for_test(monkeypatch=monkeypatch, tmp_path=tmp_path, cleanup_tmpdir=False)
    try:
        assert rec.result is not None
        assert rec.result.success, f"run failed: {rec.result}"
        assert rec.tmpdir is not None
        assert not _path_exists(rec.tmpdir), (
            f"MERGECRAFT_TEMP_DIR {rec.tmpdir} survived a successful run"
        )
    finally:
        if rec.tmpdir:
            _rmtree(rec.tmpdir)


async def test_tmpdir_removed_after_agent_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """W2.3 — cleanup happens even when the agent raises (no residue on error)."""
    agent = FakeAgent(result=RuntimeError("agent exploded"))
    rec = await run_main_for_test(
        monkeypatch=monkeypatch, tmp_path=tmp_path, agent=agent, cleanup_tmpdir=False
    )
    try:
        assert rec.result is not None
        assert not rec.result.success
        assert rec.tmpdir is not None
        assert not _path_exists(rec.tmpdir), (
            f"MERGECRAFT_TEMP_DIR {rec.tmpdir} survived a failed run"
        )
    finally:
        if rec.tmpdir:
            _rmtree(rec.tmpdir)


def test_wipe_leaves_foreign_files_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W2.4 — the wipe must never unlink files mergeCraft did not create.

    Fails if the ownership guard is deleted: the planted foreign files vanish
    and the assertions on their contents turn red.
    """
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    foreign_sh = runner_temp / "other-tool.sh"
    foreign_sh.write_text("#!/bin/sh\necho other-tool\n", encoding="utf-8")
    foreign_creds = runner_temp / "git-credentials-foreign.config"
    foreign_creds.write_text("https://x:secret@example.com\n", encoding="utf-8")
    commands_dir = runner_temp / "_runner_file_commands"
    commands_dir.mkdir()
    foreign_command = commands_dir / "set_output_other-guid"
    foreign_command.write_text("not-mergecraft\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))

    wipe_runner_leak_surface()

    assert foreign_sh.exists(), "foreign *.sh was wiped — wipe is not ownership-scoped"
    assert foreign_creds.exists(), "foreign git-credentials file was wiped"
    assert foreign_command.exists(), "foreign _runner_file_commands entry was wiped"


def test_wipe_still_removes_registered_mergecraft_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W2.4 — ownership scoping must not neuter the wipe for owned paths.

    ``register_created_path`` records mergeCraft-created leak-surface files,
    and the wipe removes exactly those.
    """
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    owned = runner_temp / "git-askpass-mc123.sh"
    owned.write_text("#!/bin/sh\necho secret\n", encoding="utf-8")
    register_created_path(str(owned))
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))

    wipe_runner_leak_surface()

    assert not owned.exists(), "mergeCraft-owned leak-surface file was not wiped"


def test_wipe_preserves_github_output_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Baseline — the active ``$GITHUB_OUTPUT`` file must survive the wipe."""
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    output_file = runner_temp / "github_output"
    output_file.write_text("result=ok\n", encoding="utf-8")
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    wipe_runner_leak_surface()

    assert output_file.exists()


def test_askpass_script_contents_never_logged(tmp_path: Path) -> None:
    """Convention 6 — writing the askpass helper must not log the token.

    Loguru is the only logger under ``src/mergecraft/`` (CLAUDE.md), so the
    capture sink attaches directly to it.
    """
    token = "ghs_extremely_secret_token"
    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="TRACE")
    try:
        write_askpass_script(str(tmp_path), token)
    finally:
        logger.remove(sink_id)
    joined = "\n".join(captured)
    assert token not in joined, "askpass token leaked into logs"
