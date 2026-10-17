#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Craft postReleaseCommand — runs after a successful `craft publish`.
#
# It used to rewrite the package version to the next `-dev` version and leave the
# edit uncommitted. Committed, that edit would advertise a version that does not
# exist on the registry manifest (server.json) and fail the manifest drift check on
# the next release; uncommitted, it was easy to miss and carried no convention. The
# convention now: the version on the default branch stays the last released version
# until the next prepare bumps it. This hook therefore edits nothing. It only checks
# that Craft handed it the released version and says so.
set -euo pipefail

if [[ -z "${CRAFT_NEW_VERSION:-}" ]]; then
  echo "CRAFT_NEW_VERSION is required" >&2
  exit 1
fi

echo "Released ${CRAFT_NEW_VERSION}. The version on main stays the last released version until the next prepare; no development version is written."
