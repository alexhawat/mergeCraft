"""Usage measurements from attributable, published mergeCraft review records."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER, REVIEW_BODY_MARKER
from mergecraft.review.authorship import is_mergecraft_authored

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext

_MAX_HISTORY_PULLS = 50
_MAX_REVIEWS_PER_PULL = 100
_MAX_BODIES = 200
_BODY_BATCH = 25
_HISTORY_QUERY = """
query MergecraftBudgetHistory($owner: String!, $repo: String!, $publisher: String!,
                             $pulls: Int!, $reviews: Int!) {
  repository(owner: $owner, name: $repo) {
    pullRequests(first: $pulls, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage }
      nodes {
        reviews(last: $reviews, author: $publisher,
                states: [APPROVED, CHANGES_REQUESTED, COMMENTED, DISMISSED]) {
          pageInfo { hasPreviousPage }
          nodes { id submittedAt }
        }
      }
    }
  }
}
"""
_BODY_QUERY = """
query MergecraftBudgetReviewBodies($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on PullRequestReview { id author { login } body }
  }
}
"""
_RECORD_HEADING = f"{DETERMINISTIC_RECORD_MARKER}\n### mergeCraft run record\n\n"
_RUN_ATTEMPT = re.compile(
    r"<!-- mergecraft-record-attempt: ([1-9][0-9]{0,19}):([1-9][0-9]{0,9}) -->"
)
_TOKEN_NUMBER = r"[0-9][0-9,]{0,25}"
_TOKEN_LINE = re.compile(
    rf"({_TOKEN_NUMBER}) input / ({_TOKEN_NUMBER}) output"
    rf"(?: / ({_TOKEN_NUMBER}) context expansion)?"
    r"(?: used \(target [0-9,]+, ceiling [0-9,]+\)(?:; .*)?)?"
)
_COST_LINE = re.compile(r"\$([0-9]{1,12}\.[0-9]{4})(?: \((?!partial:).+\))?")
_TIMING = re.compile(r"(setup|agent) (<0\.1|[0-9]{1,8}(?:\.[0-9]+)?)s")
_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:+-]{0,127}")
_OUTCOMES = {"`passed`", "`failed`", "`inconclusive`"}
_PRE_MERGE_HEADING = "\n### Pre-merge checks\n"
_HEADER_FIELD = re.compile(r"- \*\*([^*]+):\*\* (.+)")
_HEADER_ORDER = {
    name: index
    for index, name in enumerate(
        (
            "Outcome",
            "Verdict diagnostic",
            "Decision",
            "Change",
            "Reviewed files",
            "Blast radius",
            "Coverage",
            "Provider",
            "Requested model",
            "Model fallback",
            "Model",
            "Attempts",
            "Tokens",
            "Recorded reviewer model cost",
            "Review cost",
            "Agent stall",
            "LLM review time",
            "Run",
            "Reviewed SHA",
            "Action pin",
            "Image source",
            "Pin lag",
            "Review skills (injected)",
            "Review MCP",
            "Publication path",
            "Inline recovery",
            "Publication recovery",
            "Body truncated",
        )
    )
}


@dataclass(frozen=True, slots=True)
class RunUsageSample:
    """One review's recorded measurements and contributors."""

    tokens: int | None
    cost_usd: float | None
    wall_seconds: float | None
    model: str | None = None
    setup_seconds: float | None = None
    agent_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ReviewHistory:
    """A newest-first sample window and whether the available search hit a bound."""

    samples: list[RunUsageSample]
    limited: bool = False


def make_usage_sample(
    *,
    tokens: int | None,
    cost_usd: float | None,
    setup: float | None,
    agent: float | None,
    model: str | None,
) -> RunUsageSample:
    """Count the top-level phases, whose durations do not overlap."""
    wall = setup + agent if setup is not None and agent is not None else None
    return RunUsageSample(
        tokens,
        cost_usd,
        wall,
        model
        if model is not None and _MODEL_NAME.fullmatch(model) and redact_secrets(model) == model
        else None,
        setup,
        agent,
    )


def _record_fields(record: str) -> dict[str, str] | None:
    """Recognize the ordered legacy header and discard injected or duplicate rows."""
    header, separator, _ = record.removeprefix(_RECORD_HEADING).partition(_PRE_MERGE_HEADING)
    if not separator or record.count(_PRE_MERGE_HEADING) != 1:
        return None
    fields: dict[str, str] = {}
    last = -1
    for line in header.rstrip("\n").splitlines():
        if line.startswith("- ⏱ LLM review time: "):
            name, value = "LLM review time", line
        elif match := _HEADER_FIELD.fullmatch(line):
            name, value = match.groups()
        else:
            return None
        if name == "Cost":
            name = "Recorded reviewer model cost"
        if name != "Risk":
            position = _HEADER_ORDER.get(name, -1)
            if position <= last:
                return None
            last = position
        if name in fields:
            return None
        fields[name] = value
    return fields


