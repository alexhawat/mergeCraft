"""No credential path in the action image is readable by the agent user.

Plan 35 moved what it could: the askpass file is ``0:0 0600`` and the run tmpdir
is agent-owned by design. What remains is the runner's mounts and kernel state,
which no ownership change can move, plus the Codex auth file
(``agents/codex._setup_codex_auth``), which the image *does* control. This module
pins two things:

* the Codex auth file is written ``0600`` root-owned (checked anywhere); and
* **in the action image only** — the privileged Linux container the review runs
  in — none of the candidate credential paths is readable by the ``mergecraft``
  agent user. Off that image the readability class skips with a named
  precondition, matching the other root-gated in-image suites.
"""

from __future__ import annotations

import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from mergecraft.agents import codex
from tests.agents.conftest import make_agent_run_context

_AGENT_USER = "mergecraft"
_IN_IMAGE_PRECONDITION = (
    "requires euid 0, Linux, setpriv and the image's mergecraft user — runs in the action image"
)
_CODEX_AUTH_FIXTURE = json.dumps({"tokens": {"access_token": "sub-token-not-a-real-credential"}})


def _in_image_preconditions_met() -> bool:
    if sys.platform != "linux" or os.geteuid() != 0:
        return False
    if shutil.which("setpriv") is None:
        return False
    try:
        pwd.getpwnam(_AGENT_USER)
    except KeyError:
        return False
    return True


def _agent_can_read(path: str) -> bool:
    entry = pwd.getpwnam(_AGENT_USER)
    completed = subprocess.run(
        [
            "setpriv",
            "--reuid",
            str(entry.pw_uid),
            "--regid",
            str(entry.pw_gid),
            "--clear-groups",
            "test",
            "-r",
            path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def test_codex_auth_file_is_written_root_only(tmp_path: Path) -> None:
    """``_setup_codex_auth`` must not leave the credential group/world-readable."""
    ctx = make_agent_run_context(tmp_path, resolved_model=None)
    codex_home = tmp_path / "codex-home"

    codex._setup_codex_auth(
        ctx,
        codex_home=codex_home,
        credential_env={codex.CODEX_AUTH_ENV: _CODEX_AUTH_FIXTURE},
    )

    auth_path = codex_home / "auth.json"
    assert auth_path.is_file(), "the Codex CLI must still be able to read its own credential"
    assert stat.S_IMODE(auth_path.stat().st_mode) == 0o600, (
        f"the Codex auth file must be 0600; got {oct(stat.S_IMODE(auth_path.stat().st_mode))}"
    )


def _candidate_credential_paths() -> list[str]:
    """Every path HW0's static table marks as credential material to protect."""
    candidates: list[str] = []
    for root in ("/github/file_commands", "/github/home"):
        path = Path(root)
        if path.is_dir():
            candidates.extend(str(item) for item in path.rglob("*") if item.is_file())
        elif path.exists():
            candidates.append(str(path))

    proc = Path("/proc")
    if proc.is_dir():
        for entry in proc.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat().st_uid != 0:
                    continue
            except OSError:
                continue
            environ = entry / "environ"
            if environ.exists():
                candidates.append(str(environ))

    temp = os.environ.get("MERGECRAFT_TEMP_DIR")
    if temp:
        askpass = Path(temp) / "credentials" / "git-askpass.sh"
        if askpass.is_file():
            candidates.append(str(askpass))
    return candidates


class TestCredentialPathsAreUnreadableToTheAgentUser:
    """In-image proof: the agent user cannot read any credential path."""

    @pytest.mark.skipif(not _in_image_preconditions_met(), reason=_IN_IMAGE_PRECONDITION)
    def test_no_credential_path_is_readable_by_the_agent_user(self) -> None:
        candidates = _candidate_credential_paths()
        assert candidates, (
            "the image exposes no candidate credential path — re-anchor the read-scoping probe"
        )

        readable = [path for path in candidates if _agent_can_read(path)]

        assert not readable, f"the agent user can read credential material: {readable!r}"
