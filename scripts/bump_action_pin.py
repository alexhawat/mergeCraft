#!/usr/bin/env python3
"""Bump the self-review Action pin — one atomic edit, not a hand-run checklist.

``.github/workflows/mergecraft.yml`` pins the self-review Action to a full
commit SHA in five places (the hoisted ``env.MERGECRAFT_ACTION_SHA``, three
``uses: alexhawat/mergeCraft@…`` review rungs, and one
``uses: alexhawat/mergeCraft/get-installation-token@…`` companion-action
reference, #550), ``.github/workflows/mergecraft-approve.yml`` pins the same
companion action a second time, and ``action.yml`` pins the matching
published image **digest** (``runs.image``). Bumping the SHA without also
updating the image digest — or updating some sites and not others — is
exactly the footgun ``scripts/check_action_pin_freshness.py`` and
``scripts/check_action_image_digest.py`` exist to catch. PR #562 hit the
workflow/digest split directly (splitting the pin bump from the digest bump
turned five checks red at once); the very next merge after this script first
shipped hit the companion-action split too — a merge that only advanced the
bare ``mergeCraft@`` rungs left both ``get-installation-token@`` references
behind, and (before ``check_action_pin_freshness.py``'s ``_PIN_RE`` was
widened to see the subpath form) no gate caught it. This script now rewrites
every one of those sites in one pass, from one target SHA, and refuses to
write anything unless every precondition holds first.

Preconditions, all checked before any file is touched:

1. **Ancestry.** ``sha`` must be an ancestor of ``--ref`` (default ``HEAD``).
   A pin that is not part of this branch's history cannot be a legitimate
   bump of it — see #532's "one-sided bump" and #533's staleness incident.
2. **Publication.** GHCR must already serve ``ghcr.io/alexhawat/mergecraft:<sha>``.
   The image is built by ``action-slim-bootstrap`` (``.github/workflows/ci.yml``,
   pull-request into ``pre-0.0.1``) or ``build-images``
   (``.github/workflows/ci-cd.yml``, push to ``main``/``pre-0.0.1``) — this
   script never builds or pushes the image itself. Run the workflow that
   ensures the image exists first (see ``.github/workflows/bump-action-pin.yml``,
   which does exactly that before invoking this script).
3. **Tracing extra.** The published image must have been built with
   ``uv sync --extra tracing`` (#531) — a slim image without it silently
   degrades Logfire/OTEL tracing to a ``NullSink``.
4. **Every pin site already carries the current pin, literally.** If
   ``mergecraft.yml`` or ``mergecraft-approve.yml`` has already drifted (a
   site pins something other than the SHA ``env.MERGECRAFT_ACTION_SHA``
   names), this script refuses rather than silently leaving that drift in
   place — reconcile it by hand first, the same way the #550 follow-up split
   had to be reconciled.

Only once all four hold does the script rewrite ``mergecraft.yml`` and
``mergecraft-approve.yml`` (every literal occurrence of the current pin in
each, in one string replace per file, so every rung and every companion-action
reference moves together by construction) and ``action.yml``'s ``runs.image``
digest, then write all three files.

The GHCR lookup helpers (``ghcr_digest_for_tag``, ``fetch_oci_config_for_tag``,
``image_has_tracing_extra``) are imported from ``check_action_image_digest``
rather than duplicated — that script already owns the GHCR API contract
(retry behaviour, manifest/config parsing, tracing-extra detection), and a
second implementation drifting from it is exactly the kind of split this
script exists to avoid.

Module: scripts.bump_action_pin
Depends: check_action_image_digest (this directory), argparse, re, subprocess,
    sys, pathlib

Exports:
    current_pin — read the self-review Action SHA out of mergecraft.yml.
    resolve_digest — look up + validate the GHCR digest for a target SHA.
    bump — rewrite mergecraft.yml + mergecraft-approve.yml + action.yml for a
        validated target SHA.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from check_action_image_digest import (  # noqa: E402
    SLIM_IMAGE,
    TagLookupResult,
    TagLookupStatus,
    fetch_oci_config_for_tag,
    ghcr_digest_for_tag,
    image_has_tracing_extra,
)

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "mergecraft.yml"
APPROVE_WORKFLOW = REPO / ".github" / "workflows" / "mergecraft-approve.yml"
ACTION_YML = REPO / "action.yml"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ENV_SHA_RE = re.compile(
    r"^\s*MERGECRAFT_ACTION_SHA:\s*[\"']?(?P<sha>[0-9a-f]{40})[\"']?\s*$",
    re.MULTILINE,
)
_IMAGE_DIGEST_RE = re.compile(
    rf'(image:\s*"docker://{re.escape(SLIM_IMAGE)}@sha256:)([a-f0-9]{{64}})(")'
)


class BumpError(RuntimeError):
    """A precondition failed; nothing was written."""


def current_pin(workflow_text: str | None = None) -> str:
    """Return the SHA currently hoisted into ``env.MERGECRAFT_ACTION_SHA``."""
    text = workflow_text if workflow_text is not None else WORKFLOW.read_text(encoding="utf-8")
    match = _ENV_SHA_RE.search(text)
    if match is None:
        msg = f"{WORKFLOW}: no env.MERGECRAFT_ACTION_SHA found"
        raise BumpError(msg)
    return match.group("sha")


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        msg = f"git {' '.join(args)} failed: {completed.stderr.strip()}"
        raise BumpError(msg)
    return completed.stdout.strip()


def assert_is_ancestor(sha: str, ref: str) -> None:
    """Refuse a SHA that is not part of ``ref``'s history."""
    check = subprocess.run(
        ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode != 0:
        msg = f"{sha} is not a known commit in this checkout (fetch it first)"
        raise BumpError(msg)
    ancestry = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, ref],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if ancestry.returncode != 0:
        resolved_ref = _git("rev-parse", ref)
        msg = (
            f"refusing to bump: {sha} is not an ancestor of {ref} ({resolved_ref}). "
            "A pin must be reachable from the branch it reviews — bump order matters "
            "(pin pre-0.0.1 to its own tip before promoting to main); see "
            "docs/workflows.md 'Action pin and evidence artifacts'."
        )
        raise BumpError(msg)


