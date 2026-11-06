"""Plan consumer release-pin updates without importing project dependencies.

Release preparation advances the documented version. The post-release dev bump
retains that release, rather than advertising the next unpublished version.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

METADATA = "docs/consumer-release.json"
PIN_PATHS = (
    "README.md",
    "AGENTS-mergecraft.md",
    "docs/install.md",
    "docs/mcp.md",
    "docs/opencode.md",
    "llms-full.txt",
)
RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?")
INSTALL_PIN = re.compile(r"mergecraft-action==([0-9][A-Za-z0-9.]*)")
RELEASE_DOCS = re.compile(r"https://github\.com/alexhawat/mergeCraft/tree/v([^/\s)]+)/docs")


def documented_release(root: Path) -> str:
    """Read the release metadata shared by consumer surfaces and release gates."""
    version = json.loads((root / METADATA).read_text(encoding="utf-8"))["version"]
    if not isinstance(version, str) or RELEASE_VERSION.fullmatch(version) is None:
        raise ValueError(f"{METADATA}: expected a canonical release version")
    return version


def pin_paths(root: Path) -> tuple[Path, ...]:
    """Include every generated skill as well as the primary consumer pages."""
    skills = tuple(sorted((root / "skills").rglob("SKILL.md")))
    if not skills or root / "skills/mergecraft/SKILL.md" not in skills:
        raise ValueError("consumer skill sources are missing")
    return (*(root / name for name in PIN_PATHS), *skills)


def plan_pin_updates(root: Path, new_version: str) -> dict[Path, str]:
    """Validate every input, then return all updates for the release transaction."""
    if re.fullmatch(RELEASE_VERSION.pattern + r"(?:\.dev\d+)?", new_version) is None:
        raise ValueError(f"not a canonical release/development version: {new_version!r}")
    old_version = documented_release(root)
    release = old_version if ".dev" in new_version else new_version
    updates: dict[Path, str] = {}
    for path in pin_paths(root):
        text = path.read_text(encoding="utf-8")
        pins = INSTALL_PIN.findall(text)
        links = RELEASE_DOCS.findall(text)
        if not pins or set(pins) != {old_version} or not links or set(links) != {old_version}:
            raise ValueError(f"{path}: install pins and release-doc links must match {old_version}")
        updated = INSTALL_PIN.sub(f"mergecraft-action=={release}", text)
        updates[path] = RELEASE_DOCS.sub(
            f"https://github.com/alexhawat/mergeCraft/tree/v{release}/docs", updated
        )
    lock_path = root / "skills-lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    for path, text in updates.items():
        if path.name != "SKILL.md":
            continue
        relative = path.relative_to(root).as_posix()
        matches = [entry for entry in lock["skills"].values() if entry.get("skillPath") == relative]
        if len(matches) != 1:
            raise ValueError(f"skills-lock.json: expected one entry for {relative}")
        matches[0]["computedHash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    updates[lock_path] = json.dumps(lock, indent=2, ensure_ascii=False) + "\n"
    updates[root / METADATA] = json.dumps({"version": release}, indent=2) + "\n"
    return {
        path: text for path, text in updates.items() if path.read_text(encoding="utf-8") != text
    }
