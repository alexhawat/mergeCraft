"""Downloaded lint tools must be verified before extraction on every architecture."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.ci.workflow_support import REPO_ROOT


@pytest.mark.parametrize("arch", ["x86_64", "arm64"])
@pytest.mark.parametrize("tool", ["actionlint", "zizmor"])
def test_tampered_archive_is_rejected_before_extraction(
    tmp_path: Path, arch: str, tool: str
) -> None:
    binaries = tmp_path / "bin"
    binaries.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    recorded = tmp_path / "digest"
    scripts = {
        "uname": f'#!/bin/sh\nif [ "$1" = -s ]; then echo Linux; else echo {arch}; fi\n',
        "curl": '#!/bin/sh\nwhile [ "$1" != -o ]; do shift; done\nshift\nprintf tampered > "$1"\n',
        "sha256sum": f"""#!{sys.executable}
import hashlib, pathlib, sys
line = sys.stdin.read()
pathlib.Path({str(recorded)!r}).write_text(line)
expected, path = line.strip().split(None, 1)
sys.exit(0 if hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest() == expected else 1)
""",
        "tar": f'#!/bin/sh\ntouch "{tmp_path / "extracted"}"\nexit 1\n',
    }
    for name, script in scripts.items():
        path = binaries / name
        path.write_text(script)
        path.chmod(0o755)
    if tool == "zizmor":
        cached = cache / "actionlint"
        cached.write_text("#!/bin/sh\nexit 0\n")
        cached.chmod(0o755)
    run = subprocess.run(
        ["bash", "scripts/workflow_lint.sh"],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{binaries}:{os.environ['PATH']}",
            "MERGECRAFT_TOOL_CACHE": str(cache),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode != 0, run.stdout + run.stderr
    assert not (tmp_path / "extracted").exists()
    assert not (cache / tool).exists()
    # Digests from the pinned upstream release assets, independently recorded.
    digests = {
        (
            "actionlint",
            "x86_64",
        ): "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8",
        ("actionlint", "arm64"): "325e971b6ba9bfa504672e29be93c24981eeb1c07576d730e9f7c8805afff0c6",
        ("zizmor", "x86_64"): "e87b67160194884e375a46a12c57ccc904f762b53845f254fab7f17d98809c09",
        ("zizmor", "arm64"): "324e43770cfacf4216f8aefb287263b5b5c733c85b03bf7583b5cc4a0460239e",
    }
    assert recorded.read_text().split()[0] == digests[tool, arch]
