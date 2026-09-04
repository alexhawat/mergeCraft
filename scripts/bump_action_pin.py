#!/usr/bin/env python3
"""Bump the self-review Action pin in the two-commit order the live pin flow uses.

Plan 19 (and PRs #562 / #603): a pin PR against ``pre-0.0.1`` is two commits.

1. **``--stage sha``** — rewrite ``MERGECRAFT_ACTION_SHA`` and every
   ``uses: alexhawat/mergeCraft@…`` rung in ``mergecraft.yml`` (and any
   remaining companion-action pin in ``mergecraft-approve.yml``). Does **not**
   touch ``action.yml``. Does **not** require the GHCR image: that image is
   published only by ``action-slim-bootstrap`` once this SHA bump is a
   ``pull_request`` into ``pre-0.0.1``.
2. **``--stage digest``** — rewrite ``action.yml``'s ``runs.image`` digest
   after that image exists, with the tracing extra. The workflow pin must
   already equal ``sha`` (commit 1 landed). Never merge a pin PR after
   commit 1 alone.

Splitting SHA from digest is *expected* between those two commits. Merging
after commit 1 is what turned five checks red on #562.

Preconditions, all checked before any file is touched:

1. **Ancestry.** ``sha`` must be an ancestor of ``--ref`` (default ``HEAD``).
2. **``sha`` stage:** every pin site that currently names the old SHA moves
   together. A site that has already drifted off the current pin is refused.
   GHCR is not consulted.
3. **``digest`` stage:** GHCR must serve ``ghcr.io/alexhawat/mergecraft:<sha>``
   built with ``uv sync --extra tracing`` (#531). The workflow pin must
   already equal ``sha``.

The GHCR lookup helpers are imported from ``check_action_image_digest``
rather than duplicated.

Module: scripts.bump_action_pin
Depends: check_action_image_digest (this directory), argparse, re, subprocess,
    sys, pathlib

Exports:
    current_pin — read the self-review Action SHA out of mergecraft.yml.
    resolve_digest — look up + validate the GHCR digest for a target SHA.
    bump — rewrite mergecraft.yml (sha stage) or action.yml (digest stage).
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

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

Stage = Literal["sha", "digest"]

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ENV_SHA_RE = re.compile(
    r"^\s*MERGECRAFT_ACTION_SHA:\s*[\"']?(?P<sha>[0-9a-f]{40})[\"']?\s*$",
    re.MULTILINE,
)
_IMAGE_DIGEST_RE = re.compile(
    rf'(image:\s*"docker://{re.escape(SLIM_IMAGE)}@sha256:)([a-f0-9]{{64}})(")'
)
_PIN_SITE_RE = re.compile(r"uses:\s*alexhawat/mergeCraft(?:/[\w.-]+)*@(?P<sha>[0-9a-f]{40})")


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
            "A pin must be reachable from the branch it reviews — pin PR against "
            "pre-0.0.1 first, then promote to main; see docs/workflows.md."
        )
        raise BumpError(msg)


def resolve_digest(sha: str) -> str:
    """Look up the GHCR digest for ``sha``, validating publication + tracing extra."""
    lookup = ghcr_digest_for_tag(sha)
    if lookup.status is TagLookupStatus.MISSING:
        msg = (
            f"no published image for {SLIM_IMAGE}:{sha} — wait for "
            "action-slim-bootstrap on the pin PR (base pre-0.0.1) to finish, "
            "then rerun with --stage digest"
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
    """Return ``path``'s text with every literal ``old_sha`` occurrence replaced."""
    text = path.read_text(encoding="utf-8")
    occurrences = text.count(old_sha)
    if occurrences == 0:
        msg = f"{path}: current pin {old_sha} not found as literal text — refusing"
        raise BumpError(msg)
    preexisting_new_sha = text.count(new_sha)
    new_text = text.replace(old_sha, new_sha)
    if new_text.count(new_sha) != occurrences + preexisting_new_sha:
        msg = f"{path}: replacement count mismatch — refusing to write a partial bump"
        raise BumpError(msg)
    return new_text


