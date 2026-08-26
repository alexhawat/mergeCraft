"""Lane A AP1.1 — ``git_argv`` pins every safe config key (MCB-01 / D2)."""

from __future__ import annotations

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
