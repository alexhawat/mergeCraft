#!/usr/bin/env python3
"""Guard: refuse to push commits authored or committed by an untrusted email.

Client-side companion to ``trust.sandboxTrustedAuthors``
(``src/mergecraft/config/trust_policy.py``, ``docs/trust-policy.md``): that knob
gates the Codex sandbox override server-side; this guard catches the same
mistake — a fork PR checked out onto a local branch and pushed to ``origin`` —
before the branch ever reaches origin at all.

This is a guardrail, not a gate: when the push range genuinely can't be
determined it **passes**. It must never block a legitimate push on a detection
failure. "Genuinely" excludes a *new* remote branch: git's pre-push protocol
passes an all-zeros ``<remote-sha>`` when the remote ref does not exist yet,
and pre-commit forwards it as ``PRE_COMMIT_FROM_REF``. That case is not
undeterminable — it means every commit on the branch is new to the remote,
which is the case this guard most needs to check, and is exactly the shape a
fork branch pushed to ``origin`` for the first time takes.

Module: scripts.check_push_authors
Depends: pathlib, subprocess, sys

Exports:
    main — CLI / ``pre-push`` hook entry; refuses commits by an untrusted email.

Usage:
    Invoked automatically as the ``pre-push`` git hook (via pre-commit, which
    sets ``PRE_COMMIT_FROM_REF`` / ``PRE_COMMIT_TO_REF``). For manual testing:

        uv run python scripts/check_push_authors.py --range origin/main..HEAD
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ALLOWLIST_PATH = REPO / ".github" / "trusted-authors.txt"
TRUSTED_AUTHORS_ENV = "MERGECRAFT_TRUSTED_AUTHORS"


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` in the repo root; never raises on a non-zero exit."""
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _default_branch() -> str | None:
    """Return the short name of ``origin``'s default branch, if resolvable."""
    result = _run_git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().rsplit("/", 1)[-1]
    return None


def _is_zero_sha(ref: str | None) -> bool:
    """True for git's all-zeros sentinel sha.

    Matched by shape rather than against a fixed 40-character literal: a
    SHA-256 repository uses 64 zeros for the same sentinel.
    """
    return bool(ref) and set(str(ref)) == {"0"}


def _new_branch_range(to_ref: str) -> str | None:
    """Return the range for a push creating a new remote branch, or None.

    Prefers ``merge-base(origin/<default>, <to_ref>)..<to_ref>`` so the range is
    the branch's own commits rather than everything that landed on the default
    branch since it diverged. Falls back to ``origin/<default>..<to_ref>``.
    """
    default_branch = _default_branch()
    if not default_branch:
        return None
    base_ref = f"origin/{default_branch}"
    if _run_git(["rev-parse", "--verify", base_ref]).returncode != 0:
        return None
    merge_base = _run_git(["merge-base", base_ref, to_ref])
    if merge_base.returncode == 0 and merge_base.stdout.strip():
        return f"{merge_base.stdout.strip()}..{to_ref}"
    return f"{base_ref}..{to_ref}"


def _resolve_range(explicit: str | None) -> str | None:
    """Return a ``<base>..<head>`` git range for the push, or None if undeterminable.

    Precedence: an explicit ``--range``; ``PRE_COMMIT_FROM_REF`` /
    ``PRE_COMMIT_TO_REF`` (set by pre-commit for the ``pre-push`` stage), with
    an all-zeros ``from`` ref resolved against the default branch instead of
    passed through as a bogus range; ``@{upstream}..HEAD``;
    ``origin/<default-branch>..HEAD``.
    """
    if explicit:
        return explicit

    from_ref = os.environ.get("PRE_COMMIT_FROM_REF")
    to_ref = os.environ.get("PRE_COMMIT_TO_REF")
    if to_ref and _is_zero_sha(from_ref):
        # New remote branch: `git log 000..000..HEAD` is not a valid range, and
        # letting it fail turned this guard into a no-op on exactly the push it
        # exists to catch.
        return _new_branch_range(to_ref)
    if from_ref and to_ref:
        return f"{from_ref}..{to_ref}"

    upstream = _run_git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    if upstream.returncode == 0 and upstream.stdout.strip():
        return f"{upstream.stdout.strip()}..HEAD"

    default_branch = _default_branch()
    if default_branch:
        candidate = f"origin/{default_branch}"
        probe = _run_git(["rev-parse", "--verify", candidate])
        if probe.returncode == 0:
            return f"{candidate}..HEAD"

    return None


def _commits_in_range(range_spec: str) -> list[tuple[str, str, str]] | None:
    """Return ``(sha, author_email, committer_email)`` for each commit, or None on failure."""
    result = _run_git(["log", "--format=%H%n%ae%n%ce", range_spec])
    if result.returncode != 0:
        return None
    lines = result.stdout.splitlines()
    commits: list[tuple[str, str, str]] = []
    for i in range(0, len(lines) - 2, 3):
        commits.append((lines[i], lines[i + 1], lines[i + 2]))
    return commits


def _load_allowlist() -> set[str]:
    """Read the trusted-email allowlist: env var overrides the committed file."""
    env_value = os.environ.get(TRUSTED_AUTHORS_ENV)
    if env_value is not None:
        return {email.strip().lower() for email in env_value.split(",") if email.strip()}
    if not ALLOWLIST_PATH.is_file():
        return set()
    emails: set[str] = set()
    for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        emails.add(stripped.lower())
    return emails


def main(argv: list[str] | None = None) -> int:
    """Refuse the push when a commit in range carries an untrusted author/committer email."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--range",
        dest="range_spec",
        default=None,
        help="Explicit git range to check, e.g. origin/main..HEAD (default: auto-detect)",
    )
    args = parser.parse_args(argv)

    if _is_zero_sha(os.environ.get("PRE_COMMIT_TO_REF")):
        print(
            "check_push_authors: PRE_COMMIT_TO_REF is the all-zeros sentinel "
            "(branch deletion) — nothing to check",
            file=sys.stderr,
        )
        return 0

    range_spec = _resolve_range(args.range_spec)
    if range_spec is None:
        print(
            "check_push_authors: could not determine the push range "
            "(no --range, no pre-commit refs, no upstream, no origin default branch) "
            "— skipping the author check",
            file=sys.stderr,
        )
        return 0

    commits = _commits_in_range(range_spec)
    if commits is None:
        print(f"check_push_authors: `git log {range_spec}` failed; skipping", file=sys.stderr)
        return 0
    if not commits:
        return 0

    allowlist = _load_allowlist()
    if not allowlist:
        print(
            "check_push_authors: no trusted-author allowlist configured; skipping",
            file=sys.stderr,
        )
        return 0

    violations: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for sha, author_email, committer_email in commits:
        for email in (author_email, committer_email):
            if not email or email.lower() in allowlist:
                continue
            key = (sha, email)
            if key in seen:
                continue
            seen.add(key)
            violations.append(key)

    if not violations:
        return 0

    print(
        "check_push_authors: refusing to push — commit(s) with an untrusted author/"
        "committer email:",
        file=sys.stderr,
    )
    for sha, email in violations:
        print(f"  {sha[:12]}  {email}", file=sys.stderr)
    print(file=sys.stderr)
    print(
        "If this is expected: add the address to .github/trusted-authors.txt.\n"
        "If this push is deliberate (e.g. you know the commit's provenance): "
        "`git push --no-verify`.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
