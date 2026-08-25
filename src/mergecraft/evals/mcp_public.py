"""Offline public MCP tool-selection eval scorer (D17 / MP6).

Fixture prompts live under ``evals/mcp-public/cases.json``. The scorer is
heuristic and deterministic — no live LLM — so ``make test`` can pin the
public catalog's tool-selection contract without provider credentials.

Exports:
    PUBLIC_MCP_EVAL_CASES_PATH: Path to the fixture corpus JSON.
    RUNTIME_WRITE_TOOL_NAMES: Runtime mutating tools the public profile must never select.
    McpPublicEvalCase: One labeled offline eval row.
    load_mcp_public_cases: Load eval cases from the corpus file.
    select_public_tool: Offline heuristic tool selection for a user prompt.
    score_mcp_public_case: Return whether one case passes the offline selector.
    score_mcp_public_corpus: Score every case in the corpus.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final, TypedDict

from mergecraft.mcp.public import PUBLIC_TOOL_NAMES

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
PUBLIC_MCP_EVAL_CASES_PATH: Final[Path] = _REPO_ROOT / "evals" / "mcp-public" / "cases.json"

RUNTIME_WRITE_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "push_branch",
        "commit_changes",
        "create_pull_request",
    }
)

_MC_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"\bMC-[A-Za-z0-9_-]+\b", re.IGNORECASE)
_REVIEW_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(?:rev|review)[-_][\w-]+\b",
    re.IGNORECASE,
)

_WRITE_INTENT_NEEDLES: Final[tuple[str, ...]] = (
    "commit",
    "push",
    "open a pr",
    "open pr",
    "create pull request",
    "apply fix",
    "merge this",
)

_RELOAD_NEEDLES: Final[tuple[str, ...]] = (
    "reload review",
    "load review",
    "get review",
    "fetch review",
    "summarize the outcome",
)

_REVIEW_CHANGE_NEEDLES: Final[tuple[str, ...]] = (
    "review this",
    "review the",
    "review my",
    "audit",
    "what needs fixing",
    "run a review",
)


class McpPublicEvalCase(TypedDict, total=False):
    """One labeled offline public MCP tool-selection case."""

    id: str
    prompt: str
    expected_tool: str | None
    forbidden_tools: list[str]


def load_mcp_public_cases(*, cases_path: Path | None = None) -> list[McpPublicEvalCase]:
    """Load the public MCP eval corpus from disk."""
    path = cases_path or PUBLIC_MCP_EVAL_CASES_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        msg = f"{path} must contain a JSON list"
        raise ValueError(msg)
    return data


def _normalized(prompt: str) -> str:
    return " ".join(prompt.lower().split())


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _has_write_intent(normalized: str) -> bool:
    return _contains_any(normalized, _WRITE_INTENT_NEEDLES)


def select_public_tool(prompt: str) -> str | None:
    """Choose the best public MCP tool for an offline fixture prompt."""
    if not prompt.strip():
        return None

    normalized = _normalized(prompt)
    if _has_write_intent(normalized):
        return None

    if _MC_ID_PATTERN.search(prompt):
        if _contains_any(normalized, ("explain", "why", "mean")):
            return "explain_finding"
        return "inspect_finding"

    if _contains_any(normalized, _RELOAD_NEEDLES):
        return "get_review"
    if _REVIEW_ID_PATTERN.search(prompt) and "review" in normalized:
        return "get_review"

    if _contains_any(
        normalized,
        (
            "capabilities",
            "allowed vs forbidden",
            "allowed actions",
            "forbidden actions",
            "what actions",
        ),
    ):
        return "get_capabilities"

    if _contains_any(normalized, ("policy", "gate rule", "trust tier")):
        return "get_policy"

    if _contains_any(normalized, _REVIEW_CHANGE_NEEDLES) or (
        "review" in normalized and "change" in normalized
    ):
        return "review_change"

    return None


def score_mcp_public_case(case: McpPublicEvalCase) -> bool:
    """Return whether ``select_public_tool`` satisfies one corpus case."""
    chosen = select_public_tool(case.get("prompt", ""))
    expected = case.get("expected_tool")
    forbidden = frozenset(case.get("forbidden_tools") or ())

    if forbidden:
        if chosen is not None and chosen not in PUBLIC_TOOL_NAMES:
            return False
        return chosen is None or chosen not in forbidden

    if expected is None:
        return chosen is None

    if expected in {"inspect_finding", "explain_finding"}:
        return chosen in {"inspect_finding", "explain_finding"}

    return chosen == expected


def score_mcp_public_corpus(
    *,
    cases_path: Path | None = None,
) -> tuple[int, int, list[str]]:
    """Score the full corpus; returns ``(passed, total, failed_case_ids)``."""
    cases = load_mcp_public_cases(cases_path=cases_path)
    failed: list[str] = []
    passed = 0
    for case in cases:
        case_id = case.get("id", "<unknown>")
        if score_mcp_public_case(case):
            passed += 1
        else:
            failed.append(str(case_id))
    return passed, len(cases), failed


__all__ = [
    "PUBLIC_MCP_EVAL_CASES_PATH",
    "RUNTIME_WRITE_TOOL_NAMES",
    "McpPublicEvalCase",
    "load_mcp_public_cases",
    "score_mcp_public_case",
    "score_mcp_public_corpus",
    "select_public_tool",
]
