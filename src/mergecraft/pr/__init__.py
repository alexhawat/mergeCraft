"""PR utilities — describe, suggestions, TODO scan, effort band, labels (DG8).

Wired through ``mergecraft describe`` (#351). Suggestions stay output-only (D13).
"""

from __future__ import annotations

from mergecraft.pr.describe import DescribeOutput, build_describe_output
from mergecraft.pr.effort_band import classify_effort_band
from mergecraft.pr.label_suggestions import suggest_labels
from mergecraft.pr.suggestions import generate_pr_suggestions
from mergecraft.pr.todo_detection import TodoFinding, scan_todo_additions

__all__ = [
    "DescribeOutput",
    "TodoFinding",
    "build_describe_output",
    "classify_effort_band",
    "generate_pr_suggestions",
    "scan_todo_additions",
    "suggest_labels",
]
