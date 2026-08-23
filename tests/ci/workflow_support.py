"""Shared YAML helpers for release-gating workflow contract tests.

Permission-scope helpers live in ``scripts/workflow_yaml.py`` (shared with
``scripts/check_called_workflow_permissions.py``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

_SHA_PIN = re.compile(r"^[0-9a-f]{40}$")
_THIRD_PARTY_USES = re.compile(r"^\s+uses:\s+(\S+)\s*$", re.MULTILINE)


def read_text(relative: str) -> str:
    path = REPO_ROOT / relative
    return path.read_text(encoding="utf-8")


def load_workflow(name: str) -> dict[str, Any]:
    path = WORKFLOWS / name
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{name} did not parse as a mapping"
    return loaded


def workflow_on(doc: dict[str, Any]) -> Any:
    """Return the ``on:`` block. PyYAML may parse the key ``on`` as ``True``."""
    if "on" in doc:
        return doc["on"]
    return doc.get(True)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def job(doc: dict[str, Any], name: str) -> dict[str, Any]:
    jobs = doc.get("jobs") or {}
    found = jobs.get(name)
    assert isinstance(found, dict), f"job {name!r} missing: {list(jobs)}"
    return found


def third_party_uses(workflow_name: str) -> list[str]:
    """Return ``owner/repo@ref`` uses lines, excluding local ``./`` actions."""
    text = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
    found: list[str] = []
    for match in _THIRD_PARTY_USES.finditer(text):
        spec = match.group(1)
        if spec.startswith(("./", ".github/")):
            continue
        found.append(spec)
    return found


def assert_third_party_uses_sha_pinned(workflow_name: str) -> None:
    unpinned: list[str] = []
    for spec in third_party_uses(workflow_name):
        if "@" not in spec:
            unpinned.append(spec)
            continue
        _name, ref = spec.rsplit("@", 1)
        if not _SHA_PIN.fullmatch(ref):
            unpinned.append(spec)
    assert not unpinned, f"{workflow_name}: unpinned third-party uses: {unpinned}"
