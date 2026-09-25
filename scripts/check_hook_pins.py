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
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_LOCAL_REPO = "local"
# A frozen hook rev carries its human version in a trailing comment, because the
# SHA alone does not tell a reader which release it is.
_REV_LINE_RE = re.compile(r"^\s*rev:\s*(\S+)(?:\s+#\s*(v[0-9][^\s]*))?\s*$")
_REPO_LINE_RE = re.compile(r"^\s*-\s*repo:\s*(\S+)\s*$")


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
    """Return {repo_url: rev} for every hook repo in `.pre-commit-config.yaml`.

    YAML strips the trailing ``# v<version>`` comment, so a frozen rev is the
    bare 40-character SHA — never the moving tag it replaced.
    """
    data = yaml.safe_load(pre_commit_text)
    if not isinstance(data, dict):
        return {}
    revs: dict[str, str] = {}
    for repo in data.get("repos") or []:
        if not isinstance(repo, dict):
            continue
        url = repo.get("repo")
        rev = repo.get("rev")
        if url and rev:
            revs[str(url)] = str(rev)
    return revs


def _hook_versions(pre_commit_text: str) -> dict[str, str]:
    """Return {repo_url: "v<version>"} from each frozen rev's trailing comment.

    The comment carries the release a SHA corresponds to; the generic rule in
    :func:`main` requires it on every non-local repo, and the ruff pairing reads
    the version from here rather than from the YAML scalar.
    """
    versions: dict[str, str] = {}
    current_repo: str | None = None
    for line in pre_commit_text.splitlines():
        repo_match = _REPO_LINE_RE.match(line)
        if repo_match:
            current_repo = repo_match.group(1)
            continue
        rev_match = _REV_LINE_RE.match(line)
        if rev_match and current_repo and rev_match.group(2):
            versions[current_repo] = rev_match.group(2)
    return versions


def main() -> int:
    """Assert every hook rev is a frozen SHA and every tracked pin matches."""
    if not PRE_COMMIT_CONFIG.is_file():
        print(f"missing {PRE_COMMIT_CONFIG}", file=sys.stderr)
        return 1
    if not PYPROJECT.is_file():
        print(f"missing {PYPROJECT}", file=sys.stderr)
        return 1

    pins = _dev_dependency_pins(PYPROJECT.read_text(encoding="utf-8"))
    config_text = PRE_COMMIT_CONFIG.read_text(encoding="utf-8")
    revs = _hook_revs(config_text)
    versions = _hook_versions(config_text)

    mismatches: list[str] = []
    # Generic rule: no moving tag may reach CI. Every non-local hook repository
    # must pin a 40-character SHA and name its release in a trailing comment.
    for url, rev in revs.items():
        if url == _LOCAL_REPO:
            continue
        if not _SHA_RE.fullmatch(rev):
            mismatches.append(
                f"{url}: rev={rev!r} is not a 40-character SHA; freeze the hook to an "
                "immutable commit with a trailing `# v<version>` comment"
            )
            continue
        if url not in versions:
            mismatches.append(f"{url}: frozen SHA {rev} has no trailing `# v<version>` comment")
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
        rev_version = versions.get(hook.repo_url, rev).lstrip("v")
        if rev_version != pinned_version:
            mismatches.append(
                f"{hook.dep_name}: .pre-commit-config.yaml pins rev={rev!r} "
                f"(v{rev_version}) but pyproject.toml pins {hook.dep_name}=={pinned_version}"
            )

    if mismatches:
        print("hook pin drift between .pre-commit-config.yaml and pyproject.toml:", file=sys.stderr)
        for mismatch in mismatches:
            print(f"  {mismatch}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
