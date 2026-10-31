"""Required Verify check names stay aligned with branch protection."""

from __future__ import annotations

import json
import subprocess

from tests.ci.workflow_support import REPO_ROOT, read_text


def _ruleset_required_contexts() -> set[str]:
    result = subprocess.run(
        [
            "gh",
            "api",
            "repos/alexhawat/mergeCraft/rulesets/21652574",
            "--jq",
            '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context',
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def test_required_verify_checks_file_matches_ruleset() -> None:
    listed = {
        line.strip()
        for line in read_text("scripts/ci_required_verify_checks.txt").splitlines()
        if line.strip() and not line.startswith("#")
    }
    ruleset = _ruleset_required_contexts()
    assert listed == ruleset, json.dumps({"listed_only": sorted(listed - ruleset), "ruleset_only": sorted(ruleset - listed)}, indent=2)


def test_mergecraft_wait_script_uses_required_list() -> None:
    workflow = read_text(".github/workflows/mergecraft.yml")
    assert "ci_required_verify_checks.txt" in workflow
