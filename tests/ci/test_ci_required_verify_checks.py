"""Required Verify check names stay aligned with branch protection."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from tests.ci.workflow_support import REPO_ROOT, read_text

# Frozen from ruleset ``require-ci-on-main`` (2026-10-31); update when branch
# protection changes — optional live check below catches drift when ``gh`` works.
_EXPECTED = frozenset(
    {
        "Verify (static + build py3.11)",
        "Verify (static + build py3.14)",
        "Verify (tests py3.11 1/2)",
        "Verify (tests py3.11 2/2)",
        "Verify (tests py3.14 1/2)",
        "Verify (tests py3.14 2/2)",
        "Verify (security audit py3.11)",
        "Verify (security audit py3.14)",
        "Verify (coverage gate py3.14)",
    }
)


def _listed_checks() -> set[str]:
    return {
        line.strip()
        for line in read_text("scripts/ci_required_verify_checks.txt").splitlines()
        if line.strip() and not line.startswith("#")
    }


def test_required_verify_checks_file_matches_frozen_ruleset() -> None:
    listed = _listed_checks()
    assert listed == _EXPECTED


def test_mergecraft_wait_script_uses_required_list() -> None:
    workflow = read_text(".github/workflows/mergecraft.yml")
    assert "ci_required_verify_checks.txt" in workflow


@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true",
    reason="GITHUB_TOKEN on PR runners cannot read organization rulesets",
)
def test_required_verify_checks_file_matches_live_ruleset() -> None:
    result = subprocess.run(
        [
            "gh",
            "api",
            "repos/alexhawat/mergeCraft/rulesets/21652574",
            "--jq",
            '.rules[] | select(.type=="required_status_checks") | .parameters.required_status_checks[].context',
        ],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        pytest.skip(f"gh rulesets API unavailable: {result.stderr.strip()}")
    ruleset = {line.strip() for line in result.stdout.splitlines() if line.strip()}
    listed = _listed_checks()
    assert listed == ruleset, json.dumps(
        {"listed_only": sorted(listed - ruleset), "ruleset_only": sorted(ruleset - listed)},
        indent=2,
    )
