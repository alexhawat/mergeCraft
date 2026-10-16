"""Changed-line coverage: the universe, the accounting, and what an incomplete one means.

A review can reach a verdict without every changed hunk ever reaching the reviewer, and
nothing recorded that. The invariant: every changed hunk of the authoritative PR diff
(``parse_diff_scope``) is **covered** only through mediated evidence — it was in the
delivered diff (net of truncation and files with no inline patch), a mediated read of its
file returned the lines, or an explicit follow-up turn handed it back. Absence of evidence
is *uncovered*, not *unknown*. Policy exclusions (generated files) are listed but do not
count against completeness.
"""

from __future__ import annotations

import pytest

_TWO_FILES = (
    "diff --git a/src/a.py b/src/a.py\n"
    "--- a/src/a.py\n"
    "+++ b/src/a.py\n"
    "@@ -1,2 +1,3 @@\n"
    " keep\n"
    "+added\n"
    " keep\n"
    "@@ -10,2 +11,2 @@\n"
    "-old\n"
    "+new\n"
    " keep\n"
    "diff --git a/src/b.py b/src/b.py\n"
    "--- a/src/b.py\n"
    "+++ b/src/b.py\n"
    "@@ -5,0 +6,4 @@\n"
    "+one\n"
    "+two\n"
    "+three\n"
    "+four\n"
)


def _only(diff: str, path: str) -> str:
    """Return the sections of ``diff`` that belong to ``path`` (a delivered subset)."""
    chunks = diff.split("diff --git ")
    kept = [c for c in chunks if c and f"a/{path} " in c]
    return "".join("diff --git " + c for c in kept)


# ── the universe ──────────────────────────────────────────────────────────────


def test_universe_lists_every_hunk_with_its_new_side_range() -> None:
    from mergecraft.evidence.coverage import Hunk, coverage_universe

    assert coverage_universe(_TWO_FILES) == [
        Hunk("src/a.py", 1, 3),
        Hunk("src/a.py", 11, 12),
        Hunk("src/b.py", 6, 9),
    ]


def test_universe_keeps_a_deleted_only_hunk() -> None:
    from mergecraft.evidence.coverage import coverage_universe

    diff = (
        "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
        "@@ -4,2 +3,0 @@\n-gone\n-gone too\n"
    )

    hunks = coverage_universe(diff)

    assert len(hunks) == 1
    assert hunks[0].path == "src/a.py"


def test_universe_follows_a_rename_to_the_new_path() -> None:
    from mergecraft.evidence.coverage import coverage_universe

    diff = (
        "diff --git a/old/name.py b/new/name.py\nsimilarity index 90%\n"
        "rename from old/name.py\nrename to new/name.py\n"
        "--- a/old/name.py\n+++ b/new/name.py\n@@ -1,2 +1,2 @@\n-a\n+b\n keep\n"
    )

    assert [h.path for h in coverage_universe(diff)] == ["new/name.py"]


def test_universe_excludes_binary_headers() -> None:
    from mergecraft.evidence.coverage import coverage_universe

    diff = (
        "diff --git a/img.png b/img.png\nindex 111..222 100644\n"
        "Binary files a/img.png and b/img.png differ\n" + _TWO_FILES
    )

    assert {h.path for h in coverage_universe(diff)} == {"src/a.py", "src/b.py"}


def test_universe_is_not_confused_by_no_newline_at_end_of_file() -> None:
    from mergecraft.evidence.coverage import Hunk, coverage_universe

    diff = (
        "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
        "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file\n"
    )

    assert coverage_universe(diff) == [Hunk("src/a.py", 1, 1)]


def test_universe_of_an_empty_diff_is_empty() -> None:
    from mergecraft.evidence.coverage import coverage_universe

    assert coverage_universe("") == []


# ── accounting ────────────────────────────────────────────────────────────────


def test_a_fully_delivered_diff_is_complete() -> None:
    from mergecraft.evidence.coverage import account_coverage

    section = account_coverage(authoritative_diff=_TWO_FILES)

    assert section.complete is True
    assert section.hunks_total == 3
    assert section.hunks_covered == 3
    assert section.lines_total == section.lines_covered == 3 + 2 + 4
    assert section.uncovered == []


def test_a_hunk_missing_from_the_delivered_diff_is_uncovered_not_unknown() -> None:
    from mergecraft.evidence.coverage import account_coverage

    section = account_coverage(
        authoritative_diff=_TWO_FILES, delivered_diff=_only(_TWO_FILES, "src/a.py")
    )

    assert section.complete is False
    assert (section.hunks_total, section.hunks_covered) == (3, 2)
    assert (section.lines_total, section.lines_covered) == (9, 5)
    [row] = section.uncovered
    assert (row.path, row.start_line, row.end_line, row.cause) == (
        "src/b.py",
        6,
        9,
        "not_delivered",
    )


def test_a_mediated_read_of_the_file_covers_its_hunks() -> None:
    from mergecraft.evidence.coverage import account_coverage

    section = account_coverage(
        authoritative_diff=_TWO_FILES,
        delivered_diff=_only(_TWO_FILES, "src/a.py"),
        read_paths={"src/b.py"},
    )

    assert section.complete is True
    assert section.hunks_covered == 3