def _optional_approve_rewrite(old_sha: str, new_sha: str) -> str | None:
    """Rewrite approve-workflow pins when present; skip if it has none.

    A leftover remote ``get-installation-token@<other-sha>`` is refused rather
    than left behind (the split-pin class #550's freshness gate exists to
    catch). A file with no remote pin (local ``./get-installation-token``) is
    skipped.
    """
    if not APPROVE_WORKFLOW.is_file():
        return None
    text = APPROVE_WORKFLOW.read_text(encoding="utf-8")
    if old_sha in text:
        return _rewrite_literal_pin(APPROVE_WORKFLOW, old_sha, new_sha)
    leftover = {match.group("sha") for match in _PIN_SITE_RE.finditer(text)}
    if leftover:
        msg = (
            f"{APPROVE_WORKFLOW}: pins {sorted(leftover)} rather than current "
            f"{old_sha} — reconcile by hand before an automated bump"
        )
        raise BumpError(msg)
    return None


def _rewrite_action_digest(digest: str) -> str:
    action_text = ACTION_YML.read_text(encoding="utf-8")
    digest_match = _IMAGE_DIGEST_RE.search(action_text)
    if digest_match is None:
        msg = f"{ACTION_YML}: runs.image is not a digest-pinned {SLIM_IMAGE}@sha256:… reference"
        raise BumpError(msg)
    return (
        action_text[: digest_match.start()]
        + digest_match.group(1)
        + digest.removeprefix("sha256:")
        + digest_match.group(3)
        + action_text[digest_match.end() :]
    )


def bump(sha: str, *, ref: str = "HEAD", stage: Stage = "sha") -> tuple[str, str | None]:
    """Rewrite the pin to ``sha`` for ``stage``.

    Returns ``(old_sha, digest_or_none)``. Raises ``BumpError`` without writing
    if any precondition fails.
    """
    if not _SHA_RE.fullmatch(sha):
        msg = f"not a full 40-hex commit SHA: {sha!r}"
        raise BumpError(msg)
    if stage not in ("sha", "digest"):
        msg = f"stage must be 'sha' or 'digest', not {stage!r}"
        raise BumpError(msg)

    assert_is_ancestor(sha, ref)
    old_sha = current_pin()

    if stage == "sha":
        if old_sha == sha:
            msg = f"{WORKFLOW} already pins {sha} — nothing to bump"
            raise BumpError(msg)
        new_workflow_text = _rewrite_literal_pin(WORKFLOW, old_sha, sha)
        new_approve_text = _optional_approve_rewrite(old_sha, sha)
        WORKFLOW.write_text(new_workflow_text, encoding="utf-8")
        if new_approve_text is not None:
            APPROVE_WORKFLOW.write_text(new_approve_text, encoding="utf-8")
        return old_sha, None

    if old_sha != sha:
        msg = (
            f"{WORKFLOW} pins {old_sha}, not {sha} — run --stage sha first "
            "(commit 1 of the pin PR) and wait for action-slim-bootstrap"
        )
        raise BumpError(msg)
    digest = resolve_digest(sha)
    new_action_text = _rewrite_action_digest(digest)
    ACTION_YML.write_text(new_action_text, encoding="utf-8")
    return old_sha, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("sha", help="Full 40-hex commit SHA to pin")
    parser.add_argument(
        "--stage",
        choices=("sha", "digest"),
        default="sha",
        help="sha: workflow pin only (commit 1). digest: action.yml only (commit 2).",
    )
    parser.add_argument(
        "--ref",
        default="HEAD",
        help="Ancestry check: sha must be an ancestor of this ref (default: HEAD)",
    )
    args = parser.parse_args(argv)

    try:
        old_sha, digest = bump(args.sha, ref=args.ref, stage=args.stage)
    except BumpError as exc:
        print(f"bump-action-pin FAILED: {exc}", file=sys.stderr)
        return 1

    if args.stage == "sha":
        print(f"bump-action-pin OK (sha): {old_sha[:12]} -> {args.sha[:12]}")
        print(f"  {WORKFLOW}: env.MERGECRAFT_ACTION_SHA + uses: rungs updated")
        print("  action.yml: unchanged — run --stage digest after action-slim-bootstrap")
    else:
        assert digest is not None
        print(f"bump-action-pin OK (digest): {args.sha[:12]} (image digest {digest[:19]}…)")
        print(f"  {ACTION_YML}: runs.image digest updated")
    return 0


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
