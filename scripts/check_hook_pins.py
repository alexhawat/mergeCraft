#!/usr/bin/env python3
"""Guard: pre-commit hook revisions must match their `pyproject.toml` pins.

``.pre-commit-config.yaml``'s header says "Sync hook revisions with dev
tooling" but nothing enforced it — G-F11 found ``ruff-pre-commit`` drifted
three minor versions behind ``pyproject.toml``'s ``ruff==`` pin. This script
parses both files and fails when a tracked hook's ``rev`` disagrees with its
dev-dependency pin.

Module: scripts.check_hook_pins
Depends: pathlib, re, sys, tomllib, yaml

Exports:
    main — CLI entry; compares pre-commit hook revs against pyproject pins.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import NamedTuple

import yaml

REPO = Path(__file__).resolve().parents[1]
PRE_COMMIT_CONFIG = REPO / ".pre-commit-config.yaml"
PYPROJECT = REPO / "pyproject.toml"

_PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([A-Za-z0-9_.\-+]+)$")


class HookPin(NamedTuple):
    """One pre-commit hook whose `rev` must track a `pyproject.toml` pin."""

    repo_url: str
    dep_name: str


# Map a pre-commit `repo:` URL to the dev-dependency name it must match.
# The pre-commit `rev` for these mirrors is conventionally `v<version>` while
# the pyproject pin is bare `<version>` — extend this table when another
# hook's mirror should track a pyproject pin.
TRACKED_HOOKS: tuple[HookPin, ...] = (
    HookPin(repo_url="https://github.com/astral-sh/ruff-pre-commit", dep_name="ruff"),
)


def _dev_dependency_pins(pyproject_text: str) -> dict[str, str]:
    """Return {package: version} for exact `==` pins in `[dependency-groups].dev`."""
    data = tomllib.loads(pyproject_text)
    dev_deps = data.get("dependency-groups", {}).get("dev")
    if dev_deps is None:
        dev_deps = data.get("project", {}).get("optional-dependencies", {}).get("dev", [])
    pins: dict[str, str] = {}
    for entry in dev_deps:
        match = _PIN_RE.match(entry.strip())
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def _hook_revs(pre_commit_text: str) -> dict[str, str]:
    """Return {repo_url: rev} for every hook repo in `.pre-commit-config.yaml`."""
    data = yaml.safe_load(pre_commit_text)
    revs: dict[str, str] = {}
    for repo in data.get("repos", []):
        url = repo.get("repo")
        rev = repo.get("rev")
        if url and rev:
            revs[url] = rev
    return revs


def main() -> int:
    """Assert every tracked pre-commit hook `rev` matches its pyproject pin."""
    if not PRE_COMMIT_CONFIG.is_file():
        print(f"missing {PRE_COMMIT_CONFIG}", file=sys.stderr)
        return 1
    if not PYPROJECT.is_file():
        print(f"missing {PYPROJECT}", file=sys.stderr)
        return 1

    pins = _dev_dependency_pins(PYPROJECT.read_text(encoding="utf-8"))
    revs = _hook_revs(PRE_COMMIT_CONFIG.read_text(encoding="utf-8"))

    mismatches: list[str] = []
    for hook in TRACKED_HOOKS:
        pinned_version = pins.get(hook.dep_name)
        if pinned_version is None:
            mismatches.append(
                f"{hook.dep_name}: no pyproject.toml dev pin found (expected `{hook.dep_name}==...`)"
            )
            continue
        rev = revs.get(hook.repo_url)
        if rev is None:
            mismatches.append(
                f"{hook.dep_name}: no `.pre-commit-config.yaml` entry for {hook.repo_url}"
            )
            continue
        rev_version = rev.lstrip("v")
        if rev_version != pinned_version:
            mismatches.append(
                f"{hook.dep_name}: .pre-commit-config.yaml pins rev={rev!r} "
                f"but pyproject.toml pins {hook.dep_name}=={pinned_version}"
            )

    if mismatches:
        print("hook pin drift between .pre-commit-config.yaml and pyproject.toml:", file=sys.stderr)
        for mismatch in mismatches:
            print(f"  {mismatch}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
