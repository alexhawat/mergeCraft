"""PR S2 — privilege drop fails closed when the boundary is unavailable.

Contracts:

- When the action runs as root inside the image, the agent subprocess must drop
  to the unprivileged ``mergecraft`` user via ``setpriv``. If either
  ``setpriv`` or the agent user is missing, the run must abort as a
  configuration error — silently executing the agent as root would silently
  disable the security boundary (F4').
- The build image must itself refuse to build when either artifact is absent
  (D11), so a tampered image never reaches a runner.
- Non-root invocations must continue to work unchanged (D12); the boundary only
  applies inside the action image.

These tests run as non-root in CI; the root path is simulated by monkeypatching
``os.getuid``, ``shutil.which``, and ``pwd.getpwnam`` — never by adding a
production-side test hook (convention 10).
"""

from __future__ import annotations

import asyncio
import os
import pwd
import shutil
from pathlib import Path

import pytest
from loguru import logger

from mergecraft.main import _classify_error_outcome, _ConfigurationError
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils import privilege

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _REPO_ROOT / "Dockerfile"


class _FakePwnam:
    """Stand-in for ``pwd.struct_passwd`` carrying only the fields the code reads."""

    def __init__(self, pw_name: str, pw_uid: int = 10001, pw_gid: int = 10001) -> None:
        self.pw_name = pw_name
        self.pw_uid = pw_uid
        self.pw_gid = pw_gid


def _force_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every branch in ``wrap_agent_command``/``prepare_workspace_for_agent``
    see the action-image root path, regardless of the host's real uid."""
    monkeypatch.setattr(os, "getuid", lambda: 0)
    monkeypatch.setattr(privilege, "_in_action_image", lambda: True)
    monkeypatch.setattr(privilege, "_setpriv_supports_bounding_set", lambda: True)


@pytest.fixture(autouse=True)
def _reset_agent_user_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``agent_user_name`` deterministic across tests — the default unless a
    specific case overrides it. ``monkeypatch`` is autouse so the env var never
    leaks across tests."""
    monkeypatch.delenv("MERGECRAFT_AGENT_USER", raising=False)


# ---------------------------------------------------------------------------
# wrap_agent_command
# ---------------------------------------------------------------------------


def test_root_without_setpriv_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Root + no ``setpriv`` on PATH → abort, not an unwrapped command."""
    # Arrange — pretend we're root, and that setpriv does not exist anywhere on PATH.
    _force_root(monkeypatch)
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == "setpriv" else f"/usr/bin/{name}"
    )

    # Act + Assert — the boundary has to fail closed as the same exception type
    # ``main._classify_error_outcome`` maps to ``RunOutcome.configuration_error``.
    with pytest.raises(_ConfigurationError, match="setpriv"):
        privilege.wrap_agent_command(["claude", "--help"])


def test_root_without_agent_user_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``setpriv`` present but the agent user missing → abort at the wrap site,
    not at ``prepare_workspace_for_agent`` further down."""
    # Arrange — root + setpriv available, but the user does not exist.
    _force_root(monkeypatch)
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/setpriv" if name == "setpriv" else None
    )

    def _raise_keyerror(_name: str) -> _FakePwnam:
        raise KeyError(_name)

    monkeypatch.setattr(pwd, "getpwnam", _raise_keyerror)

    # Act + Assert — fail closed with the configuration-error type.
    with pytest.raises(_ConfigurationError, match="mergecraft"):
        privilege.wrap_agent_command(["claude", "--help"])


def test_root_with_setpriv_and_user_wraps_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy-path pin: argv must be exactly the ``setpriv`` invocation contract.

    Fails if any flag regresses (e.g. ``--reuid`` dropped, ``--init-groups``
    removed) or if the drop stops happening on the root path.
    """
    # Arrange — root + setpriv + the mergecraft user all resolve cleanly.
    _force_root(monkeypatch)
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/setpriv" if name == "setpriv" else None
    )
    monkeypatch.setattr(pwd, "getpwnam", lambda _name: _FakePwnam(_name))

    # Act
    wrapped = privilege.wrap_agent_command(["claude", "--help"])

    # Assert — pin the exact argv shape; any drift here is a regression on the
    # privilege drop contract (the verifier reads uid from inside the child).
    assert wrapped == [
        "setpriv",
        "--no-new-privs",
        "--inh-caps=-all",
        "--bounding-set=-all",
        "--reuid=mergecraft",
        "--regid=mergecraft",
        "--init-groups",
        "claude",
        "--help",
    ]


