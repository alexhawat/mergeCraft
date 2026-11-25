"""``scripts/check_new_test_types.py`` — the type gate on newly added test modules.

``make ci`` runs it without ``MERGECRAFT_TEST_TYPE_BASE``, so an unset base must
mean ``origin/main`` and a base that cannot be found must fail, never pass.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from tests.docs.support import ci_steps, load_script_module, makefile_prerequisite_tokens

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

_ROOT = Path(__file__).resolve().parents[2]
main = load_script_module("scripts/check_new_test_types.py").main

_BASE_ENV = "MERGECRAFT_TEST_TYPE_BASE"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def _commit_file(repo: Path, name: str, text: str) -> str:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "--no-verify", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """A repository on a branch, with ``origin/main`` at its first commit."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "user.email", "test@example.com")
    first = _commit_file(path, "tests/test_existing.py", "X = 1\n")
    _git(path, "update-ref", "refs/remotes/origin/main", first)
    monkeypatch.chdir(path)
    monkeypatch.delenv(_BASE_ENV, raising=False)
    return path


@pytest.fixture
def checked(tmp_path: Path, monkeypatch: MonkeyPatch) -> Path:
    """Put a recording ``pyright`` first on ``PATH``; return the file it writes."""
    log = tmp_path / "pyright-args"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "pyright"
    stub.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" > "$STUB_PYRIGHT_LOG"\nexit "$STUB_PYRIGHT_RC"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("STUB_PYRIGHT_LOG", str(log))
    monkeypatch.setenv("STUB_PYRIGHT_RC", "0")
    return log


def test_unset_base_checks_what_the_branch_adds_to_main(repo: Path, checked: Path) -> None:
    """Bug: an unset base was a ``KeyError``, so ``make ci`` could not run the gate."""
    _commit_file(repo, "tests/unit/test_added.py", "Y = 1\n")
    _commit_file(repo, "tests/test_existing.py", "X = 2\n")
    _commit_file(repo, "src/added.py", "Z = 1\n")

    assert main() == 0
    assert checked.read_text(encoding="utf-8").split() == ["tests/unit/test_added.py"]


def test_empty_base_means_the_default(repo: Path, checked: Path, monkeypatch: MonkeyPatch) -> None:
    """An empty value (an unset workflow expression) must not select nothing."""
    _commit_file(repo, "tests/test_added.py", "Y = 1\n")
    monkeypatch.setenv(_BASE_ENV, "")

    assert main() == 0
    assert checked.read_text(encoding="utf-8").split() == ["tests/test_added.py"]


def test_explicit_base_wins_over_main(repo: Path, checked: Path, monkeypatch: MonkeyPatch) -> None:
    """Pull-request CI passes its base commit and only later modules are checked."""
    base = _commit_file(repo, "tests/test_before.py", "Y = 1\n")
    _commit_file(repo, "tests/test_after.py", "Y = 1\n")
    monkeypatch.setenv(_BASE_ENV, base)

    assert main() == 0
    assert checked.read_text(encoding="utf-8").split() == ["tests/test_after.py"]


def test_modules_main_added_after_the_fork_are_not_checked(repo: Path, checked: Path) -> None:
    """The comparison starts at the fork point, not at the tip of ``main``."""
    _git(repo, "switch", "-q", "-c", "work")
    _commit_file(repo, "tests/test_mine.py", "Y = 1\n")
    _git(repo, "switch", "-q", "main")
    theirs = _commit_file(repo, "tests/test_theirs.py", "Y = 1\n")
    _git(repo, "update-ref", "refs/remotes/origin/main", theirs)
    _git(repo, "switch", "-q", "work")

    assert main() == 0
    assert checked.read_text(encoding="utf-8").split() == ["tests/test_mine.py"]


def test_uncommitted_modules_are_checked(repo: Path, checked: Path) -> None:
    """A local run covers staged and untracked modules, but not ignored ones."""
    (repo / ".gitignore").write_text("tests/ignored/\n", encoding="utf-8")
    for name in ("tests/test_staged.py", "tests/test_untracked.py", "tests/ignored/test_x.py"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Y = 1\n", encoding="utf-8")
    _git(repo, "add", "tests/test_staged.py")

    assert main() == 0
    assert checked.read_text(encoding="utf-8").split() == [
        "tests/test_staged.py",
        "tests/test_untracked.py",
    ]


def test_no_new_modules_passes_without_running_pyright(
    repo: Path, checked: Path, capsys: CaptureFixture[str]
) -> None:
    """The post-merge run on ``main`` has nothing to check."""
    assert main() == 0
    assert not checked.exists()
    assert "No new Python test modules." in capsys.readouterr().out


def test_pyright_failure_fails_the_gate(
    repo: Path, checked: Path, monkeypatch: MonkeyPatch
) -> None:
    """A type error in a new module is the gate's exit status."""
    _commit_file(repo, "tests/test_added.py", "Y = 1\n")
    monkeypatch.setenv("STUB_PYRIGHT_RC", "1")

    assert main() == 1
    assert checked.exists()


def test_unresolvable_base_fails_and_names_the_variable(
    repo: Path, checked: Path, capsys: CaptureFixture[str]
) -> None:
    """Without a base the gate cannot know what is new, so it must not pass."""
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    _commit_file(repo, "tests/test_added.py", "Y = 1\n")

    assert main() == 2
    assert not checked.exists()
    message = capsys.readouterr().err
    assert "origin/main" in message
    assert _BASE_ENV in message


def test_make_ci_runs_the_gate() -> None:
    """Both the full gate and its resumable form include the new-test type check."""
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "pyright-new-tests" in makefile_prerequisite_tokens(makefile, "ci")
    assert "pyright-new-tests" in ci_steps()
