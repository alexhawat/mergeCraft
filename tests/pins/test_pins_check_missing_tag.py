"""`make pins-check` must fail when the release tag does not exist (SW-D7).

``scripts/check_example_defaults_sync.py`` resolves ``action_pin_minimal`` with
``git ls-remote --tags <remote> refs/tags/<tag> refs/tags/<tag>^{}``. A tag that
was deleted, mistyped or never pushed makes that command print nothing and
**exit 0** — indistinguishable from a reachable remote, so the guard used to
take its unreachable-remote skip path and exit 0 too. A release tag with no
commit therefore passed ``make pins-check`` silently.

These tests drive the CLI itself, with a ``git`` shim on ``PATH`` that answers
``ls-remote`` per case, so they pin exactly what ``make pins-check`` does. The
offline recorded-capture gate lives in ``test_action_sha_matches_tag.py`` and is
deliberately left untouched.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.pins import action_pin_minimal, load_example_defaults

if TYPE_CHECKING:
    import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_example_defaults_sync.py"
# A valid 40-hex commit that is not the shipped ``action_sha_minimal``.
_OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"


def _git_shim(stdout: str, returncode: int) -> str:
    """Return a POSIX ``git`` shim that emits *stdout* then exits *returncode*.

    Arguments are ignored: the shim answers whatever ``ls-remote`` form the
    guard uses, so the test does not over-couple to its exact query.
    """
    lines = ["#!/bin/sh"]
    if stdout:
        lines += ["cat <<'__PINS_SHIM_OUT__'", stdout.rstrip("\n"), "__PINS_SHIM_OUT__"]
    lines.append(f"exit {returncode}")
    return "\n".join(lines) + "\n"


def _run_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: str = "",
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    """Run the pins-check CLI with a stubbed ``git`` first on ``PATH``."""
    shim_dir = tmp_path / "shim-bin"
    shim_dir.mkdir(exist_ok=True)
    shim = shim_dir / "git"
    shim.write_text(_git_shim(stdout, returncode), encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=str(_SCRIPT.parents[1]),
        capture_output=True,
        text=True,
        check=False,
    )


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"


def test_an_absent_tag_fails_instead_of_skipping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tag the remote never heard of must fail, not skip (SW-D7).

    ``git ls-remote --tags`` exits 0 with empty output when the ref is absent.
    Treating that as "remote unreachable" let a deleted, mistyped or never-pushed
    release tag pass ``make pins-check`` with a notice and exit 0.
    """
    tag = action_pin_minimal()
    result = _run_guard(tmp_path, monkeypatch, stdout="", returncode=0)
    output = _output(result)

    assert result.returncode == 1, (
        f"an absent tag must fail pins-check, got exit {result.returncode}:\n{output}"
    )
    assert tag in output, f"the failure must name the missing tag {tag!r}:\n{output}"
    assert "drift" in output.lower(), f"expected a drift failure naming the gap:\n{output}"
    assert "skipping" not in output.lower(), (
        f"an absent tag must not take the unreachable-remote skip path:\n{output}"
    )


def test_an_unreachable_remote_still_skips_the_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An offline checkout must keep its grace: no network must not fail."""
    result = _run_guard(tmp_path, monkeypatch, stdout="", returncode=128)
    output = _output(result)

    assert result.returncode == 0, f"an unreachable remote must not fail the gate:\n{output}"
    assert "notice" in output.lower(), f"expected a skip notice:\n{output}"
    assert "skipping" in output.lower(), f"expected the comparison to be skipped:\n{output}"
    assert "drift" not in output.lower(), f"no drift may be reported when skipping:\n{output}"


def test_a_tag_resolving_to_a_different_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for the existing mismatch rule."""
    tag = action_pin_minimal()
    result = _run_guard(
        tmp_path,
        monkeypatch,
        stdout=f"{_OTHER_SHA}\trefs/tags/{tag}",
        returncode=0,
    )
    output = _output(result)

    assert result.returncode == 1, (
        f"a tag pointing at another commit must fail, got exit {result.returncode}:\n{output}"
    )
    assert tag in output, f"the failure must name the tag {tag!r}:\n{output}"
    assert _OTHER_SHA in output, f"the failure must name the resolved commit:\n{output}"


def test_a_tag_resolving_to_the_pinned_commit_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path: tag and pinned commit agree, so the gate is green."""
    tag = action_pin_minimal()
    pinned = load_example_defaults()["action_sha_minimal"]
    result = _run_guard(
        tmp_path,
        monkeypatch,
        stdout=f"{pinned}\trefs/tags/{tag}",
        returncode=0,
    )
    output = _output(result)

    assert result.returncode == 0, (
        f"a matching tag and commit must pass, got exit {result.returncode}:\n{output}"
    )
    assert "skipping" not in output.lower(), f"the comparison must actually run:\n{output}"
    assert "OK" in output, f"expected the success line:\n{output}"
