"""Lane A AP1.1 — ``git_argv`` pins every safe config key (MCB-01 / D2)."""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path

_EXPECTED_SAFE_KEYS: tuple[str, ...] = (
    "core.fsmonitor=false",
    "core.hooksPath=/dev/null",
    "core.sshCommand=ssh",
    "protocol.ext.allow=never",
    "core.pager=cat",
)


def test_git_argv_pins_every_safe_config_key() -> None:
    from mergecraft.utils.git_hardening import GIT_SAFE_CONFIG, git_argv

    flat = " ".join(GIT_SAFE_CONFIG)
    for key in _EXPECTED_SAFE_KEYS:
        assert key in flat, f"missing safe config pin: {key}"
    argv = git_argv(["status"])
    assert argv[0] == "git"
    assert argv[-1] == "status"
    for key in _EXPECTED_SAFE_KEYS:
        assert key.split("=")[0] in flat


def test_git_argv_injects_no_ext_diff_for_diff_family() -> None:
    from mergecraft.utils.git_hardening import git_argv

    diff_argv = git_argv(["diff", "HEAD"])
    assert diff_argv[diff_argv.index("diff") + 1 : diff_argv.index("diff") + 3] == [
        "--no-ext-diff",
        "--no-textconv",
    ]

    show_argv = git_argv(["-C", "/repo", "show", "HEAD:README.md"])
    show_idx = show_argv.index("show")
    assert show_argv[show_idx + 1 : show_idx + 3] == ["--no-ext-diff", "--no-textconv"]

    log_argv = git_argv(["log", "-p", "-1"])
    log_idx = log_argv.index("log")
    assert log_argv[log_idx + 1 : log_idx + 3] == ["--no-ext-diff", "--no-textconv"]

    assert "--no-ext-diff" not in git_argv(["status"])
    assert "--no-textconv" not in git_argv(["status"])
    assert "--no-ext-diff" not in git_argv(["log", "-1", "--oneline"])
    assert "--no-textconv" not in git_argv(["log", "-1", "--oneline"])


def test_git_authenticated_argv_pins_identity_rewrite_for_remote_url() -> None:
    from mergecraft.utils.git_hardening import git_authenticated_argv

    remote = "https://github.com/acme/demo.git"
    argv = git_authenticated_argv(["fetch", "origin"], remote_url=remote)
    argv_text = " ".join(argv)
    assert f"url.{remote}.insteadOf={remote}" in argv_text
    assert "url.https://github.com/acme/demo.insteadOf=https://github.com/acme/demo" in argv_text


def test_git_remote_identity_urls_includes_git_suffix_variants() -> None:
    from mergecraft.utils.git_hardening import git_remote_identity_urls

    assert git_remote_identity_urls("https://github.com/acme/demo") == (
        "https://github.com/acme/demo.git",
        "https://github.com/acme/demo",
    )
    assert git_remote_identity_urls("https://github.com/acme/demo.git") == (
        "https://github.com/acme/demo.git",
        "https://github.com/acme/demo",
    )


def test_git_env_for_token_scopes_auth_header_to_trusted_host() -> None:
    from mergecraft.utils.git_setup import git_env_for_token

    env = git_env_for_token(
        "ghs_secret",
        remote_url="https://github.com/acme/demo.git",
    )
    expected = base64.b64encode(b"x-access-token:ghs_secret").decode()
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"] == f"Authorization: Basic {expected}"
    assert "http.extraHeader" not in env.values()


def test_read_remote_origin_url_ignores_insteadof(tmp_path: Path) -> None:
    from mergecraft.utils.git_hardening import read_remote_origin_url

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    remote = "https://github.com/acme/demo.git"
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
    expanded = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert "attacker.example" in expanded
    assert read_remote_origin_url(str(repo)) == remote
