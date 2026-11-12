#!/usr/bin/env bash
# Print pytest --deselect options for every node id in a known-failures file.
# Usage: PYTEST_ADDOPTS="$(scripts/ci_known_failures_addopts.sh FILE)" make test
# Blank lines and lines starting with "#" are ignored. Works on macOS bash 3.2.
set -euo pipefail
[[ $# -eq 1 ]] || { echo "usage: $0 KNOWN_FAILURES_FILE" >&2; exit 2; }
addopts=""
while IFS= read -r node; do
  case "$node" in "" | "#"*) continue ;; esac
  addopts="$addopts --deselect $(printf '%q' "$node")"
done <"$1"
printf '%s\n' "$addopts"