def test_non_root_returns_command_unwrapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D12 — outside the action image, ``wrap_agent_command`` is a no-op even
    if the rest of the boundary tools happen to exist (a developer running
    ``mergecraft diff-review`` on a workstation)."""
    # Arrange — non-root, but setpriv *is* available, so we know the function
    # short-circuited before reaching the wrap branch.
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/setpriv" if name == "setpriv" else None
    )

    # Act
    out = privilege.wrap_agent_command(["claude", "--help"])

    # Assert — unchanged argv, no raise, no list aliasing.
    assert out == ["claude", "--help"]


def test_custom_agent_user_via_env_is_honoured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MERGECRAFT_AGENT_USER`` is respected on the happy path; a nonexistent
    custom user still fails closed at the wrap site."""
    _force_root(monkeypatch)
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/setpriv" if name == "setpriv" else None
    )

    # Case 1: env var honoured.
    monkeypatch.setenv("MERGECRAFT_AGENT_USER", "reviewer")
    monkeypatch.setattr(pwd, "getpwnam", lambda name: _FakePwnam(name))
    wrapped = privilege.wrap_agent_command(["claude", "--help"])
    assert wrapped[4] == "--reuid=reviewer"
    assert wrapped[5] == "--regid=reviewer"

    # Case 2: env var names a user that doesn't exist → fail closed.
    monkeypatch.setattr(pwd, "getpwnam", lambda _name: (_ for _ in ()).throw(KeyError(_name)))
    with pytest.raises(_ConfigurationError, match="reviewer"):
        privilege.wrap_agent_command(["claude", "--help"])


def test_failure_is_logged_at_error_not_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the drop is unavailable, the log record must be ``ERROR`` — the old
    ``debug`` log line is exactly what let the failure pass unnoticed."""
    # Arrange — root + no setpriv, so the failure path runs.
    _force_root(monkeypatch)
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == "setpriv" else f"/usr/bin/{name}"
    )

    records: list[tuple[str, str]] = []

    def _capture(record: object) -> None:
        entry = record.record  # type: ignore[attr-defined]
        records.append((entry["level"].name, entry["message"]))

    sink_id = logger.add(_capture, level="DEBUG")
    try:
        with pytest.raises(_ConfigurationError):
            privilege.wrap_agent_command(["claude", "--help"])
    finally:
        logger.remove(sink_id)

    # Assert — at least one ERROR record, and nothing dropped the failure at DEBUG.
    error_records = [msg for level, msg in records if level == "ERROR"]
    assert error_records, "privilege-drop failure must log at ERROR, got: " + ", ".join(
        f"{lvl}:{msg!r}" for lvl, msg in records
    )
    debug_records = [msg for level, msg in records if level == "DEBUG"]
    assert not any("setpriv" in m.lower() for m in debug_records), (
        "the old debug line for setpriv absence must be gone: " + ", ".join(debug_records)
    )


# ---------------------------------------------------------------------------
# UID 0 reject — fail closed when the resolved user has UID/GID 0
# ---------------------------------------------------------------------------


def test_root_user_rejected_by_uid_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``pwd.getpwnam`` returning ``pw_uid=0``/``pw_gid=0`` is a fail-open hole:
    ``setpriv --reuid=root`` would run the agent as root, defeating the drop.
    The username is not the security boundary — the UID is — so a record whose
    ``pw_name`` is anything (including ``root``) but whose ``pw_uid`` is 0
    must be rejected with a message that names the UID, not just "user missing".
    """
    _force_root(monkeypatch)
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/setpriv" if name == "setpriv" else None
    )
    monkeypatch.setattr(pwd, "getpwnam", lambda name: _FakePwnam(name, pw_uid=0, pw_gid=0))

    with pytest.raises(_ConfigurationError, match="uid=0"):
        privilege.wrap_agent_command(["claude", "--help"])