def test_a_follow_up_turn_covers_exactly_the_hunks_it_handed_back() -> None:
    from mergecraft.evidence.coverage import Hunk, account_coverage

    section = account_coverage(
        authoritative_diff=_TWO_FILES,
        delivered_diff="",
        followup_hunks={Hunk("src/a.py", 1, 3), Hunk("src/b.py", 6, 9)},
    )

    assert section.complete is False
    assert [(r.path, r.start_line) for r in section.uncovered] == [("src/a.py", 11)]


def test_a_file_with_no_inline_patch_is_listed_and_never_cleared() -> None:
    from mergecraft.evidence.coverage import account_coverage

    section = account_coverage(
        authoritative_diff=_TWO_FILES,
        unreviewable_paths=["big/huge.py"],
        read_paths={"big/huge.py"},
    )

    assert section.complete is False
    [row] = section.uncovered
    assert (row.path, row.cause) == ("big/huge.py", "no_inline_patch")
    assert section.hunks_total == 4, "the unseen file counts as one unreviewed hunk"
    assert section.hunks_covered == 3


def test_a_truncated_file_listing_is_uncovered_with_its_own_cause() -> None:
    from mergecraft.evidence.coverage import account_coverage

    section = account_coverage(authoritative_diff=_TWO_FILES, diff_truncated=True)

    assert section.complete is False
    assert [r.cause for r in section.uncovered] == ["diff_truncated"]


def test_a_generated_hunk_removed_by_policy_is_listed_but_does_not_make_the_run_incomplete() -> (
    None
):
    from mergecraft.evidence.coverage import account_coverage

    generated = (
        "diff --git a/pkg/generated/api.py b/pkg/generated/api.py\n"
        "--- a/pkg/generated/api.py\n+++ b/pkg/generated/api.py\n"
        "@@ -1,2 +1,2 @@\n-a\n+b\n keep\n"
    )

    section = account_coverage(authoritative_diff=_TWO_FILES + generated, delivered_diff=_TWO_FILES)

    assert section.complete is True
    [row] = section.uncovered
    assert (row.path, row.cause) == ("pkg/generated/api.py", "excluded_generated")
    assert section.hunks_covered == 3
    assert section.hunks_total == 4


def test_a_delivered_generated_hunk_is_simply_covered() -> None:
    from mergecraft.evidence.coverage import account_coverage

    generated = (
        "diff --git a/pkg/generated/api.py b/pkg/generated/api.py\n"
        "--- a/pkg/generated/api.py\n+++ b/pkg/generated/api.py\n"
        "@@ -1,2 +1,2 @@\n-a\n+b\n keep\n"
    )

    section = account_coverage(authoritative_diff=_TWO_FILES + generated)

    assert section.complete is True
    assert section.uncovered == []


def test_budget_exhaustion_is_named_as_the_cause_of_what_stayed_uncovered() -> None:
    from mergecraft.evidence.coverage import account_coverage

    section = account_coverage(
        authoritative_diff=_TWO_FILES,
        delivered_diff=_only(_TWO_FILES, "src/a.py"),
        budget_exhausted=True,
    )

    assert [r.cause for r in section.uncovered] == ["budget_exhausted"]
    assert section.complete is False


def test_no_diff_at_all_is_complete_with_nothing_to_cover() -> None:
    from mergecraft.evidence.coverage import account_coverage

    section = account_coverage(authoritative_diff="")

    assert section.complete is True
    assert section.hunks_total == 0


# ── the line on the check ─────────────────────────────────────────────────────


def test_summary_line_states_hunks_and_the_outcome_it_causes() -> None:
    from mergecraft.evidence.coverage import account_coverage, coverage_summary_line

    section = account_coverage(
        authoritative_diff=_TWO_FILES, delivered_diff=_only(_TWO_FILES, "src/a.py")
    )

    line = coverage_summary_line(section, on_incomplete="inconclusive")

    assert line.startswith("Coverage: 2/3 hunks, 1 uncovered → inconclusive")
    assert "src/b.py:6-9" in line


def test_summary_line_for_the_warn_policy_says_it_only_warns() -> None:
    from mergecraft.evidence.coverage import account_coverage, coverage_summary_line

    section = account_coverage(
        authoritative_diff=_TWO_FILES, delivered_diff=_only(_TWO_FILES, "src/a.py")
    )

    assert "→ warn" in coverage_summary_line(section, on_incomplete="warn")


def test_summary_line_caps_the_listed_ranges_and_counts_the_overflow() -> None:
    from mergecraft.evidence.coverage import account_coverage, coverage_summary_line

    paths = [f"src/f{n:02d}.py" for n in range(25)]
    diff = "".join(
        f"diff --git a/{p} b/{p}\n--- a/{p}\n+++ b/{p}\n@@ -1 +1 @@\n-a\n+b\n" for p in paths
    )

    section = account_coverage(authoritative_diff=diff, delivered_diff="")
    line = coverage_summary_line(section, on_incomplete="inconclusive")

    assert "25 uncovered" in line
    assert "src/f00.py:1" in line
    assert "src/f24.py" not in line
    assert "more" in line


