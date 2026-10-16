#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Set the version Craft is preparing in pyproject.toml and server.json.
#
# Craft invokes this as `bash scripts/bump-version.sh <oldVersion> <newVersion>`,
# positionally, with CRAFT_OLD_VERSION / CRAFT_NEW_VERSION also exported. The
# new version is the second argument. Rewriting server.json here is what keeps
# a prepared release branch from failing its own mcp-server-json-check drift
# gate: Craft's own auto-bump would edit pyproject.toml alone.
#
# No project import and no uv: the Release workflow's prepare job installs
# nothing and has no virtualenv. stdlib python3 plus perl only.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

new_version="${2:-}"
if [[ -z "${new_version}" ]]; then
  echo "usage: bump-version.sh <old-version> <new-version> (new version is required)" >&2
  exit 1
fi

perl -i -pe "s/^version = \".*\"/version = \"${new_version}\"/" pyproject.toml
grep -q "version = \"${new_version}\"" pyproject.toml

python3 - "$new_version" <<'PY'
import json
import sys
from pathlib import Path

new_version = sys.argv[1]
path = Path("server.json")
data = json.loads(path.read_text(encoding="utf-8"))

# Fail loudly on a manifest that lost a field: overwriting a broken server.json
# would hide the defect, and the committed file must keep both fields.
if not isinstance(data.get("version"), str):
    raise SystemExit("server.json is missing its top-level version field")
packages = data.get("packages")
if (
    not isinstance(packages, list)
    or not packages
    or not isinstance(packages[0], dict)
    or not isinstance(packages[0].get("version"), str)
):
    raise SystemExit("server.json is missing packages[0].version")

data["version"] = new_version
packages[0]["version"] = new_version
path.write_text(
    json.dumps(data, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
PY

echo "Bumped pyproject.toml and server.json to ${new_version}"
