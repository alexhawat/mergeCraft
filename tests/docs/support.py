"""Shared helpers for the ``tests/docs`` contract suite (#405)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from mergecraft.utils.git_ref import git_ref_exists
from tests.ci.workflow_support import REPO_ROOT

__all__ = [
    "action_uses_pattern",
    "ci_steps",
    "git_ref_exists",
    "load_harness_manifest",
    "load_script_module",
    "makefile_prerequisite_tokens",
]

action_uses_pattern = re.compile(
    r"uses:\s*alexhawat/mergeCraft@(\S+)",
    re.IGNORECASE,
)

HARNESS_MANIFEST = REPO_ROOT / "skills" / "harnesses.yaml"


def load_harness_manifest() -> dict[str, Any]:
    """Parse ``skills/harnesses.yaml`` as a mapping."""
    assert HARNESS_MANIFEST.is_file(), f"missing {HARNESS_MANIFEST.relative_to(REPO_ROOT)}"
    data = yaml.safe_load(HARNESS_MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "skills/harnesses.yaml must parse as a mapping"
    return data


def makefile_prerequisite_tokens(makefile: str, target: str) -> set[str]:
    """Return Makefile prerequisite tokens for *target*."""
    match = re.search(rf"^{re.escape(target)}:(.*)$", makefile, re.MULTILINE)
    assert match, f"Makefile missing {target}: recipe"
    return set(match.group(1).split())


def ci_steps() -> list[str]:
    """Return Makefile ``CI_STEPS`` tokens."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^CI_STEPS\s*:?=\s*(.+)$", makefile, re.MULTILINE)
    assert match, "Makefile missing CI_STEPS"
    return match.group(1).split()


def load_script_module(path: str | Path) -> ModuleType:
    """Load a repo script by absolute or repo-relative path."""
    script = Path(path)
    if not script.is_absolute():
        script = REPO_ROOT / script
    assert script.is_file(), f"missing {script.relative_to(REPO_ROOT)}"
    module_name = f"mergecraft_docs_support_{script.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        msg = f"could not load {script}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
