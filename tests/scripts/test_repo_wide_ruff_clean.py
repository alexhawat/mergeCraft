"""``ruff format --check`` and ``ruff check src`` are clean repo-wide (#1570).

CI scopes formatting to ``src tests scripts``, so Markdown code blocks went
unchecked and three of them drifted out of ``ruff format`` shape:
``docs/agents-sdk.md``, ``docs/dev/plans/audit-2026-11-05-testing.md`` and
``docs/dev/test-plans/eval-benchmark-b3-live.md``. The issue's own verification
commands are ``uv run ruff format --check .`` and ``uv run ruff check src``,
and CI's format scope is not widened to cover them, so these tests run the
same two commands for the whole repository.

``ruff check src`` also warns about a literal noqa directive inside a comment
in ``analyzers/self_silencing/markers.py``; a warning on a clean run makes
every future warning easy to miss.

Both tests spawn ``sys.executable -m ruff`` against the repository root and
assert on the exit code and the diagnostics, so they see exactly what an
operator running the issue's commands sees. Nothing is skipped: a missing ruff
fails the test with the interpreter path in the message.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT

# The Markdown files the repository-wide format check rejects today. A new one
# appearing fails the test until it is listed here.
_MARKDOWN_FILES = (
    "docs/agents-sdk.md",
    "docs/dev/plans/audit-2026-11-05-testing.md",
    "docs/dev/test-plans/eval-benchmark-b3-live.md",
)

# What ruff says about a marker directive written as ordinary prose. The message
# wraps the directive in backticks; the needle is split so this source line is
# not itself read as a directive.
_INVALID_NOQA = "Invalid `# " + "noqa`"


def _ruff(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``sys.executable -m ruff <args>`` from the repository root."""
    return subprocess.run(
        [sys.executable, "-m", "ruff", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )


def test_markdown_code_blocks_are_formatted() -> None:
    """``ruff format --check`` accepts every Markdown code block the issue lists."""
    root = Path(REPO_ROOT)
    missing = [name for name in _MARKDOWN_FILES if not (root / name).is_file()]
    assert not missing, f"the issue's Markdown files are gone: {missing}"
    result = _ruff(["format", "--check", *_MARKDOWN_FILES])
    assert result.returncode == 0, (
        f"ruff format --check rejects a Markdown code block:\n{result.stdout}{result.stderr}"
    )


def test_ruff_check_src_emits_no_warning() -> None:
    """``ruff check src`` exits 0 and prints no invalid-noqa warning."""
    # ``--no-cache``: ruff 0.17.6 caches "already parsed" state and suppresses
    # the invalid-noqa diagnostic on a warm cache, which would hide the drift.
    result = _ruff(["check", "src", "--no-cache"])
    assert result.returncode == 0, f"ruff check src failed:\n{result.stdout}{result.stderr}"
    assert _INVALID_NOQA not in result.stderr, (
        f"ruff check src warns about an invalid noqa directive:\n{result.stderr}"
    )
