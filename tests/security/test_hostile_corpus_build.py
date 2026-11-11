"""The shared adversarial corpus is published only after a successful build."""

from __future__ import annotations

import os
import selectors
import subprocess
import sys
from pathlib import Path

import pytest

from tests.security import hostile_corpus


def _read_line(process: subprocess.Popen[str]) -> str:
    assert process.stdout is not None
    line = bytearray()
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while True:
            assert selector.select(timeout=10), "corpus worker did not report progress"
            char = os.read(process.stdout.fileno(), 1)
            assert char, "corpus worker exited before reporting progress"
            if char == b"\n":
                return line.decode()
            line.extend(char)


def test_concurrent_workers_wait_for_the_complete_corpus(tmp_path: Path) -> None:
    """A second process must wait even after the builder creates .git."""
    script = tmp_path / "build.sh"
    script.touch()
    worker = """
import sys
from pathlib import Path
from tests.security import hostile_corpus as corpus

root = Path(sys.argv[1])
corpus.HOSTILE_REPO = root / "hostile-repo"
corpus.BUILD_SCRIPT = root / "build.sh"

def build(*args, **kwargs):
    with (root / "build-count").open("a") as count:
        count.write("build\\n")
    (corpus.HOSTILE_REPO / ".git").mkdir(parents=True, exist_ok=True)
    print("building", flush=True)
    assert sys.stdin.readline().strip() == "finish"
    (corpus.HOSTILE_REPO / "complete").touch()

corpus.subprocess.run = build
print("calling", flush=True)
repo = corpus.require_hostile_repo()
assert (repo / "complete").is_file()
print("ready", flush=True)
"""
    processes: list[subprocess.Popen[str]] = []
    try:
        for _ in range(2):
            process = subprocess.Popen(
                [sys.executable, "-c", worker, str(tmp_path)],
                cwd=Path(__file__).resolve().parents[2],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            processes.append(process)
            assert _read_line(process) == "calling"
            if len(processes) == 1:
                assert _read_line(process) == "building"

        first, second = processes
        with pytest.raises(subprocess.TimeoutExpired):
            second.communicate(timeout=0.2)

        stdout, stderr = first.communicate(input="finish\n", timeout=10)
        assert first.returncode == 0, stderr
        assert stdout.strip() == "ready"
        stdout, stderr = second.communicate(timeout=10)
        assert second.returncode == 0, stderr
        assert stdout.strip() == "ready"
        assert (tmp_path / "build-count").read_text() == "build\n"
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)


def test_failed_build_is_retried_and_success_is_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "hostile-repo"
    script = tmp_path / "build.sh"
    script.touch()
    monkeypatch.setattr(hostile_corpus, "HOSTILE_REPO", repo)
    monkeypatch.setattr(hostile_corpus, "BUILD_SCRIPT", script)
    attempts = 0

    def build(*args: object, **kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        if attempts == 1:
            raise subprocess.CalledProcessError(128, [str(script)])
        (repo / "complete").touch()

    monkeypatch.setattr(hostile_corpus.subprocess, "run", build)
    with pytest.raises(subprocess.CalledProcessError):
        hostile_corpus.require_hostile_repo()
    assert hostile_corpus.require_hostile_repo() == repo
    assert (repo / "complete").is_file()
    assert hostile_corpus.require_hostile_repo() == repo
    assert attempts == 2
