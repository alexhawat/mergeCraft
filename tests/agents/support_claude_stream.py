"""A real streaming Claude stand-in for driver diagnostics contracts."""

from __future__ import annotations

import sys
from pathlib import Path


def write_claude_cli(root: Path, *, stdout: str = "", stderr: str = "", returncode: int = 0) -> str:
    path = root / "fake-claude"
    path.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdout.write({stdout!r})\nsys.stderr.write({stderr!r})\nsys.exit({returncode})\n"
    )
    path.chmod(0o700)
    return str(path)
