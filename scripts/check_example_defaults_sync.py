#!/usr/bin/env python3
"""Guard: example-workflow defaults stay in sync and pinned to their release tag.

Two copies of the shared defaults exist — the checkout source of truth under
``scripts/example_workflows/`` and the packaged copy under
``src/mergecraft/data/example_workflows/``. A workflow renders the immutable
``action_sha_minimal`` commit while Harbor installs mergeCraft by the release
``action_pin_minimal`` tag, so the two are updated by hand and can rot apart.
This script fails when the copies drift and when the SHA does not equal the
commit the tag resolves to.

The tag comparison runs a live ``git ls-remote``; when the remote cannot be
reached it prints a notice and skips that half, so a local ``make pins-check``
in an offline checkout does not fail on the network. A remote that *answers*
but has no such tag is a failure, not a skip: the pin names a release that does
not exist, so there is no commit to agree with. The offline half — the recorded
capture — is exercised by the pins test suite.

Module: scripts.check_example_defaults_sync
Depends: argparse, subprocess, sys, pathlib, typing, yaml

Exports:
    main — CLI entry; byte-identity and tag/commit agreement for the defaults.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal, NamedTuple

import yaml

REPO = Path(__file__).resolve().parents[1]
CHECKOUT_DEFAULTS = REPO / "scripts" / "example_workflows" / "defaults.yaml"
PACKAGED_DEFAULTS = REPO / "src" / "mergecraft" / "data" / "example_workflows" / "defaults.yaml"
_DEFAULT_REMOTE = "origin"


def _load(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"expected a mapping in {path}"
        raise TypeError(msg)
    return raw


def _check_byte_identity() -> list[str]:
    """Return drift messages when the checkout and packaged copies differ."""
    if not CHECKOUT_DEFAULTS.is_file():
        return [f"missing {CHECKOUT_DEFAULTS.relative_to(REPO)}"]
    if not PACKAGED_DEFAULTS.is_file():
        return [f"missing {PACKAGED_DEFAULTS.relative_to(REPO)}"]
    if CHECKOUT_DEFAULTS.read_bytes() != PACKAGED_DEFAULTS.read_bytes():
        return [
            "defaults.yaml copies drifted (edit scripts/example_workflows/defaults.yaml, "
            "sync the packaged copy, then make pins-check)"
        ]
    return []


class _TagResolution(NamedTuple):
    """Outcome of resolving a release tag against a remote.

    ``state`` keeps the three cases distinct so an *absent* tag (the remote
    answered but has no such ref) can fail instead of being conflated with an
    *unreachable* remote (which keeps the offline grace):

    - ``"resolved"`` — ``commit`` is the SHA the tag points at.
    - ``"absent"`` — the remote is reachable but has no such tag.
    - ``"unreachable"`` — the remote could not be queried; skip the comparison.
    """

    state: Literal["resolved", "absent", "unreachable"]
    commit: str | None = None


def _resolve_tag_commit(tag: str, remote: str) -> _TagResolution:
    """Resolve *tag* on *remote*, distinguishing absent from unreachable.

    A non-zero ``git`` exit, ``OSError`` or timeout means the remote could not
    be queried (``unreachable``). A zero exit with no ``refs/tags/<tag>`` (or
    only a peeled ref yielding no commit) means the remote answered and the tag
    does not exist (``absent``).
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", remote, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _TagResolution("unreachable")
    if result.returncode != 0:
        return _TagResolution("unreachable")
    peeled = ""
    plain = ""
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        sha, ref = fields[0], fields[1]
        if ref.endswith("^{}"):
            peeled = sha
        elif ref == f"refs/tags/{tag}":
            plain = sha
    # An annotated tag lists both the tag object and the peeled commit; the
    # peeled commit is what a workflow ``uses:`` resolves to.
    resolved = peeled or plain
    if not resolved:
        # The remote answered but never heard of this tag: a deleted, mistyped
        # or never-pushed release pin, not an offline checkout.
        return _TagResolution("absent")
    return _TagResolution("resolved", resolved)


def main() -> int:
    """Compare the defaults copies and the tag against the pinned commit."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remote",
        default=_DEFAULT_REMOTE,
        help=f"Git remote to resolve the release tag against (default: {_DEFAULT_REMOTE}).",
    )
    args = parser.parse_args()

    failures = _check_byte_identity()
    defaults = _load(CHECKOUT_DEFAULTS)
    tag = str(defaults.get("action_pin_minimal", "")).strip()
    pinned = str(defaults.get("action_sha_minimal", "")).strip()
    if not tag or not pinned:
        failures.append("defaults.yaml must declare both action_pin_minimal and action_sha_minimal")
    else:
        lookup = _resolve_tag_commit(tag, args.remote)
        if lookup.state == "unreachable":
            print(
                f"notice: could not resolve {tag} from remote {args.remote!r} "
                "— skipping the tag/commit comparison",
                file=sys.stderr,
            )
        elif lookup.state == "absent":
            failures.append(
                f"action_sha_minimal ({pinned}) cannot match the tag {tag!r}: "
                f"the remote {args.remote!r} has no such tag; "
                "push the release tag or refresh action_pin_minimal"
            )
        elif lookup.commit != pinned:
            failures.append(
                f"action_sha_minimal ({pinned}) does not equal the commit "
                f"{tag} resolves to ({lookup.commit}); refresh the SHA key"
            )

    if failures:
        print("example-workflow defaults drift:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print("example-workflow defaults OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