def resolve_digest(sha: str) -> str:
    """Look up the GHCR digest for ``sha``, validating publication + tracing extra."""
    lookup = ghcr_digest_for_tag(sha)
    if lookup.status is TagLookupStatus.MISSING:
        msg = (
            f"no published image for {SLIM_IMAGE}:{sha} — build + push it first "
            "(action-slim-bootstrap in ci.yml, or build-images in ci-cd.yml; the "
            "bump-action-pin.yml workflow does this automatically before calling "
            "this script)"
        )
        raise BumpError(msg)
    if lookup.status is TagLookupStatus.ERROR or lookup.digest is None:
        msg = f"could not resolve GHCR digest for {SLIM_IMAGE}:{sha} (registry error)"
        raise BumpError(msg)

    config = fetch_oci_config_for_tag(sha)
    if config is None:
        msg = f"could not fetch OCI config for {SLIM_IMAGE}:{sha}"
        raise BumpError(msg)
    if not image_has_tracing_extra(config):
        msg = (
            f"published image for {sha} was built without `uv sync --extra tracing` "
            "(#531) — refusing to pin it. Logfire/OTEL tracing would silently degrade "
            "to a NullSink."
        )
        raise BumpError(msg)

    return lookup.digest


def _rewrite_literal_pin(path: Path, old_sha: str, new_sha: str) -> str:
    """Return ``path``'s text with every literal ``old_sha`` occurrence replaced.

    Refuses (raises ``BumpError``, writes nothing) when ``old_sha`` does not
    appear at all — a file that has already drifted off the shared pin must be
    reconciled by hand before an automated bump can safely touch it, rather
    than this script silently leaving that drift in place.
    """
    text = path.read_text(encoding="utf-8")
    occurrences = text.count(old_sha)
    if occurrences == 0:
        msg = f"{path}: current pin {old_sha} not found as literal text — refusing"
        raise BumpError(msg)
    preexisting_new_sha = text.count(new_sha)
    new_text = text.replace(old_sha, new_sha)
    if new_text.count(new_sha) != occurrences + preexisting_new_sha:
        # Should be unreachable (replace() is exact), but this is the one
        # invariant that makes "atomic" true: every pin site in this file
        # moves together.
        msg = f"{path}: replacement count mismatch — refusing to write a partial bump"
        raise BumpError(msg)
    return new_text


