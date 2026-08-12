"""Mutation test for the action-mapping policy table (WD-T evidence bar).

Per Batch C's protocol: flip each policy's mapping in turn, count how
many tests fail. If a mutation breaks zero tests, that branch is a
tautology — the test must be fixed before opening the PR.

This is an evidence-gathering script, not a test. It exits 0 unless the
mutation reports a zero-test branch.

Usage:
    env -u VIRTUAL_ENV uv run python scripts/mutation_test_policy.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE_POLICY = REPO / "src" / "mergecraft" / "evidence" / "gate_policy.py"

# Each mutation: (rule, replacement_action, expected_test_substring)
MUTATIONS = [
    ("schema_failure", "GateAction.REQUEST_CHANGES", "test_policy_schema_failure_maps_to_block"),
    (
        "changed-unread-file",
        "GateAction.BLOCK",
        "test_policy_changed_unread_file_maps_to_request_changes",
    ),
    (
        "low_risk_passing",
        "GateAction.BLOCK",
        "test_policy_low_risk_passing_maps_to_auto_merge",
    ),
    (
        "tool_loop",
        "GateAction.BLOCK",
        "test_policy_tool_loop_maps_to_require_more_tests",
    ),
    (
        "high_risk_migration",
        "GateAction.BLOCK",
        "test_policy_high_risk_migration_maps_to_require_human_review",
    ),
]


def _run_pytest(args: list[str]) -> tuple[int, str]:
    cmd = ["uv", "run", "pytest", *args, "--tb=no", "-q"]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    original = GATE_POLICY.read_text(encoding="utf-8")
    results: list[tuple[str, int, int]] = []  # (rule, failing, passed_in_suite)
    try:
        for rule, replacement, _expected in MUTATIONS:
            mutated = original.replace(
                f'"{rule}": GateAction.', f'"{rule}": {replacement} # MUTATED', 1
            )
            if mutated == original:
                print(f"FAIL: could not locate {rule!r} mapping in gate_policy.py")
                return 1
            GATE_POLICY.write_text(mutated, encoding="utf-8")
            _code, output = _run_pytest(["tests/evidence/test_gate_actions.py"])
            # Parse failing count from output
            failing = 0
            passed = 0
            for line in output.splitlines():
                if " failed" in line and " passed" in line:
                    parts = line.split(",")
                    for p in parts:
                        if " failed" in p:
                            failing = int(p.strip().split()[0])
                        elif " passed" in p:
                            passed = int(p.strip().split()[0])
                elif " failed" in line and "passed" not in line:
                    failing = int(line.strip().split()[0])
                elif " passed" in line and "failed" not in line:
                    passed = int(line.strip().split()[0])
            results.append((rule, failing, passed))
            print(f"mutation {rule} -> {replacement}: {failing} failed, {passed} passed")
        # Restore
        GATE_POLICY.write_text(original, encoding="utf-8")
    finally:
        # Always restore — even on exception — so we leave the file intact
        GATE_POLICY.write_text(original, encoding="utf-8")

    # Per-rule evidence bar: a mutation must break >=1 test. Zero
    # failures means the test for that rule is a tautology.
    zero_break: list[str] = []
    for rule, failing, _passed in results:
        if failing == 0:
            zero_break.append(rule)
    if zero_break:
        print(f"\nFAIL: zero-test branches: {zero_break} — those tests prove nothing")
        return 1
    print("\nAll five mutations broke at least one test. Action mapping is covered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
