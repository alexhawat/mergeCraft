"""Ledger marker stripping and row acceptance when reading review bodies back."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mergecraft.findings import ledger
from mergecraft.findings.lifecycle import LifecycleRecord
from mergecraft.mcp.review import merge_deterministic_preamble_into_review_body

_NOW = datetime(2026, 11, 10, 12, 0, 0, tzinfo=UTC)
_FP = "ab12cd34"
_OTHER_FP = "ef56ab78"


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _v2_marker(fingerprint: str, state: str, meta: dict[str, object]) -> str:
    encoded = quote(json.dumps(meta, separators=(",", ":"), sort_keys=True), safe="")
    return f"{ledger.LEDGER_MARKER_V2_PREFIX}{fingerprint}:{state}:{encoded} -->"


def _nested(inner: str, outer_prefix: str, outer_rest: str) -> str:
    """Split ``outer_prefix`` + ``outer_rest`` around ``inner``."""
    return f"{outer_prefix}{inner}{outer_rest}"


def _published_review_body(agent_body: str, records: list[LifecycleRecord]) -> str:
    """Build a review body through the same helpers the publish path uses."""
    with_preamble = merge_deterministic_preamble_into_review_body(
        agent_body=agent_body,
        deterministic_block=ledger.DETERMINISTIC_RECORD_MARKER + "\n- outcome: ok",
    )
    return ledger.merge_ledger_into_comment(with_preamble, records=records)


def _record(fingerprint: str, state: str, recorded_at: str) -> LifecycleRecord:
    return LifecycleRecord(
        fingerprint=fingerprint,
        state=state,  # type: ignore[arg-type]
        round_index=1,
        recorded_at=recorded_at,
        source="inline",
    )


# ── Fixed-point stripping ────────────────────────────────────────────────────


def test_nested_v2_marker_in_agent_prose_yields_no_ledger_row() -> None:
    inner = _v2_marker("00", "open", {"recorded_at": "2026-01-01T00:00:00Z"})
    meta = quote('{"recorded_at":"2026-01-01T00:00:00Z"}', safe="")
    prose = _nested(inner, "<!-- mergecraft-ledger:v2:", f"{_FP}:withdrawn:{meta} -->")

    body = _published_review_body(prose, [])

    assert ledger.FindingLedger.from_comment_body(body, now=_NOW).records() == []
    assert "mergecraft-ledger:" not in body


def test_nested_v1_marker_in_agent_prose_yields_no_ledger_row() -> None:
    inner = f"{ledger.LEDGER_MARKER_PREFIX}00:open -->"
    prose = _nested(inner, "<!-- mergecraft-ledger:v1:", f"{_FP}:withdrawn -->")

    body = _published_review_body(prose, [])

    assert ledger.FindingLedger.from_comment_body(body, now=_NOW).records() == []


def test_deeply_nested_marker_yields_no_ledger_row() -> None:
    marker = _v2_marker(_FP, "withdrawn", {"recorded_at": "2026-01-01T00:00:00Z"})
    prefix = ledger.LEDGER_MARKER_V2_PREFIX
    nested = marker
    for _ in range(5):
        nested = prefix + nested + marker[len(prefix) :]

    body = _published_review_body(nested, [])

    assert ledger.FindingLedger.from_comment_body(body, now=_NOW).records() == []


def test_unterminated_prefix_in_prose_does_not_absorb_the_real_rows() -> None:
    real = _record(_OTHER_FP, "open", _iso(_NOW - timedelta(days=1)))
    prose = f"see <!-- mergecraft-ledger:v2:{_FP}:withdrawn:%7B%7D"

    body = _published_review_body(prose, [real])

    parsed = ledger.FindingLedger.from_comment_body(body, now=_NOW).records()
    assert parsed == [real]


def test_nested_deterministic_record_marker_is_stripped_from_agent_prose() -> None:
    marker = ledger.DETERMINISTIC_RECORD_MARKER
    nested = marker[:10] + marker + marker[10:]

    cleaned = ledger._strip_deterministic_record_markers(f"prose {nested} more")

    assert marker not in cleaned
    assert ledger.REVIEW_BODY_MARKER not in cleaned


_FRAGMENTS = [
    ledger.LEDGER_MARKER_PREFIX,
    ledger.LEDGER_MARKER_V2_PREFIX,
    "<!-- mergecraft-ledger:",
    "<!-- ",
    "mergecraft-ledger:",
    "v1:",
    "v2:",
    _FP,
    ":",
    "open",
    "withdrawn",
    "%7B%22recorded_at%22%3A%222026-01-01T00%3A00%3A00Z%22%7D",
    "%7B%7D",
    " -->",
    "-->",
    ">",
    "\n",
    "text",
]

_bodies = st.lists(
    st.one_of(st.sampled_from(_FRAGMENTS), st.text(max_size=4)),
    max_size=40,
).map("".join)


@settings(max_examples=400, deadline=None)
@given(_bodies)
def test_stripping_never_leaves_a_parseable_marker(body: str) -> None:
    cleaned = ledger.merge_ledger_into_comment(body, records=[])

    assert ledger.FindingLedger.from_comment_body(cleaned, now=_NOW).records() == []
    assert ledger.merge_ledger_into_comment(cleaned, records=[]) == cleaned


@settings(max_examples=200, deadline=None)
@given(_bodies)
def test_merged_body_parses_back_to_exactly_the_written_rows(body: str) -> None:
    rows = [
        _record(_FP, "open", _iso(_NOW - timedelta(hours=2))),
        _record(_OTHER_FP, "deferred", _iso(_NOW - timedelta(hours=1))),
    ]

    merged = ledger.merge_ledger_into_comment(body, records=rows)

    assert ledger.FindingLedger.from_comment_body(merged, now=_NOW).records() == rows


# ── recorded_at bounds ───────────────────────────────────────────────────────


def test_row_with_recorded_at_beyond_clock_skew_is_rejected() -> None:
    body = _v2_marker(_FP, "withdrawn", {"recorded_at": _iso(_NOW + timedelta(hours=1))})

    assert ledger.FindingLedger.from_comment_body(body, now=_NOW).records() == []


def test_row_with_far_future_recorded_at_is_rejected() -> None:
    body = _v2_marker(_FP, "withdrawn", {"recorded_at": "9999-01-01T00:00:00Z"})

    assert ledger.FindingLedger.from_comment_body(body, now=_NOW).records() == []


def test_row_within_clock_skew_is_accepted() -> None:
    stamp = _iso(_NOW + timedelta(seconds=30))
    body = _v2_marker(_FP, "open", {"recorded_at": stamp})

    rows = ledger.FindingLedger.from_comment_body(body, now=_NOW).records()

    assert [row.recorded_at for row in rows] == [stamp]


def test_row_with_unparseable_recorded_at_is_rejected() -> None:
    body = _v2_marker(_FP, "withdrawn", {"recorded_at": "zzzz"})

    assert ledger.FindingLedger.from_comment_body(body, now=_NOW).records() == []


def test_row_without_recorded_at_is_still_accepted() -> None:
    body = _v2_marker(_FP, "open", {"round_index": 1})

    rows = ledger.FindingLedger.from_comment_body(body, now=_NOW).records()

    assert [(row.fingerprint, row.recorded_at) for row in rows] == [(_FP, None)]


@pytest.mark.asyncio
async def test_review_ledger_keeps_the_real_row_over_a_future_dated_one() -> None:
    real = _record(_FP, "open", "2026-08-20T10:00:00Z")
    future = _v2_marker(_FP, "withdrawn", {"recorded_at": "9999-01-01T00:00:00Z"})

    class _Scm:
        async def list_issue_comments(self, *_a: object, **_k: object) -> list[dict[str, object]]:
            return []

        async def list_reviews(self, *_a: object, **kwargs: object) -> list[dict[str, object]]:
            if int(kwargs["params"]["page"]) != 1:  # type: ignore[index]
                return []
            bot = {"login": "github-actions[bot]", "type": "Bot"}
            return [
                {"id": 1, "user": bot, "body": _published_review_body("", [real])},
                {
                    "id": 2,
                    "user": bot,
                    "body": f"{ledger.DETERMINISTIC_RECORD_MARKER}\n{future}\n",
                },
            ]

    found = await ledger.fetch_review_ledger(_Scm(), "acme", "demo", 7)  # type: ignore[arg-type]

    kept = found.get_record(_FP)
    assert kept is not None
    assert kept.state == "open"
    assert kept.recorded_at == "2026-08-20T10:00:00Z"


# ── Authorship of the run-bound progress comment ─────────────────────────────


def _ctx(tmp_path: Path, scm: Any) -> Any:
    from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.mcp.tool_state import ProgressComment, init_tool_state
    from mergecraft.modes import compute_modes
    from mergecraft.utils.github import GitHubClient

    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.progress_comment = ProgressComment(id="42", type="issue")
    state.finding_ledger_loaded = False
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        github=GitHubClient(token="test-token"),
        scm=scm,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user", "expected"),
    [
        ({"login": "github-actions[bot]", "type": "Bot"}, ["deferred"]),
        ({"login": "contributor", "type": "User"}, []),
        (None, []),
    ],
)
async def test_hydrate_reads_the_run_bound_comment_only_when_a_bot_wrote_it(
    tmp_path: Path, user: dict[str, str] | None, expected: list[str]
) -> None:
    body = ledger.merge_ledger_into_comment(
        "## mergeCraft progress\n",
        records=[_record(_FP, "deferred", "2026-08-20T10:00:00Z")],
    )

    class _Scm:
        async def get_issue_comment(self, *_a: object) -> dict[str, object]:
            comment: dict[str, object] = {"id": 42, "body": body}
            if user is not None:
                comment["user"] = user
            return comment

    hydrated = await ledger.hydrate_finding_ledger_from_progress_comment(_ctx(tmp_path, _Scm()))

    assert [row.state for row in hydrated.records()] == expected