def bump(sha: str, *, ref: str = "HEAD") -> tuple[str, str]:
    """Rewrite the pin to ``sha`` across mergecraft.yml, mergecraft-approve.yml,
    and action.yml.

    Returns ``(old_sha, new_digest)``. Raises ``BumpError`` (without writing
    anything) if any precondition fails — ancestry, GHCR publication, the
    tracing extra, or a pin site that has already drifted off the current SHA.
    """
    if not _SHA_RE.fullmatch(sha):
        msg = f"not a full 40-hex commit SHA: {sha!r}"
        raise BumpError(msg)

    assert_is_ancestor(sha, ref)
    digest = resolve_digest(sha)  # "sha256:<64-hex>"

    old_sha = current_pin()
    if old_sha == sha:
        msg = f"{WORKFLOW} already pins {sha} — nothing to bump"
        raise BumpError(msg)

    new_workflow_text = _rewrite_literal_pin(WORKFLOW, old_sha, sha)
    new_approve_text = _rewrite_literal_pin(APPROVE_WORKFLOW, old_sha, sha)

    action_text = ACTION_YML.read_text(encoding="utf-8")
    digest_match = _IMAGE_DIGEST_RE.search(action_text)
    if digest_match is None:
        msg = f"{ACTION_YML}: runs.image is not a digest-pinned {SLIM_IMAGE}@sha256:… reference"
        raise BumpError(msg)
    new_action_text = (
        action_text[: digest_match.start()]
        + digest_match.group(1)
        + digest.removeprefix("sha256:")
        + digest_match.group(3)
        + action_text[digest_match.end() :]
    )

    # Every text is fully computed and validated — write them only now.
    WORKFLOW.write_text(new_workflow_text, encoding="utf-8")
    APPROVE_WORKFLOW.write_text(new_approve_text, encoding="utf-8")
    ACTION_YML.write_text(new_action_text, encoding="utf-8")
    return old_sha, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("sha", help="Full 40-hex commit SHA to pin")
    parser.add_argument(
        "--ref",
        default="HEAD",
        help="Ancestry check: sha must be an ancestor of this ref (default: HEAD)",
    )
    args = parser.parse_args(argv)

    try:
        old_sha, digest = bump(args.sha, ref=args.ref)
    except BumpError as exc:
        print(f"bump-action-pin FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"bump-action-pin OK: {old_sha[:12]} -> {args.sha[:12]} (image digest {digest[:19]}…)")
    print(
        f"  {WORKFLOW}: env.MERGECRAFT_ACTION_SHA + 3 uses: rungs + get-installation-token updated"
    )
    print(f"  {APPROVE_WORKFLOW}: get-installation-token pin updated")
    print(f"  {ACTION_YML}: runs.image digest updated")
    return 0


# Re-exported so callers (and tests) that build a stub lookup result do not
# need a second import from check_action_image_digest for the one type this
# module's own public API surface (resolve_digest's dependency) requires.
__all__ = [
    "BumpError",
    "TagLookupResult",
    "TagLookupStatus",
    "bump",
    "current_pin",
    "main",
    "resolve_digest",
]

if __name__ == "__main__":
    raise SystemExit(main())
