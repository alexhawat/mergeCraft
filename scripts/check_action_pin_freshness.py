#!/usr/bin/env python3
"""Guard: the self-review Action pin must not drift far behind this branch.

``.github/workflows/mergecraft.yml`` triggers on ``pull_request_target``, so
GitHub resolves its definition — and therefore its ``uses:`` pin — from the
repository **default branch**, never from the PR base. A fix merged to
``pre-0.0.1`` does not reach the reviewer until it reaches ``main``.

Nothing detected that skew, and it reached 687 commits: PR #443 timed out on a
600s ceiling that had already been fixed on ``pre-0.0.1``, because the run used
``main``'s older pin. The failure mode is quiet — the branch holds the fix, the
branch's own workflow pins the fixed SHA, and CI still exercises the old code
(#450).

Three checks:

1. **Self-consistency** (offline, always runs). Every ``uses:`` pin of this
   action inside a workflow file must be the same SHA. The workflow header
   warns that a one-sided bump is a footgun; this makes it an error.
2. **Freshness** (needs the default-branch ref). The default branch's pin must
   be an ancestor of this branch's pin and within ``MAX_DRIFT`` commits of it.
   Skips with a notice when the ref is not fetched, so a local ``make lint``
   in a shallow or offline checkout does not fail on it.
3. **Staleness** (needs the default-branch ref). The pin must not lag the
   default branch's own tip by more than ``MAX_PRODUCT_LAG`` commits touching
   ``src/mergecraft/``. Check 2 compares the two branches' pins only to each
   other, so it passes when *both* are equally stale: after PR #457 merged,
   both branches pinned the same SHA and the check reported OK while the
   reviewer ran none of the fixes that had just landed. Measuring against the
   default branch's tip rather than HEAD keeps this stable, since unmerged
   feature commits are not something a pin could reference yet.

Module: scripts.check_action_pin_freshness
Depends: os, re, subprocess, sys, pathlib

Exports:
    main — CLI entry; compares self-review Action pins for drift.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO / ".github" / "workflows"

# The action pins itself here; a consumer's own pin is their business. The
# optional `(?:/[\w.-]+)*` subpath covers companion actions published from the
# same repo/SHA (e.g. `alexhawat/mergeCraft/get-installation-token@<sha>`,
# #550) — those must stay in lockstep with the review rungs exactly like the
# rungs must stay in lockstep with each other; a merge that only advances the
# bare `mergeCraft@` pin silently split them once (see the mergecraft.yml /
# mergecraft-approve.yml `get-installation-token` steps' history).
_PIN_RE = re.compile(r"uses:\s*alexhawat/mergeCraft(?:/[\w.-]+)*@(?P<sha>[0-9a-f]{40})")
_ENV_SHA_RE = re.compile(
    r"^\s*MERGECRAFT_ACTION_SHA:\s*[\"']?(?P<sha>[0-9a-f]{40})[\"']?\s*$",
    re.MULTILINE,
)

DEFAULT_BRANCH = os.environ.get("MERGECRAFT_DEFAULT_BRANCH", "main")

# Chosen to catch a genuinely stale reviewer, not routine lag: a pin a few
# merges behind still runs substantially current code, while hundreds of
# commits behind is how #450 went unnoticed. Override for a tighter policy.
MAX_DRIFT = int(os.environ.get("MERGECRAFT_MAX_ACTION_PIN_DRIFT", "100"))

# Product-code commits the pin may lag the default branch's tip by. Counted
# over ``src/mergecraft/`` only: docs, tests and workflow commits do not change
# what the reviewer executes, so counting them would fire for reasons an
# operator cannot act on. Small, because each one is a behaviour difference
# between the reviewer and the branch it is reviewing.
MAX_PRODUCT_LAG = int(os.environ.get("MERGECRAFT_MAX_ACTION_PIN_PRODUCT_LAG", "5"))

# The tree whose changes alter reviewer behaviour.
PRODUCT_PATH = "src/mergecraft/"


def _pins_in(text: str) -> list[tuple[int, str]]:
    """Return ``(line_number, sha)`` for every self-referential Action pin."""
    return [
        (index, match.group("sha"))
        for index, line in enumerate(text.splitlines(), start=1)
        if (match := _PIN_RE.search(line))
    ]


def _git(*args: str) -> str | None:
    """Run a read-only git command, returning ``None`` when it fails."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _default_branch_workflow(rel_path: str) -> str | None:
    """Return the workflow's text on the default branch, or ``None``."""
    for ref in (f"origin/{DEFAULT_BRANCH}", DEFAULT_BRANCH):
        if _git("rev-parse", "--verify", "--quiet", ref) is None:
            continue
        text = _git("show", f"{ref}:{rel_path}")
        if text is not None:
            return text
    return None


def _check_self_consistency(rel_path: str, pins: list[tuple[int, str]]) -> list[str]:
    """Every pin inside one workflow file must name the same SHA."""
    distinct = {sha for _, sha in pins}
    if len(distinct) <= 1:
        return []
    locations = ", ".join(f"line {line}: {sha[:12]}" for line, sha in pins)
    return [
        f"{rel_path}: {len(distinct)} different Action pins in one file "
        f"({locations}). A one-sided bump leaves the review and fallback steps "
        f"on different code."
    ]