def _usage_from_review(
    review: dict[str, Any], publishers: frozenset[str]
) -> tuple[tuple[int, int], RunUsageSample] | None:
    body = review.get("body")
    if not isinstance(body, str) or not is_mergecraft_authored(
        {"user": review.get("author"), "body": body}, publishers=publishers
    ):
        return None

    record, separator, _ = body.partition(f"\n{REVIEW_BODY_MARKER}")
    if (
        not separator
        or not record.startswith(_RECORD_HEADING)
        or body.count(REVIEW_BODY_MARKER) != 1
        or body.count(DETERMINISTIC_RECORD_MARKER) != 1
        or record.count("\n<!-- mergecraft-record-attempt:") != 1
    ):
        return None
    attempt = _RUN_ATTEMPT.fullmatch(record.rstrip().split("\n")[-1])
    fields = _record_fields(record)
    if (
        attempt is None
        or fields is None
        or fields.get("Outcome") not in _OUTCOMES
        or fields.get("Publication path") != "`publish_pull_request_review`"
        or "Model" not in fields
        or "Recorded reviewer model cost" not in fields
    ):
        return None

    tokens = _TOKEN_LINE.fullmatch(fields.get("Tokens", ""))
    cost = _COST_LINE.fullmatch(fields["Recorded reviewer model cost"])
    _, _, timing = fields.get("Review cost", "").partition(" · phases: ")
    phases = {}
    for bit in timing.split(", "):
        if match := _TIMING.fullmatch(bit):
            phase, seconds = match.groups()
            if phase in phases:
                return None
            phases[phase] = 0.05 if seconds == "<0.1" else float(seconds)
    sample = make_usage_sample(
        tokens=sum(int(part.replace(",", "")) for part in tokens.groups() if part)
        if tokens
        else None,
        cost_usd=float(cost[1]) if cost else None,
        setup=phases.get("setup"),
        agent=phases.get("agent"),
        model=fields["Model"].strip("`"),
    )
    if sample.tokens is None and sample.cost_usd is None and sample.wall_seconds is None:
        return None
    return (int(attempt[1]), int(attempt[2])), sample


async def load_review_history(
    ctx: ToolContext,
    *,
    publishers: frozenset[str],
    window_size: int,
    current_attempt: tuple[int, int] | None,
) -> ReviewHistory:
    """Load a bounded repository history, newest first with duplicate attempts removed."""
    if window_size <= 0:
        return ReviewHistory([])
    repo = ctx.repo
    candidates: dict[str, datetime] = {}
    limited = False
    for publisher in sorted(publishers):
        data = await ctx.scm.graphql(
            _HISTORY_QUERY,
            {
                "owner": repo.owner,
                "repo": repo.name,
                "publisher": publisher,
                "pulls": min(max(window_size * 2, 20), _MAX_HISTORY_PULLS),
                "reviews": min(window_size + 1, _MAX_REVIEWS_PER_PULL),
            },
        )
        pull_connection = data["repository"]["pullRequests"]
        pulls = pull_connection["nodes"]
        if not isinstance(pulls, list):
            raise ValueError("invalid pull request history")
        limited |= pull_connection["pageInfo"]["hasNextPage"] is True
        for pull in pulls:
            if not isinstance(pull, dict):
                continue
            connection = pull.get("reviews")
            if not isinstance(connection, dict) or not isinstance(connection.get("nodes"), list):
                raise ValueError("invalid review history")
            limited |= connection["pageInfo"]["hasPreviousPage"] is True
            for review in connection["nodes"]:
                if not isinstance(review, dict) or not isinstance(review.get("submittedAt"), str):
                    continue
                node_id = review.get("id")
                if not isinstance(node_id, str) or not node_id:
                    continue
                try:
                    timestamp = datetime.fromisoformat(review["submittedAt"])
                except ValueError:
                    continue
                if timestamp.utcoffset() is not None:
                    candidates[node_id] = timestamp
    ordered = sorted(candidates, key=lambda node_id: (candidates[node_id], node_id), reverse=True)
    limited |= len(ordered) > _MAX_BODIES
    ordered = ordered[:_MAX_BODIES]
    attempts = {current_attempt}
    samples: list[RunUsageSample] = []
    for start in range(0, len(ordered), _BODY_BATCH):
        ids = ordered[start : start + _BODY_BATCH]
        data = await ctx.scm.graphql(_BODY_QUERY, {"ids": ids})
        nodes = data["nodes"]
        if not isinstance(nodes, list):
            raise ValueError("invalid review bodies")
        bodies = {
            node["id"]: node
            for node in nodes
            if isinstance(node, dict) and isinstance(node.get("id"), str)
        }
        for node_id in ids:
            review = bodies.get(node_id)
            usage = _usage_from_review(review, publishers) if review is not None else None
            if usage is None:
                continue
            attempt, sample = usage
            if attempt in attempts:
                continue
            attempts.add(attempt)
            samples.append(sample)
            if len(samples) == window_size:
                return ReviewHistory(samples, limited)
    return ReviewHistory(samples, limited)
