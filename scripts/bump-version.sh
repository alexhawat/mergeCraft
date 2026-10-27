#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Set the version Craft is preparing in pyproject.toml, server.json and uv.lock.
#
# Craft invokes this as `bash scripts/bump-version.sh <oldVersion> <newVersion>`,
# positionally, with CRAFT_OLD_VERSION / CRAFT_NEW_VERSION also exported. The
# new version is the second argument. Rewriting server.json here is what keeps
# a prepared release branch from failing its own mcp-server-json-check drift
# gate: Craft's own auto-bump would edit pyproject.toml alone. Rewriting the
# lockfile's root package version is what keeps `make lockcheck` (a required
# context) green: `uv lock --check` fails when pyproject.toml and uv.lock
# disagree.
#
# Every input is validated before anything is written, so a malformed tree
# stops the run without a half-bumped branch. No project import and no uv: the
# Release workflow's prepare job installs nothing and has no virtualenv.
# stdlib python3 only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

new_version="${2:-}"
if [[ -z "${new_version}" ]]; then
  echo "usage: bump-version.sh <old-version> <new-version> (new version is required)" >&2
  exit 1
fi

python3 - "$new_version" <<'PY'
import json
import re
import sys
from pathlib import Path

new_version = sys.argv[1]

# --- validate every input before writing anything -------------------------
pyproject_path = Path("pyproject.toml")
pyproject_text = pyproject_path.read_text(encoding="utf-8")
pyproject_pattern = re.compile(r'(?m)^version = "[^"]*"$')
if len(pyproject_pattern.findall(pyproject_text)) != 1:
    raise SystemExit("pyproject.toml must carry exactly one top-level version line")

server_path = Path("server.json")
server = json.loads(server_path.read_text(encoding="utf-8"))
# Fail loudly on a manifest that lost a field: overwriting a broken server.json
# would hide the defect, and the committed file must keep both fields.
if not isinstance(server.get("version"), str):
    raise SystemExit("server.json is missing its top-level version field")
packages = server.get("packages")
if (
    not isinstance(packages, list)
    or not packages
    or not isinstance(packages[0], dict)
    or not isinstance(packages[0].get("version"), str)
):
    raise SystemExit("server.json is missing packages[0].version")

lock_path = Path("uv.lock")
lock_text = lock_path.read_text(encoding="utf-8")
lock_pattern = re.compile(r'(\[\[package\]\]\nname = "mergecraft-action"\nversion = )"([^"]*)"')
if len(lock_pattern.findall(lock_text)) != 1:
    raise SystemExit("uv.lock must carry exactly one mergecraft-action package block")

# --- write, with the manifest's own serialization --------------------------
pyproject_path.write_text(
    pyproject_pattern.sub(f'version = "{new_version}"', pyproject_text),
    encoding="utf-8",
)

server["version"] = new_version
packages[0]["version"] = new_version
server_path.write_text(
    json.dumps(server, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

lock_path.write_text(
    lock_pattern.sub(lambda match: f'{match.group(1)}"{new_version}"', lock_text),
    encoding="utf-8",
)
PY

echo "Bumped pyproject.toml, server.json and uv.lock to ${new_version}"
