"""Build targets and tooling claims must be true on the host that runs them.

Two Make/tooling claims are false today: ``docker-build`` tags the image
``mergeCraft:local``, which is not a valid Docker reference, and the sharding
selector advertises least-duration balancing with no durations file to balance
by. ``scripts/workflow_lint.sh`` also reports success when it never linted.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Final

from tests.ci.workflow_support import REPO_ROOT, makefile_target_body, read_text

# Docker repository components are lowercase; a tag after ``:`` may be mixed case.
_DOCKER_REPOSITORY: Final = re.compile(
    r"^[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*)*$"
)
_DURATIONS_FILE: Final = REPO_ROOT / ".test_durations"


def test_docker_build_tag_is_a_valid_docker_reference() -> None:
    body = makefile_target_body("docker-build")
    tags = re.findall(r"(?:^|\s)-t\s+(\S+)", body)
    assert tags, f"docker-build passes no -t tag:\n{body}"
    for tag in tags:
        repository = tag.partition(":")[0]
        assert repository == repository.lower(), (
            f"docker-build tag {tag!r} has an uppercase repository; Docker rejects it"
        )
        assert _DOCKER_REPOSITORY.fullmatch(repository), (
            f"docker-build tag {tag!r} is not a valid Docker reference"
        )


def test_sharding_claims_durations_it_has() -> None:
    """Either the durations file exists and parses, or the claim is dropped."""
    makefile = read_text("Makefile")
    if "least_duration" not in makefile:
        return
    assert _DURATIONS_FILE.is_file(), (
        "the Makefile selects --splitting-algorithm least_duration but no "
        ".test_durations file is tracked; commit one or drop the algorithm"
    )
    payload = json.loads(_DURATIONS_FILE.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), ".test_durations must parse as a mapping"
    assert payload, ".test_durations must not be empty"
    assert all(isinstance(value, (int, float)) for value in payload.values()), (
        ".test_durations values must be seconds as numbers"
    )

    refresh = makefile_target_body("test-durations", makefile)
    assert "durations" in refresh, (
        "the test-durations target must regenerate the durations file it advertises"
    )


def test_workflow_lint_fails_when_it_cannot_lint(tmp_path: Path) -> None:
    """Off Linux with no cached binaries the script must not report success."""
    shim = tmp_path / "bin"
    shim.mkdir()
    uname = shim / "uname"
    uname.write_text(
        '#!/bin/sh\nif [ "$1" = "-m" ]; then echo arm64; else echo Darwin; fi\n',
        encoding="utf-8",
    )
    uname.chmod(0o700)

    cache = tmp_path / "cache"
    cache.mkdir()
    environment = {
        **os.environ,
        "PATH": f"{shim}:{os.environ['PATH']}",
        "MERGECRAFT_TOOL_CACHE": str(cache),
    }
    completed = subprocess.run(
        ["bash", "scripts/workflow_lint.sh"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    output = f"{completed.stdout}\n{completed.stderr}"
    assert completed.returncode != 0, (
        f"workflow_lint.sh exited 0 on a host where it could not lint:\n{output}"
    )
    assert "unavailable" in output.lower(), (
        f"the failure must say lint is unavailable, got:\n{output}"
    )
