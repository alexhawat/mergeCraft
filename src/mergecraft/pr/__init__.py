"""PR utilities — describe, suggestions, TODO scan, effort band, labels (DG8).

Library surfaces extracted in DG8.2 for unit testing.  Wiring into the review
dispatch path (``select_mode``, MCP tools, Action comment handlers) is a DG7/DG8
follow-on — callers must not assume live integration from this package alone.
"""

from __future__ import annotations

from mergecraft.pr.describe import DescribeOutput, build_describe_output
from mergecraft.pr.effort_band import EffortBandResult, classify_effort_band
from mergecraft.pr.label_suggestions import LabelSuggestionsResult, suggest_labels
from mergecraft.pr.suggestions import PrSuggestionsResult, generate_pr_suggestions
from mergecraft.pr.todo_detection import TodoFinding, scan_todo_additions

__all__ = [
    "DescribeOutput",
    "EffortBandResult",
    "LabelSuggestionsResult",
    "PrSuggestionsResult",
    "TodoFinding",
    "build_describe_output",
    "classify_effort_band",
    "generate_pr_suggestions",
    "scan_todo_additions",
    "suggest_labels",
]
