#!/usr/bin/env python3
"""Write a refreshed ChatGPT-subscription login back to the ``CODEX_AUTH_JSON`` secret.

The self-review's Codex rung authenticates with the ChatGPT login stored in the
``CODEX_AUTH_JSON`` repository secret. Codex rotates that login's refresh token
on use, so once a CI run refreshes it the stored token is spent and every later
consumer fails with "refresh token was already used" until a maintainer
re-mints it by hand (#970). The Codex driver copies the refreshed ``auth.json``
to the path named by ``MERGECRAFT_CODEX_AUTH_EXPORT`` — only when its refresh
token changed — and this script stores that copy as the new secret.

Runs on the runner host, from the trusted copy the workflow staged before any
mergeCraft step ran (the workspace holds the branch under review by then).
Standard library only: the runner's ``python3`` is all it has.

The credential is never printed. Every outcome is reported as a workflow
``::notice`` / ``::warning`` that names paths and reasons only. The exported
file is removed on every path once it has been read.

Module: scripts.codex_auth_writeback
Depends: argparse, json, os, pathlib, subprocess, sys

Exports:
    decide — classify the exported file against the stored secret.
    write_back — run ``gh secret set`` with the exported file on stdin.
    main — CLI entry.

Usage (as the workflow step runs it)::

    python3 scripts/codex_auth_writeback.py \\
        --exported "$RUNNER_TEMP/mergecraft-codex-auth/auth.json" \\
        --original-env CODEX_AUTH_JSON_ORIGINAL \\
        --secret-name CODEX_AUTH_JSON --repo "$GITHUB_REPOSITORY"
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

EXPIRED_KIND = "reviewer_credential_expired"
"""The infra reason the Codex driver records for a dead login; nothing to store then."""

_TITLE = "mergecraft codex login"


class Decision(NamedTuple):
    """Whether to write the exported login back, and the reason either way."""

    write: bool
    reason: str


def _refresh_token(raw: str) -> str | None:
    """Return the refresh token in a ``CODEX_AUTH_JSON`` body, or ``None``."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens")
    source = tokens if isinstance(tokens, dict) else data
    for key in ("refresh_token", "refresh"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _account_id(raw: str) -> str | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None
    value = tokens.get("account_id")
    return value if isinstance(value, str) and value.strip() else None


def decide(*, exported: str | None, original: str, infra_reason: str = "") -> Decision:
    """Classify the exported body against the stored secret.

    Args:
        exported: Contents of the exported ``auth.json``, or ``None`` when the
            file does not exist.
        original: The stored ``CODEX_AUTH_JSON`` value the run started with.
        infra_reason: The infra reason the rung recorded, when the caller has it.

    Returns:
        A :class:`Decision`; ``write`` is ``True`` only for a parsable body whose
        refresh token is present, differs from the stored one, and belongs to
        the same account.
    """
    if infra_reason == EXPIRED_KIND:
        return Decision(False, "the rung reported the login expired; nothing to write back")
    if exported is None:
        return Decision(False, "no refreshed login was exported; the stored secret is current")
    if not original.strip():
        return Decision(False, "the stored secret is empty here; refusing to write back blind")
    try:
        parsed = json.loads(exported)
    except json.JSONDecodeError:
        return Decision(False, "the exported login is not JSON; not writing it back")
    if not isinstance(parsed, dict):
        return Decision(False, "the exported login is not a JSON object; not writing it back")
    token = _refresh_token(exported)
    if token is None:
        return Decision(False, "the exported login carries no refresh token; not writing it back")
    if token == _refresh_token(original):
        return Decision(False, "the refresh token is unchanged; nothing to write back")
    stored_account = _account_id(original)
    exported_account = _account_id(exported)
    if stored_account and exported_account and stored_account != exported_account:
        return Decision(
            False, "the exported login belongs to a different account; not writing it back"
        )
    return Decision(True, "Codex refreshed the login; storing the new refresh token")


def write_back(*, exported_path: Path, secret_name: str, repo: str, gh: str = "gh") -> int:
    """Store the exported file as ``secret_name`` with ``gh secret set``.

    The body goes to ``gh`` on stdin, so it never appears in argv or logs.
    Returns the ``gh`` exit status.
    """
    with exported_path.open("rb") as handle:
        completed = subprocess.run(  # fixed argv, credential on stdin only
            [gh, "secret", "set", secret_name, "--repo", repo],
            stdin=handle,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip().splitlines()
        tail = detail[-1] if detail else "no stderr"
        _emit(
            "warning", f"gh secret set {secret_name} failed (exit {completed.returncode}): {tail}"
        )
    return completed.returncode


def _emit(level: str, message: str) -> None:
    print(f"::{level} title={_TITLE}::{message}")


def _discard(path: Path) -> None:
    """Overwrite then remove the exported file; best effort, never raises."""
    try:
        if path.is_file():
            size = path.stat().st_size
            with path.open("r+b") as handle:
                handle.write(b"\0" * size)
                handle.flush()
                os.fsync(handle.fileno())
            path.unlink()
    except OSError as exc:
        _emit("warning", f"could not remove the exported login at {path}: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exported", required=True, type=Path, help="exported auth.json path")
    parser.add_argument(
        "--original-env",
        required=True,
        help="env var holding the CODEX_AUTH_JSON value the run started with",
    )
    parser.add_argument("--secret-name", default="CODEX_AUTH_JSON")
    parser.add_argument("--repo", required=True, help="owner/name of the repository")
    parser.add_argument("--infra-reason", default="", help="the rung's recorded infra reason")
    parser.add_argument("--gh", default="gh", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    exported_path: Path = args.exported
    exported: str | None
    try:
        exported = exported_path.read_text(encoding="utf-8") if exported_path.is_file() else None
    except OSError as exc:
        _emit("warning", f"cannot read the exported login at {exported_path}: {exc}")
        _discard(exported_path)
        return 1

    try:
        decision = decide(
            exported=exported,
            original=os.environ.get(args.original_env, ""),
            infra_reason=args.infra_reason,
        )
        if not decision.write:
            _emit("notice", decision.reason)
            return 0
        status = write_back(
            exported_path=exported_path, secret_name=args.secret_name, repo=args.repo, gh=args.gh
        )
        if status == 0:
            _emit("notice", f"{decision.reason}; {args.secret_name} updated in {args.repo}")
            return 0
        return 1
    finally:
        _discard(exported_path)


if __name__ == "__main__":
    sys.exit(main())
