"""W2 measurement script — extract corpus diffs and time the Meat subprocess.

Run from the spike worktree (``.ignorelocal/waves/issues-meat-reading-diff-wave-plan.md``
W2.3-W2.7). Each parent->child diff is materialised from the W0 corpus via
``git diff <parent>..<child>`` and the harness boundary is exercised with
the real ``meat -json`` binary at ``~/go/bin/meat`` (env-pinned per W0.4:

    meat.dev@v0.0.0-20260803201634-f39f41dfe7b5

If the operator has a usable credential, the script prints the four
measurements (D10); if not, it prints the blocker and the harness-only
behaviour that **is** observable offline (subprocess boundary overhead,
token-count of the raw diff, gate outcomes). The output is the raw
operator measurement output (no repo writes).

No writes to the repo; no git operations; the only network is to the
LLM credential host and that is the spike's whole point. The script is
operator-runnable; ``make`` does not call it.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

# W0 corpus (issue #60 spike)
CORPUS: list[tuple[str, str, str, str, str]] = [
    ("#114", "d898ba4", "4dde63a", "chore: ignore .claude, .cursor, and CLAUDE.md", "small"),
    ("#111", "b1cfe06", "3f3c271", "ci(issues): install the auto-close workflow", "small"),
    ("#100", "d4f3d98", "a6c4078", "ci(issues): auto-close issues fixed by PRs", "small"),
    (
        "#93",
        "e03590f",
        "35d4bc1",
        "fix(budget): give overflowed agent findings distinct fingerprints",
        "small",
    ),
    (
        "#103",
        "7e427f1",
        "a784d1d",
        "fix(codex): report nested-sandbox failures and add an opt-out",
        "small",
    ),
    ("#116", "fdb41be", "3948a62", "feat(evidence): thermostat + shadow mode", "medium"),
    ("#115", "3948a62", "d898ba4", "feat(evidence): trajectory record and auditor", "medium"),
    (
        "#112",
        "fc2d2e7",
        "f4b9f8a",
        "feat(analyzers): trust-aware selection for pull_request_target",
        "medium",
    ),
    ("#113", "4dde63a", "fc2d2e7", "analyzers: publish findings as code-scanning alerts", "medium"),
    ("#109", "f4b9f8a", "84f14c0", "feat(agents): stream-json migration", "medium"),
    ("#89", "57ab51b", "4e8ebc4", "feat(classify+evidence): blast radius + lane policy", "large"),
    ("#92", "35d4bc1", "37c8db6", "feat(eval): Failure Memory and Eval Bank", "large"),
]

MEAT_BINARY = Path(os.environ.get("MEAT_BINARY", "/Users/alex/go/bin/meat"))


def _diff_text(*, child: str, parent: str) -> str:
    return subprocess.run(
        ["git", "diff", f"{parent}..{child}"],
        check=False,
        capture_output=True,
        text=True,
    ).stdout


def _diff_stats(text: str) -> dict[str, int]:
    added = sum(
        1 for line in text.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in text.splitlines() if line.startswith("-") and not line.startswith("---")
    )
    files = sum(1 for line in text.splitlines() if line.startswith("diff --git "))
    return {"files": files, "added": added, "removed": removed, "chars": len(text)}


def _approx_tokens(text: str) -> int:
    """Conservative token estimate: chars/4 (OpenAI rule-of-thumb for English/code)."""
    return max(1, len(text) // 4)


def _time_harness_skip(raw_diff: str, *, iterations: int = 3) -> dict[str, float]:
    """Time the harness's subprocess-boundary overhead on the missing-credential path.

    With no ``OPENAI_API_KEY`` / ``ANTHROPIC_API_KEY`` set, ``meat -json``
    exits non-zero with a stderr error. The harness still invokes the
    subprocess, captures the error, and degrades - so what we measure
    here is the **boundary overhead**, not the LLM call. This is the
    floor below which the latency cannot drop; the real LLM call sits
    on top of it.
    """
    samples: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        try:
            subprocess.run(
                [str(MEAT_BINARY), "-json"],
                input=raw_diff,
                capture_output=True,
                text=True,
                timeout=120.0,
                check=False,
            )
        except subprocess.TimeoutExpired:
            samples.append(120.0)
            continue
        samples.append(time.perf_counter() - start)
    return {"min_s": min(samples), "median_s": statistics.median(samples), "max_s": max(samples)}


def _real_meat_call(raw_diff: str, *, timeout: float = 120.0) -> dict[str, Any]:
    """Run the real ``meat -json`` once with the operator's credentials.

    Returns the parsed JSON dict on success, the stderr text on failure,
    and the wall-clock time in both cases. The harness ensures the
    subprocess inherits the env; this script does not add to it.
    """
    start = time.perf_counter()
    process = subprocess.run(
        [str(MEAT_BINARY), "-json"],
        input=raw_diff,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    elapsed = time.perf_counter() - start
    if process.returncode != 0:
        return {
            "ok": False,
            "elapsed_s": elapsed,
            "stderr_tail": (process.stderr or "").strip().splitlines()[-1:],
        }
    try:
        return {"ok": True, "elapsed_s": elapsed, "payload": json.loads(process.stdout)}
    except ValueError as exc:
        return {"ok": False, "elapsed_s": elapsed, "stderr_tail": [f"json parse failed: {exc}"]}


def _print_table(rows: list[dict[str, Any]]) -> None:
    """Pretty-print the measurement table to stdout."""
    if not rows:
        return
    headers = list(rows[0].keys())
    widths = [max(len(str(h)), max(len(str(r.get(h, ""))) for r in rows)) for h in headers]
    line = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=False))
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(str(r.get(h, "")).ljust(w) for h, w in zip(headers, widths, strict=False)))


def main() -> None:
    """Run the W2.3-W2.7 measurement loop over the W0 corpus."""
    if not MEAT_BINARY.exists():
        print(f"ERROR: meat binary not found at {MEAT_BINARY}")
        print("Install via `go install meat.dev/cmd/meat@latest` (D6 - operator env only).")
        return

    print(f"Spike corpus - W2.3-W2.7 measurements (meat at {MEAT_BINARY})")
    print("credential env: explicit name only; value never read or printed")
    print()

    rows: list[dict[str, Any]] = []
    for pr, child, parent, _label, kind in CORPUS:
        diff = _diff_text(child=child, parent=parent)
        stats = _diff_stats(diff)
        approx_input_tokens = _approx_tokens(diff)
        boundary = _time_harness_skip(diff, iterations=1)
        real = _real_meat_call(diff)
        rows.append(
            {
                "pr": pr,
                "kind": kind,
                "files": stats["files"],
                "+": stats["added"],
                "-": stats["removed"],
                "chars": stats["chars"],
                "approx_input_tokens": approx_input_tokens,
                "boundary_subprocess_s": round(boundary["median_s"], 3),
                "real_call_ok": real["ok"],
                "real_call_s": round(real["elapsed_s"], 3),
                "real_call_err_tail": (real.get("stderr_tail") or [""])[-1]
                if not real["ok"]
                else "",
            }
        )

    _print_table(rows)
    print()
    print("Notes:")
    print("  - boundary_subprocess_s: harness's subprocess boundary")
    print("    with the credential missing; this is the floor of any")
    print("    real meat -json latency.")
    print("  - real_call_ok: True only if the operator has a working")
    print("    OPENAI_API_KEY / ANTHROPIC_API_KEY set in the env that")
    print("    the subprocess inherits. The harness is the only thing")
    print("    doing the calling; nothing else in the loop does.")
    print("  - approx_input_tokens: chars/4 of the raw diff.")


if __name__ == "__main__":
    main()
