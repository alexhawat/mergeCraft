"""PR utilities — describe, suggestions, TODO scan, effort band, labels (DG8).

Wired through ``mergecraft describe`` (#351). Suggestions stay output-only (D13).
"""

from __future__ import annotations

from mergecraft.pr.describe import DescribeOutput, build_describe_output
from mergecraft.pr.effort_band import EffortBandResult, classify_effort_band
from mergecraft.pr.label_suggestions import LabelSuggestionsResult, suggest_labels
from mergecraft.pr.similar import (
    SimilarChange,
    SimilarIssue,
    find_similar_changes,
    find_similar_issues,
)
from mergecraft.pr.suggestions import PrSuggestionsResult, generate_pr_suggestions
from mergecraft.pr.todo_detection import TodoFinding, scan_todo_additions

__all__ = [
    "DescribeOutput",
    "EffortBandResult",
    "LabelSuggestionsResult",
    "PrSuggestionsResult",
    "SimilarChange",
    "SimilarIssue",
    "TodoFinding",
    "build_describe_output",
    "classify_effort_band",
    "find_similar_changes",
    "find_similar_issues",
    "generate_pr_suggestions",
    "scan_todo_additions",
    "suggest_labels",
]
