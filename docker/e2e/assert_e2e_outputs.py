#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Assert Action-image E2E outputs (structured ``result`` + check-run shape)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _parse_github_output(path: Path) -> dict[str, str]:
    """Parse a ``$GITHUB_OUTPUT`` file including UUID-heredoc multiline values."""
    text = path.read_text(encoding="utf-8")
    outputs: dict[str, str] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        heredoc = re.match(r"^([A-Za-z0-9_-]+)<<(.+)$", line)
        if heredoc:
            name, delimiter = heredoc.group(1), heredoc.group(2)
            i += 1
            chunks: list[str] = []
            while i < len(lines) and lines[i] != delimiter:
                chunks.append(lines[i])
                i += 1
            outputs[name] = "\n".join(chunks)
            i += 1
            continue
        if "=" in line:
            name, _, value = line.partition("=")
            outputs[name] = value
        i += 1
    return outputs


def _load_check_runs(directory: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    if not directory.is_dir():
        return runs
    for path in sorted(directory.glob("*.json")):
        runs.append(json.loads(path.read_text(encoding="utf-8")))
    return runs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-output", type=Path, required=True)
    parser.add_argument("--check-runs-dir", type=Path, required=True)
    parser.add_argument(
        "--expect-outcome",
        default="passed",
        help="Expected RunOutcome value when result is structured JSON (default: passed)",
    )
    parser.add_argument(
        "--require-check-runs",
        action="store_true",
        help="Require at least the mergecraft completion check-run",
    )
    args = parser.parse_args()

    if not args.github_output.is_file():
        print(f"FAIL: GITHUB_OUTPUT missing: {args.github_output}", file=sys.stderr)
        return 1

    outputs = _parse_github_output(args.github_output)
    raw_result = outputs.get("result")
    if raw_result is None or raw_result == "":
        print("FAIL: result output missing from GITHUB_OUTPUT", file=sys.stderr)
        print(f"outputs keys: {sorted(outputs)}", file=sys.stderr)
        return 1

    # Successful runs write the agent text output; failures write structured JSON
    # with outcome + error.code. Accept either, but prefer structured when present.
    try:
        parsed: Any = json.loads(raw_result)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict) and "outcome" in parsed:
        outcome = parsed.get("outcome")
        if outcome != args.expect_outcome:
            print(
                f"FAIL: result.outcome={outcome!r}, expected {args.expect_outcome!r}",
                file=sys.stderr,
            )
            print(raw_result, file=sys.stderr)
            return 1
        print(f"OK: structured result outcome={outcome}")
    else:
        if "E2E review complete" not in raw_result and args.expect_outcome == "passed":
            print(
                f"FAIL: unexpected result text for passed run: {raw_result!r}",
                file=sys.stderr,
            )
            return 1
        print(f"OK: result text present ({len(raw_result)} chars)")

    runs = _load_check_runs(args.check_runs_dir)
    if args.require_check_runs:
        if not runs:
            print(f"FAIL: no check-runs recorded under {args.check_runs_dir}", file=sys.stderr)
            return 1
        bodies = [r.get("body") or {} for r in runs]
        names = {str(b.get("name")) for b in bodies}
        if "mergecraft" not in names:
            print(f"FAIL: completion check-run missing; got names={sorted(names)}", file=sys.stderr)
            return 1
        for body in bodies:
            if body.get("name") != "mergecraft":
                continue
            required = {"name", "head_sha", "status", "conclusion", "output"}
            missing = required - set(body)
            if missing:
                print(f"FAIL: mergecraft check-run missing keys: {sorted(missing)}", file=sys.stderr)
                return 1
            if body.get("status") != "completed":
                print(f"FAIL: mergecraft status={body.get('status')!r}", file=sys.stderr)
                return 1
            output = body.get("output") or {}
            if not isinstance(output, dict) or "title" not in output or "summary" not in output:
                print("FAIL: mergecraft check-run output missing title/summary", file=sys.stderr)
                return 1
            print(
                f"OK: check-run shape name=mergecraft "
                f"conclusion={body.get('conclusion')!r} head_sha={str(body.get('head_sha'))[:7]}"
            )
        print(f"OK: recorded {len(runs)} check-run(s): {sorted(names)}")
    else:
        print(f"OK: check-runs dir has {len(runs)} file(s) (not required)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