def test_summary_line_for_a_complete_run_is_just_the_count() -> None:
    from mergecraft.evidence.coverage import account_coverage, coverage_summary_line

    line = coverage_summary_line(
        account_coverage(authoritative_diff=_TWO_FILES), on_incomplete="inconclusive"
    )

    assert line == "Coverage: 3/3 hunks"


# ── the outcome ───────────────────────────────────────────────────────────────


def _classify(**overrides: object) -> tuple[object, str | None]:
    from mergecraft.agents.shared import AgentResult
    from mergecraft.main_outcome import _classify_outcome

    kwargs: dict[str, object] = {
        "result": AgentResult(success=True, terminal_submission_received=True),
        "setup_reason": "",
        "setup_policy": "warn",
        "prep_reason": None,
        "mode": "Review",
        "verdict_protocol": "enforce",
        "terminal_publication_receipt": True,
    }
    kwargs.update(overrides)
    return _classify_outcome(**kwargs)  # type: ignore[arg-type]


def test_an_incomplete_coverage_reason_turns_a_submitted_verdict_inconclusive() -> None:
    from mergecraft.run_outcome import RunOutcome

    outcome, reason = _classify(coverage_incomplete_reason="Coverage: 2/3 hunks, 1 uncovered")

    assert outcome is RunOutcome.inconclusive
    assert reason is not None
    assert "Coverage: 2/3 hunks" in reason


def test_a_complete_run_is_unchanged() -> None:
    from mergecraft.run_outcome import RunOutcome

    outcome, reason = _classify(coverage_incomplete_reason=None)

    assert outcome is RunOutcome.passed
    assert reason is None


def test_coverage_does_not_mask_an_agent_failure() -> None:
    from mergecraft.agents.shared import AgentResult
    from mergecraft.run_outcome import RunOutcome

    outcome, reason = _classify(
        result=AgentResult(success=False, error="agent crashed"),
        coverage_incomplete_reason="Coverage: 2/3 hunks, 1 uncovered",
    )

    assert outcome is RunOutcome.failed
    assert reason == "agent crashed"


def test_a_blocker_still_wins_over_incomplete_coverage() -> None:
    """Blockers are never masked: an incomplete run with a Major finding is ``failure``."""
    from mergecraft.evidence.coverage import account_coverage

    from mergecraft.agents.gates import decide_approval
    from mergecraft.analyzers.finding import make_finding
    from mergecraft.evidence.build import build_packet

    blocker = make_finding(
        tool="agent",
        rule_id="agent:terminal",
        category="Security & Privacy",
        severity="Major",
        confidence="certain",
        message="Unchecked input reaches the shell.",
        path="src/a.py",
        start_line=2,
        end_line=2,
        source="agent",
        evidence=["x"],
        remediation="Validate it.",
        fingerprint="cov-blocker-1",
    )
    incomplete = account_coverage(
        authoritative_diff=_TWO_FILES, delivered_diff=_only(_TWO_FILES, "src/a.py")
    )
    packet = build_packet(
        change_id="acme/demo#7",
        agent_id="claude",
        agent_version="0",
        model="m",
        files_changed=["src/a.py"],
        findings=[blocker],
        deterministic_checks=[],
        coverage=incomplete,
    )

    assert decide_approval(packet, run_succeeded=False, tier="trusted").verdict == "failure"
    clean = packet.model_copy(update={"findings": []})
    assert decide_approval(clean, run_succeeded=False, tier="trusted").verdict == "neutral"


# ── the setting ───────────────────────────────────────────────────────────────


def test_the_default_policy_is_inconclusive() -> None:
    from mergecraft.config.settings import RepoSettings

    assert RepoSettings().review.coverage.on_incomplete == "inconclusive"


def test_the_yaml_spelling_is_on_incomplete_and_accepts_warn() -> None:
    from mergecraft.config.settings import RepoSettings

    settings = RepoSettings.model_validate({"review": {"coverage": {"onIncomplete": "warn"}}})

    assert settings.review.coverage.on_incomplete == "warn"


def test_an_unknown_policy_value_is_rejected() -> None:
    from pydantic import ValidationError

    from mergecraft.config.settings import RepoSettings

    with pytest.raises(ValidationError):
        RepoSettings.model_validate({"review": {"coverage": {"onIncomplete": "ignore"}}})


def test_the_gate_reason_follows_the_pinned_policy() -> None:
    from mergecraft.evidence.coverage import account_coverage, coverage_gate_reason

    incomplete = account_coverage(
        authoritative_diff=_TWO_FILES, delivered_diff=_only(_TWO_FILES, "src/a.py")
    )
    complete = account_coverage(authoritative_diff=_TWO_FILES)

    assert coverage_gate_reason(incomplete, on_incomplete="inconclusive") is not None
    assert coverage_gate_reason(incomplete, on_incomplete="warn") is None
    assert coverage_gate_reason(complete, on_incomplete="inconclusive") is None
    assert coverage_gate_reason(None, on_incomplete="inconclusive") is None
