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


def validate_outputs(
    outputs: dict[str, str],
    runs: list[dict[str, Any]],
    publications: list[dict[str, Any]],
    *,
    expected_outcome: str,
    expected_sha: str,
    require_checks: bool,
) -> None:
    """Reject prose, incomplete reviews, wrong revisions, and nonpassing checks."""
    result = json.loads(outputs.get("result", ""))
    if not isinstance(result, dict) or result.get("outcome") != expected_outcome:
        raise ValueError("result must be structured JSON with the expected outcome")
    if expected_outcome != "passed":
        if not isinstance(result.get("error"), dict) or not result["error"].get("code"):
            raise ValueError("failed result must identify its error code")
        if any((run.get("body") or {}).get("conclusion") == "success" for run in runs):
            raise ValueError("a refused fixture must not publish a successful check")
        if any(
            row.get("method") == "POST" and row.get("path", "").endswith("/reviews")
            for row in publications
        ):
            raise ValueError("a refused fixture must not publish a formal review")
        return
    if result.get("head_sha") != expected_sha or not result.get("terminal_id"):
        raise ValueError("result must identify the reviewed head and accepted terminal submission")
    packet = json.loads(outputs.get("evidence_packet", ""))
    if (
        packet.get("reviewed_head_sha") != expected_sha
        or packet.get("agent_terminal_verdict") != "approve"
    ):
        raise ValueError("packet must contain an accepted approval for the fixture head")
    if (packet.get("decision") or {}).get("verdict") != "success":
        raise ValueError("packet must record a successful evidence decision")
    calls = (packet.get("trajectory") or {}).get("tool_calls") or []
    successful = {call.get("tool") for call in calls if call.get("ok") is True}
    required = {"select_mode", "checkout_pr", "git", "run_analyzers", "submit_review_verdict"}
    if not required <= successful:
        raise ValueError("packet is missing successful MCP review protocol calls")
    if outputs.get("verdict_diagnostic") != "approved":
        raise ValueError("review reported a terminal verdict diagnostic")
    if require_checks:
        for name in ("mergecraft", "mergecraft-approval"):
            bodies = [
                run.get("body") or {} for run in runs if (run.get("body") or {}).get("name") == name
            ]
            completed = [body for body in bodies if body.get("status") == "completed"]
            if not completed:
                raise ValueError(f"completed {name} check missing")
            for body in completed:
                if body.get("head_sha") != expected_sha or body.get("conclusion") != "success":
                    raise ValueError(f"{name} must succeed on the reviewed head")
                if not (body.get("output") or {}).get("summary"):
                    raise ValueError(f"{name} must explain its result")
        reviews = [
            row["body"]
            for row in publications
            if row.get("method") == "POST" and row.get("path", "").endswith("/reviews")
        ]
        if not any(
            row.get("commit_id") == expected_sha and row.get("event") == "APPROVE"
            for row in reviews
        ):
            raise ValueError("no formal review was published on the fixture head")
        if any(row.get("commit_id") != expected_sha for row in reviews):
            raise ValueError("a formal review was published on another revision")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--github-output", type=Path, required=True)
    parser.add_argument("--check-runs-dir", type=Path, required=True)
    parser.add_argument("--expect-outcome", default="passed")
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument("--require-check-runs", action="store_true")
    args = parser.parse_args()
    try:
        validate_outputs(
            _parse_github_output(args.github_output),
            _load_check_runs(args.check_runs_dir),
            _load_check_runs(args.check_runs_dir / "requests"),
            expected_outcome=args.expect_outcome,
            expected_sha=args.expected_head_sha,
            require_checks=args.require_check_runs,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"OK: {args.expect_outcome} with verified review and publication semantics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