def _check_env_parity(rel_path: str, text: str, pins: list[tuple[int, str]]) -> list[str]:
    """Every rung pin must match the hoisted ``env.MERGECRAFT_ACTION_SHA``."""
    env_match = _ENV_SHA_RE.search(text)
    if env_match is None:
        return []
    env_sha = env_match.group("sha")
    mismatched = [(line, sha) for line, sha in pins if sha != env_sha]
    if not mismatched:
        return []
    locations = ", ".join(f"line {line}: {sha[:12]}" for line, sha in mismatched)
    return [
        f"{rel_path}: uses: pin(s) disagree with env.MERGECRAFT_ACTION_SHA "
        f"({env_sha[:12]}): {locations}. Bump env.MERGECRAFT_ACTION_SHA only "
        f"and mirror to every rung."
    ]


def _check_freshness(rel_path: str, head_sha: str) -> list[str]:
    """Compare this branch's pin against the default branch's."""
    base_text = _default_branch_workflow(rel_path)
    if base_text is None:
        print(
            f"action-pin-check: skipped freshness for {rel_path} — "
            f"'{DEFAULT_BRANCH}' is not available in this checkout",
        )
        return []
    base_pins = _pins_in(base_text)
    if not base_pins:
        return []
    base_sha = base_pins[0][1]
    if base_sha == head_sha:
        return []
    if _git("cat-file", "-e", f"{base_sha}^{{commit}}") is None:
        print(
            f"action-pin-check: skipped freshness for {rel_path} — "
            f"{DEFAULT_BRANCH} pin {base_sha[:12]} is not in this checkout",
        )
        return []
    if _git("merge-base", "--is-ancestor", base_sha, head_sha) is None:
        return [
            f"{rel_path}: {DEFAULT_BRANCH} pins {base_sha[:12]}, which is not an "
            f"ancestor of this branch's pin {head_sha[:12]}. The branches have "
            f"diverged; reconcile them before merging."
        ]
    drift_raw = _git("rev-list", "--count", f"{base_sha}..{head_sha}")
    drift = int(drift_raw) if drift_raw and drift_raw.isdigit() else 0
    if drift <= MAX_DRIFT:
        return []
    return [
        f"{rel_path}: {DEFAULT_BRANCH} pins {base_sha[:12]}, {drift} commits behind "
        f"this branch's pin {head_sha[:12]} (max {MAX_DRIFT}). Because this workflow "
        f"runs on pull_request_target, the reviewer executes the {DEFAULT_BRANCH} pin "
        f"— every fix newer than it is absent from CI. Bump {DEFAULT_BRANCH}."
    ]


def _check_staleness(rel_path: str, head_sha: str) -> list[str]:
    """Compare the pin against the default branch's tip, not against another pin."""
    ref = f"origin/{DEFAULT_BRANCH}"
    if _git("rev-parse", "--verify", "--quiet", ref) is None:
        ref = DEFAULT_BRANCH
        if _git("rev-parse", "--verify", "--quiet", ref) is None:
            return []
    if _git("cat-file", "-e", f"{head_sha}^{{commit}}") is None:
        return []
    if _git("merge-base", "--is-ancestor", head_sha, ref) is None:
        # The pin is not on the default branch's history: either it is ahead
        # (bumped here, not yet promoted) or it points somewhere unrelated.
        # Neither is staleness, and check 2 already covers divergence.
        return []
    lag_raw = _git("rev-list", "--count", f"{head_sha}..{ref}", "--", PRODUCT_PATH)
    lag = int(lag_raw) if lag_raw and lag_raw.isdigit() else 0
    if lag <= MAX_PRODUCT_LAG:
        return []
    return [
        f"{rel_path}: pin {head_sha[:12]} lags {DEFAULT_BRANCH} by {lag} commits touching "
        f"{PRODUCT_PATH} (max {MAX_PRODUCT_LAG}). The reviewer is not running the product "
        f"code on {DEFAULT_BRANCH}, so anything merged since the pin is absent from every "
        f"review. Bump the pin."
    ]


def main() -> int:
    """Report Action-pin drift; return 1 when a check fails."""
    if not WORKFLOW_DIR.is_dir():
        print("action-pin-check: no .github/workflows directory; nothing to check")
        return 0

    failures: list[str] = []
    checked = 0
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        pins = _pins_in(text)
        if not pins:
            continue
        checked += 1
        rel_path = path.relative_to(REPO).as_posix()
        failures.extend(_check_self_consistency(rel_path, pins))
        failures.extend(_check_env_parity(rel_path, text, pins))
        failures.extend(_check_freshness(rel_path, pins[0][1]))
        failures.extend(_check_staleness(rel_path, pins[0][1]))

    if failures:
        print("action-pin-check FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(f"action-pin-check OK: {checked} workflow(s) pin this action")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