def test_zero_uid_rejected_even_when_username_is_not_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured user named anything but ``root`` that happens to resolve to
    UID 0 must still be rejected. The username is a hint; the UID is the
    boundary. Without this check, a misconfigured image that maps e.g.
    ``reviewer`` to ``uid=0`` would silently run the agent as root.
    """
    _force_root(monkeypatch)
    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/setpriv" if name == "setpriv" else None
    )
    monkeypatch.setattr(pwd, "getpwnam", lambda _name: _FakePwnam("notroot", pw_uid=0, pw_gid=0))

    with pytest.raises(_ConfigurationError, match="notroot"):
        privilege.wrap_agent_command(["claude", "--help"])


def test_zero_uid_rejected_in_prepare_workspace_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The same UID 0 check must guard ``prepare_workspace_for_agent`` —
    otherwise the chown helper would silently ``chown -R … 0:0 …`` and the
    agent process would land on a root-owned workspace. The guard at the wrap
    site is not enough; both call sites must fail closed.
    """
    _force_root(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    monkeypatch.setattr(pwd, "getpwnam", lambda name: _FakePwnam(name, pw_uid=0, pw_gid=0))

    with pytest.raises(_ConfigurationError, match="uid=0"):
        privilege.prepare_workspace_for_agent(str(workspace))


# ---------------------------------------------------------------------------
# prepare_workspace_for_agent
# ---------------------------------------------------------------------------


def test_prepare_workspace_missing_user_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When running as root, the silently-``return`` branch at the old
    ``except ImportError, KeyError:`` must be split: ``KeyError`` is a real
    failure and must raise the configuration-error type. ``ImportError`` on
    ``pwd`` (non-POSIX) is the one we still tolerate."""
    _force_root(monkeypatch)
    workspace = tmp_path / "ws"
    workspace.mkdir()

    # Case 1 — KeyError on getpwnam: must raise, not silently return.
    def _raise_keyerror(_name: str) -> _FakePwnam:
        raise KeyError(_name)

    monkeypatch.setattr(pwd, "getpwnam", _raise_keyerror)
    with pytest.raises(_ConfigurationError, match="mergecraft"):
        privilege.prepare_workspace_for_agent(str(workspace))

    # Case 2 — ImportError on the pwd import: non-POSIX host, action image
    # cannot be running here; the legacy silent-return behaviour is preserved.
    import builtins

    real_import = builtins.__import__

    def _import_blocking_pwd(name: str, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if name == "pwd":
            raise ImportError("pwd unavailable on this platform")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import_blocking_pwd)
    # Should not raise.
    privilege.prepare_workspace_for_agent(str(workspace))


# ---------------------------------------------------------------------------
# main._classify_error_outcome wires the abort into the right outcome bucket
# ---------------------------------------------------------------------------


def test_abort_maps_to_configuration_error_outcome() -> None:
    """The ``_ConfigurationError`` raised by ``wrap_agent_command`` must reach
    ``_classify_error_outcome`` as ``RunOutcome.configuration_error``, so the
    GitHub check conclusion is ``neutral`` rather than an uncaught crash."""
    outcome = _classify_error_outcome(_ConfigurationError("setpriv unavailable"))
    assert outcome is RunOutcome.configuration_error


def test_main_missing_agent_user_fails_closed_as_configuration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """End-to-end — a missing agent user surfaces as ``configuration_error``.

    The S2 contract must hold for the *secondary* path
    (``prepare_workspace_for_agent`` in ``main()``), not only the
    ``wrap_agent_command`` wrap site. Driving ``main()`` with a missing user
    must yield a classified ``MainResult`` (``RunOutcome.configuration_error``)
    — not an uncaught exception escaping ``main()`` entirely, which would
    crash ``cli/gha_cmd.py:gha_root`` unclassified.
    """
    from mergecraft.main import main

    # Pretend we're root in the action image with a missing agent user.
    _force_root(monkeypatch)

    def _raise_keyerror(_name: str) -> _FakePwnam:
        raise KeyError(_name)

    monkeypatch.setattr(pwd, "getpwnam", _raise_keyerror)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))

    result = asyncio.run(main())
    assert result.success is False
    assert result.outcome is RunOutcome.configuration_error
    assert "mergecraft" in (result.error or "")


# ---------------------------------------------------------------------------
# Dockerfile build-time assertion (D11)
# ---------------------------------------------------------------------------


def _dockerfile_run_lines(dockerfile_text: str) -> list[str]:
    """Concatenate every ``RUN`` instruction body in source order.

    The Dockerfile uses line-continuation backslashes inside ``RUN``, so a
    naive split-on-``\n`` will fragment the body. This walks the file once,
    tracking line continuations, and returns the joined instruction body for
    each ``RUN`` line. Comment-only lines (``#``) inside a ``RUN`` survive the
    parse because they are not stripped by the Dockerfile parser either —
    what matters for the assertion is that the **tokens** ``command``,
    ``getent``, and ``mergecraft`` appear together in at least one ``RUN``.
    """
    bodies: list[str] = []
    buffer: list[str] = []
    in_run = False
    for raw in dockerfile_text.splitlines():
        stripped = raw.strip()
        if in_run:
            buffer.append(raw)
            if stripped.endswith("\\"):
                continue
            bodies.append("\n".join(buffer))
            buffer = []
            in_run = False
            continue
        if stripped.startswith("RUN "):
            buffer = [raw]
            in_run = True
            if stripped.endswith("\\"):
                continue
            bodies.append(raw)
            buffer = []
            in_run = False
    # Flush a trailing unterminated continuation, in case the file ends mid-RUN.
    if in_run and buffer:
        bodies.append("\n".join(buffer))
    return bodies


def test_dockerfile_asserts_setpriv_and_agent_user() -> None:
    """D11 — the image must refuse to build when ``setpriv`` or the agent user
    is missing. The assertion is parsed out of the ``RUN`` instruction set, not
    string-matched against a comment, so reformatting comments cannot silently
    regress the contract."""
    assert _DOCKERFILE.exists(), f"missing {_DOCKERFILE}"
    text = _DOCKERFILE.read_text(encoding="utf-8")
    run_bodies = _dockerfile_run_lines(text)

    matching = [
        body
        for body in run_bodies
        if "setpriv" in body and "mergecraft" in body and "exit 1" in body
    ]
    assert matching, (
        "Dockerfile must contain a RUN instruction that asserts setpriv + "
        "mergecraft user are present and exits 1 otherwise; none found."
    )
