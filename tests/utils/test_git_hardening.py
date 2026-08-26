"""Lane A AP1.1 — ``git_argv`` pins every safe config key (MCB-01 / D2)."""

from __future__ import annotations

_EXPECTED_SAFE_KEYS: tuple[str, ...] = (
    "core.fsmonitor=false",
    "diff.external=",
    "core.hooksPath=/dev/null",
    "uploadpack.packObjectsHook=",
    "core.sshCommand=ssh",
    "core.gitProxy=",
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
