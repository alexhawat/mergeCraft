"""Lane A AP1.1 — root-side git must not execute hostile ``.git/config`` (MCB-01)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mergecraft.mcp.git import _run_git
from mergecraft.xrepo.review import _rev_parse_commit
from tests.security.hostile_git_fixtures import HostileGitRepo, build_hostile_git_repo


def test_root_side_status_does_not_execute_fsmonitor(hostile_git_repo: HostileGitRepo) -> None:
    _run_git(["status", "--porcelain"], cwd=str(hostile_git_repo.root))
    assert not hostile_git_repo.fsmonitor_sentinel.exists()


def test_root_side_diff_does_not_execute_diff_external(hostile_git_repo: HostileGitRepo) -> None:
    (hostile_git_repo.root / "README.md").write_text("changed\n", encoding="utf-8")
    output = _run_git(["diff", "README.md"], cwd=str(hostile_git_repo.root))
    assert "README.md" in output
    assert "changed" in output
    assert not hostile_git_repo.diff_external_sentinel.exists()


def test_root_side_diff_does_not_execute_textconv(hostile_git_repo: HostileGitRepo) -> None:
    (hostile_git_repo.root / "README.md").write_text("changed\n", encoding="utf-8")
    _run_git(["diff", "README.md"], cwd=str(hostile_git_repo.root))
    assert not hostile_git_repo.textconv_sentinel.exists()


def test_commit_path_does_not_execute_fsmonitor(hostile_git_repo: HostileGitRepo) -> None:
    """``commit_changes`` path must pin safe git config (hooksPath alone is insufficient)."""
    (hostile_git_repo.root / "tracked.txt").write_text("x\n", encoding="utf-8")
    _run_git(["add", "tracked.txt"], cwd=str(hostile_git_repo.root))
    _run_git(["commit", "-m", "test"], cwd=str(hostile_git_repo.root))
    assert not hostile_git_repo.fsmonitor_sentinel.exists()


def test_insteadof_rewrite_does_not_leak_git_config_value_0(
    hostile_git_repo: HostileGitRepo,
) -> None:
    from mergecraft.mcp.git import _origin_remote_url, _run_git
    from mergecraft.utils.git_hardening import git_authenticated_argv, read_remote_origin_url
    from mergecraft.utils.git_setup import git_env_for_token

    remote = "https://github.com/acme/demo.git"
    _run_git(["remote", "add", "origin", remote], cwd=str(hostile_git_repo.root))

    expanded = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=hostile_git_repo.root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert "attacker.example" in expanded, "fixture must model insteadOf expansion"

    raw = read_remote_origin_url(str(hostile_git_repo.root))
    assert raw == remote
    assert _origin_remote_url(str(hostile_git_repo.root)) == remote
    assert "attacker.example" not in raw

    fetch_argv = git_authenticated_argv(["fetch", "--no-tags", "origin"], remote_url=remote)
    assert f"url.{remote}.insteadOf={remote}" in " ".join(fetch_argv)

    env = git_env_for_token("ghs_secret_token", remote_url=remote)
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    assert "http.extraHeader" not in env.values()
    assert "attacker.example" not in env.values()

    completed = subprocess.run(
        fetch_argv,
        cwd=hostile_git_repo.root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = f"{completed.stdout}\n{completed.stderr}"
    assert "attacker.example" not in combined
    assert not hostile_git_repo.insteadof_leak_path.exists()


def test_insteadof_guard_matches_actions_checkout_origin_without_git_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identity pins must cover origin URLs stored without a ``.git`` suffix."""
    from mergecraft.mcp.git import _run_authenticated_git
    from mergecraft.utils.git_hardening import git_authenticated_argv, read_remote_origin_url

    repo = tmp_path / "checkout-shape"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    remote = "https://github.com/acme/demo"
    subprocess.run(
        ["git", "remote", "add", "origin", remote],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    config_path = repo / ".git" / "config"
    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        + """
[url "https://attacker.example/"]
\tinsteadOf = https://github.com/
""",
        encoding="utf-8",
    )

    trusted = "https://github.com/acme/demo.git"
    assert read_remote_origin_url(str(repo)) == remote

    fetch_argv = git_authenticated_argv(["fetch", "--no-tags", "origin"], remote_url=remote)
    argv_text = " ".join(fetch_argv)
    assert f"url.{remote}.insteadOf={remote}" in argv_text
    assert f"url.{trusted}.insteadOf={trusted}" in argv_text

    captured: dict[str, str] = {}

    def _capture_env(token: str, *, remote_url: str = "") -> dict[str, str]:
        captured["remote_url"] = remote_url
        return {"GIT_TERMINAL_PROMPT": "0"}

    import mergecraft.mcp.git as git_mod

    monkeypatch.setattr(git_mod, "_git_env", _capture_env)
    monkeypatch.setattr(git_mod, "_run_git", lambda *_a, **_k: "")

    _run_authenticated_git(
        ["fetch", "--no-tags", "origin"],
        cwd=str(repo),
        token="ghs_secret",
        trusted_remote_url=trusted,
    )

    assert captured["remote_url"] == trusted


def test_hostile_insteadof_fetch_scopes_auth_to_trusted_push_url(
    hostile_git_repo: HostileGitRepo,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Authenticated fetch must bind bearer auth to trusted push_url, not expanded origin."""
    from mergecraft.mcp.git import _run_authenticated_git

    remote = "https://github.com/acme/demo.git"
    trusted = "https://github.com/trusted-owner/trusted-repo.git"
    _run_git(["remote", "add", "origin", remote], cwd=str(hostile_git_repo.root))

    captured: dict[str, str] = {}

    def _capture_env(token: str, *, remote_url: str = "") -> dict[str, str]:
        captured["remote_url"] = remote_url
        return git_setup_mod.git_env_for_token(token, remote_url=remote_url)

    import mergecraft.utils.git_setup as git_setup_mod

    monkeypatch.setattr("mergecraft.mcp.git._git_env", _capture_env)
    monkeypatch.setattr(
        "mergecraft.mcp.git._run_git",
        lambda *_a, **_k: "",
    )

    _run_authenticated_git(
        ["fetch", "--no-tags", "origin"],
        cwd=str(hostile_git_repo.root),
        token="ghs_secret",
        trusted_remote_url=trusted,
    )
    assert captured["remote_url"] == trusted
    assert "attacker.example" not in captured["remote_url"]


def test_xrepo_checkout_is_equally_protected(hostile_git_repo: HostileGitRepo) -> None:
    """H-7: xrepo ``_rev_parse_commit`` must use hardened git argv."""
    _rev_parse_commit(hostile_git_repo.root, "HEAD")
    assert not hostile_git_repo.fsmonitor_sentinel.exists()


@pytest.fixture
def hostile_git_repo(tmp_path: Path) -> HostileGitRepo:
    return build_hostile_git_repo(tmp_path)
