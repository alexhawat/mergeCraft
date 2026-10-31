"""Concurrency contract for the shared pip cache used by managed analyzers.

``provision_pip_script`` installs into a cache root every process on the machine
shares. Two workers provisioning the same package at once used to interleave —
one walked ``bin/`` with ``rmtree`` while the other was still writing into it —
which surfaced as ``[Errno 39] Directory not empty: 'bin'`` and a silently
``skipped`` analyzer. These tests pin the locking and the atomic publish.

Module: tests.analyzers.test_pip_provision_lock
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers import pattern


class _FakeSubprocess:
    """Stand-in for the ``subprocess`` module that fabricates a valid install."""

    def __init__(self) -> None:
        self.targets: list[Path] = []
        self._lock = threading.Lock()

    def run(self, cmd: list[str], **kwargs: Any) -> Any:
        target = Path(cmd[cmd.index("--target") + 1])
        with self._lock:
            self.targets.append(target)
        # A real install takes seconds; the delay is what exposes the race.
        time.sleep(0.05)
        (target / "bin").mkdir(parents=True, exist_ok=True)
        script = target / "bin" / "semgrep"
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)
        (target / "semgrep").mkdir(exist_ok=True)
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()


@pytest.fixture
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> _FakeSubprocess:
    fake = _FakeSubprocess()
    monkeypatch.setattr(pattern, "subprocess", fake)
    monkeypatch.setattr(pattern, "_resolve_pip_python", lambda *, package: "python3")
    return fake


def test_concurrent_provisioning_installs_once_and_returns_one_path(
    tmp_path: Path, fake_subprocess: _FakeSubprocess
) -> None:
    cache_dir = tmp_path / "analyzer-cache"
    results: list[Path] = []
    errors: list[BaseException] = []
    start = threading.Barrier(4)

    def _worker() -> None:
        try:
            start.wait(timeout=5)
            results.append(
                pattern.provision_pip_script(
                    package="semgrep",
                    version="9.9.9",
                    script="semgrep",
                    cache_dir=cache_dir,
                )
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors, f"concurrent provisioning raised: {errors!r}"
    assert len(results) == 4
    assert len(set(results)) == 1, "every worker must return the same installed script"
    assert results[0].is_file()
    assert len(fake_subprocess.targets) == 1, (
        "the lock must collapse concurrent installs into one; "
        f"installs attempted: {[str(t) for t in fake_subprocess.targets]}"
    )


def test_a_stale_entry_is_replaced_without_deleting_it_in_place(
    tmp_path: Path, fake_subprocess: _FakeSubprocess
) -> None:
    cache_dir = tmp_path / "analyzer-cache"
    install_root = cache_dir / "pip" / "semgrep" / "9.9.9"
    (install_root / "bin").mkdir(parents=True)
    # A half-written entry: a script with no package beside it.
    (install_root / "bin" / "semgrep").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")

    script = pattern.provision_pip_script(
        package="semgrep",
        version="9.9.9",
        script="semgrep",
        cache_dir=cache_dir,
    )

    assert script == install_root / "bin" / "semgrep"
    assert script.read_text(encoding="utf-8").startswith("#!/bin/sh\nexit 0")
    assert (install_root / "semgrep").is_dir(), "the published tree is the new, complete one"
    leftovers = [
        child.name for child in install_root.parent.iterdir() if child.name.startswith(".")
    ]
    assert leftovers == [], f"staging and stale trees must not survive: {leftovers}"


def test_a_failed_install_leaves_the_existing_entry_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "analyzer-cache"
    install_root = cache_dir / "pip" / "semgrep" / "9.9.9"

    class _Failing:
        def run(self, cmd: list[str], **kwargs: Any) -> Any:
            return type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()

    monkeypatch.setattr(pattern, "subprocess", _Failing())
    monkeypatch.setattr(pattern, "_resolve_pip_python", lambda *, package: "python3")

    with pytest.raises(OSError, match=r"pip install failed for semgrep==9\.9\.9"):
        pattern.provision_pip_script(
            package="semgrep", version="9.9.9", script="semgrep", cache_dir=cache_dir
        )

    assert not install_root.exists(), "a failed first install must not publish a partial tree"
    staging = [c for c in install_root.parent.iterdir() if c.name.startswith(".")]
    assert staging == [], f"failed staging trees must be cleaned up: {staging}"
