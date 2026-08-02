#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Bump pyproject.toml to the next patch dev version after a successful publish.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -z "${CRAFT_NEW_VERSION:-}" ]]; then
  echo "CRAFT_NEW_VERSION is required" >&2
  exit 1
fi

IFS='.' read -r major minor patch <<< "${CRAFT_NEW_VERSION%%-*}"
patch="${patch%%[^0-9]*}"
dev_version="${major}.${minor}.$((patch + 1))-dev"

perl -i -pe "s/^version = \".*\"/version = \"${dev_version}\"/" pyproject.toml
grep -q "version = \"${dev_version}\"" pyproject.toml

echo "Bumped development version to ${dev_version}"
