"""Complete, local-only consumer inputs for release-hook integration fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

from scripts.consumer_install_pins import METADATA, pin_paths
from scripts.gen_llms_full import LLMS_FULL_PATHS

from tests.ci.workflow_support import REPO_ROOT


def copy_consumer_pin_inputs(root: Path) -> None:
    paths = {
        METADATA,
        "scripts/consumer_install_pins.py",
        "skills-lock.json",
        "skills/harnesses.yaml",
        *LLMS_FULL_PATHS,
        *(path.relative_to(REPO_ROOT).as_posix() for path in pin_paths(REPO_ROOT)),
    }
    for relative in paths:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
