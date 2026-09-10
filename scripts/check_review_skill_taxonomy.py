#!/usr/bin/env python3
"""Drift gate: the code-review skill must name every live taxonomy constant (D8).

Reads expected values from :mod:`mergecraft.review_taxonomy` and
:mod:`mergecraft.findings.severity` at check time — never diffs
``REVIEW-CHECKS.md`` prose.
"""

from __future__ import annotations

import sys
from pathlib import Path

from mergecraft.evals.skill_taxonomy_gate import taxonomy_values_covered_by_skill

REPO = Path(__file__).resolve().parents[1]
DEFAULT_SKILL_ROOT = REPO / ".github" / "skills" / "code-review"


def main() -> int:
    """Exit 1 when any taxonomy value is missing from the skill tree."""
    skill_root = DEFAULT_SKILL_ROOT
    if not skill_root.is_dir():
        print(f"missing review skill directory: {skill_root}", file=sys.stderr)
        return 1
    coverage = taxonomy_values_covered_by_skill(skill_root=skill_root)
    if coverage.missing:
        print(
            "review-skill taxonomy drift: skill text is missing values from "
            "review_taxonomy.py / findings/severity.py:",
            file=sys.stderr,
        )
        for value in coverage.missing:
            print(f"  - {value}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
