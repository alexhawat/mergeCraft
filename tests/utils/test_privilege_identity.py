"""Lane A AP1.5 — privilege identity gates (MCB-24 / MCB-32 / D11)."""

from __future__ import annotations

import sys

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


def test_allow_root_env_var_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    """``MERGECRAFT_ALLOW_ROOT=1`` admits root and still hardens the ``setpriv`` argv.

    Stubs the passwd lookup and the ``--bounding-set`` probe the same way the
    sibling ``test_setpriv_argv_carries_no_new_privs_and_cleared_caps`` does, so
    the pin passes on macOS and Linux without a real ``mergecraft`` user.
    """
    from unittest.mock import MagicMock

    class _Pw:
        pw_uid = 10001
        pw_gid = 10001
        pw_name = "mergecraft"

    fake_pwd = MagicMock()
    fake_pwd.getpwnam.return_value = _Pw()
    monkeypatch.setitem(sys.modules, "pwd", fake_pwd)
    monkeypatch.setattr("mergecraft.utils.privilege.os.getuid", lambda: 0)
    monkeypatch.setenv("MERGECRAFT_ALLOW_ROOT", "1")
    monkeypatch.setattr("mergecraft.utils.privilege._in_action_image", lambda: False)
    monkeypatch.setattr("mergecraft.utils.privilege.shutil.which", lambda _n: "/usr/bin/setpriv")
    monkeypatch.setattr(
        "mergecraft.utils.privilege._setpriv_supports_bounding_set",
        lambda: True,
    )
    wrapped = wrap_agent_command(["echo", "hi"])
    assert wrapped[0] == "setpriv"
    assert "--no-new-privs" in wrapped
    assert "--inh-caps=-all" in wrapped
    assert "--bounding-set=-all" in wrapped
    assert wrapped[-2:] == ["echo", "hi"]


def test_in_action_image_detects_is_sandbox_and_opt_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft.utils.privilege import _in_action_image

    monkeypatch.setenv("IS_SANDBOX", "1")
    monkeypatch.setattr(
        "mergecraft.utils.privilege.Path.is_dir",
        lambda self: str(self).endswith("/opt/mergecraft"),
    )
    assert _in_action_image() is True


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
    monkeypatch.setattr(
        "mergecraft.utils.privilege._setpriv_supports_bounding_set",
        lambda: True,
    )
    argv = wrap_agent_command(["agent"])
    assert "--no-new-privs" in argv
    assert "--inh-caps=-all" in argv
    assert "--bounding-set=-all" in argv


def test_no_non_strict_xfail_remains_in_this_file() -> None:
    """The quarantined privilege pin is fixed or made strict — never left non-strict.

    A ``strict=False`` mark quietly absorbs a real failure. ``test_allow_root_env_var_overrides``
    is the only non-strict xfail in this file, and it is quarantined by a test bug
    (the missing passwd/bounding-set stubs the sibling above supplies), not by
    product behaviour. This pin turns that quarantine into a ratchet DC4.4 removes.
    """
    module = sys.modules[__name__]
    surviving = module.test_setpriv_argv_carries_no_new_privs_and_cleared_caps
    # Surviving surface: the stubbed hardened-argv sibling is a plain, passing test.
    assert callable(surviving)
    for name, obj in vars(module).items():
        if not name.startswith("test_") or not callable(obj):
            continue
        for mark in getattr(obj, "pytestmark", []):
            if mark.name != "xfail":
                continue
            assert mark.kwargs.get("strict") is not False, (
                f"{name} still carries a non-strict xfail: {mark.kwargs!r}"
            )
