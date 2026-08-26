"""Lane A AP1.5 — privilege identity gates (MCB-24 / MCB-32 / D11)."""

from __future__ import annotations

import pytest

from mergecraft.utils.privilege import wrap_agent_command


def test_root_outside_action_image_refuses_with_policy_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mergecraft.main import _ConfigurationError

    monkeypatch.setattr("mergecraft.utils.privilege.os.getuid", lambda: 0)
    monkeypatch.delenv("MERGECRAFT_ALLOW_ROOT", raising=False)
    monkeypatch.setattr("mergecraft.utils.privilege._in_action_image", lambda: False)
    with pytest.raises(_ConfigurationError, match=r"policy|action image|MERGECRAFT_ALLOW_ROOT"):
        wrap_agent_command(["echo", "hi"])


@pytest.mark.xfail(
    reason="green after AP6: image identity gate + hardened setpriv argv",
    strict=False,
)
def test_allow_root_env_var_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mergecraft.utils.privilege.os.getuid", lambda: 0)
    monkeypatch.setenv("MERGECRAFT_ALLOW_ROOT", "1")
    monkeypatch.setattr("mergecraft.utils.privilege._in_action_image", lambda: False)
    monkeypatch.setattr("mergecraft.utils.privilege.shutil.which", lambda _n: "/usr/bin/setpriv")
    wrapped = wrap_agent_command(["echo", "hi"])
    assert wrapped[0] == "setpriv"


def test_in_action_image_detects_is_sandbox_and_opt_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft.utils.privilege import _in_action_image

    monkeypatch.setenv("IS_SANDBOX", "1")
    monkeypatch.setattr(
        "mergecraft.utils.privilege.Path.is_dir",
        lambda self: str(self).endswith("/opt/mergecraft"),
    )
    assert _in_action_image() is True


@pytest.mark.xfail(
    reason="green after AP6: image identity gate + hardened setpriv argv",
    strict=False,
)
def test_setpriv_argv_carries_no_new_privs_and_cleared_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    from unittest.mock import MagicMock

    class _Pw:
        pw_uid = 10001
        pw_gid = 10001
        pw_name = "mergecraft"

    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _Pw()
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)
    monkeypatch.setattr("mergecraft.utils.privilege.os.getuid", lambda: 0)
    monkeypatch.setattr("mergecraft.utils.privilege._in_action_image", lambda: True)
    monkeypatch.setattr("mergecraft.utils.privilege.shutil.which", lambda _n: "/usr/bin/setpriv")
    argv = wrap_agent_command(["agent"])
    assert "--no-new-privs" in argv
    assert "--inh-caps=-all" in argv
    assert "--bounding-set=-all" in argv
