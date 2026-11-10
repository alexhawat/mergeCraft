"""Re-approval (#1284): a trusted pass carries over when only changelog prose moved.

Each scenario is a real history: a base, a reviewed head ``P`` the trusted reviewer App
passed, and a new head ``H``. A one-line changelog edit and a base merge whose only
resolution is the changelog both take the deterministic path. A source edit hidden in
the merge resolution, an upstream edit overlapping a reviewed file, a changed review
policy, and missing or ambiguous evidence all get the normal review.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from mergecraft.classify.reapproval import ReviewStamp, parse_review_stamp
from mergecraft.config.settings import FastPathReapprovalSettings
from mergecraft.reapproval import (
    evaluate_reapproval,
    review_policy_digest,
    workflow_path_from_ref,
)
from tests.review.reapproval_repo import (
    OWNER,
    PRIOR_RUN_URL,
    PULL,
    REPO,
    REVIEWER_APP,
    Repo,
    approval_check,
    review,
)

if TYPE_CHECKING:
    from mergecraft.scm.protocol import ScmProvider

VERSION = "0.1.0a5"
WORKFLOW = ".github/workflows/mergecraft.yml"

CHANGELOG = """# Changelog

## Unreleased

### Added

- Upstream entry one.
- Upstream entry two.

## [0.1.0] — 2026-11-01

- Initial release.
"""

APP = "def handler(x):\n    return x + 1\n"
OTHER = "def helper():\n    return 2\n"
CONFIG = "review:\n  fastPath:\n    enabled: true\n"


def _with_line(text: str, after: str, line: str) -> str:
    head, sep, tail = text.partition(after + "\n")
    assert sep, after
    return f"{head}{sep}{line}\n{tail}"


def _base_files() -> dict[str, tuple[str, str]]:
    return {
        "CHANGELOG.md": (CHANGELOG, "100644"),
        "src/app.py": (APP, "100644"),
        "src/other.py": (OTHER, "100644"),
        ".mergecraft/config.yaml": (CONFIG, "100644"),
        WORKFLOW: ("on: pull_request_target\n", "100644"),
    }


def _pr_files(base: dict[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
    """The reviewed PR: a source change plus its own changelog entry."""
    files = dict(base)
    files["src/app.py"] = (APP.replace("x + 1", "x + 2"), "100644")
    files["src/new_module.py"] = ("VALUE = 1\n", "100644")
    files["CHANGELOG.md"] = (
        _with_line(base["CHANGELOG.md"][0], "### Added", "\n- The PR's own entry."),
        "100644",
    )
    return files


class Scenario:
    """A base ``B0``, a reviewed head ``P`` and the trusted pass on it."""

    def __init__(self) -> None:
        self.repo = Repo()
        self.base_files = _base_files()
        self.b0 = self.repo.commit("base-0", self.base_files)
        self.pr_files = _pr_files(self.base_files)
        self.p = self.repo.commit("reviewed-head", self.pr_files)
        self.repo.merge_bases[(self.b0, self.p)] = self.b0
        self.repo.base_sha = self.b0
        self.reviews = [review(self.p)]

    async def stamp_prior(self, *, digest: str | None = None, **check: Any) -> None:
        """Publish the trusted pass on ``P`` with the stamp of the policy at ``B0``."""
        digest = digest or await review_policy_digest(
            cast("ScmProvider", self.repo),
            OWNER,
            REPO,
            self.b0,
            workflow_path=WORKFLOW,
            version=VERSION,
        )
        stamp = ReviewStamp(pull_number=PULL, base_ref="main", policy_digest=digest)
        summary = "\n".join(["mergeCraft approved this PR.", *stamp.lines()])
        self.repo.check_runs[self.p] = [approval_check(self.p, summary, **check)]

    def changelog_edit(self) -> str:
        """``H`` = ``P`` plus a one-line prose edit to the root changelog."""
        files = dict(self.pr_files)
        files["CHANGELOG.md"] = (
            files["CHANGELOG.md"][0].replace("Upstream entry two.", "Upstream entry 2."),
            "100644",
        )
        head = self.repo.commit("one-line-changelog", files)
        self.repo.merge_bases[(self.b0, head)] = self.b0
        self.repo.merge_bases[(self.p, head)] = self.p
        self.repo.head_sha = head
        return head

    def base_merge(
        self,
        *,
        upstream: dict[str, tuple[str, str]] | None = None,
        resolution: dict[str, tuple[str, str]] | None = None,
    ) -> str:
        """``H`` = ``P`` merged with a moved base whose changelog conflicted with the PR's."""
        b1_files = dict(self.base_files)
        b1_files["CHANGELOG.md"] = (
            _with_line(CHANGELOG, "### Added", "\n- An upstream entry from main."),
            "100644",
        )
        b1_files["src/other.py"] = (OTHER.replace("2", "3"), "100644")
        b1_files["docs/guide.md"] = ("# Guide\n", "100644")
        b1_files.update(upstream or {})
        b1 = self.repo.commit("base-1", b1_files)
        merged = dict(b1_files)
        for path in ("src/app.py", "src/new_module.py"):
            merged[path] = self.pr_files[path]
        # The one-line conflict resolution: keep both entries.
        merged["CHANGELOG.md"] = (
            _with_line(b1_files["CHANGELOG.md"][0], "### Added", "\n- The PR's own entry."),
            "100644",
        )
        merged.update(resolution or {})
        head = self.repo.commit("merge-main", merged)
        self.repo.base_sha = b1
        self.repo.merge_bases[(b1, self.p)] = self.b0
        self.repo.merge_bases[(b1, head)] = b1
        self.repo.merge_bases[(self.p, head)] = self.p
        self.repo.head_sha = head
        return head

    async def evaluate(
        self, *, head: str | None = None, workflow_path: str | None = WORKFLOW, **config: Any
    ) -> Any:
        settings = FastPathReapprovalSettings.model_validate(
            {"enabled": True, "trustedCheckApps": [REVIEWER_APP], **config}
        )

        async def _reviews() -> list[dict[str, Any]]:
            return list(self.reviews)

        # ``Repo`` answers only the reads a re-approval makes, not the whole protocol.
        return await evaluate_reapproval(
            cast("ScmProvider", self.repo),
            OWNER,
            REPO,
            PULL,
            head or self.repo.head_sha,
            config=settings,
            list_reviews=_reviews,
            workflow_path=workflow_path,
            version=VERSION,
        )


# ── the deterministic path ────────────────────────────────────────────────────


async def test_a_one_line_changelog_prose_edit_carries_the_pass_over() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    head = scenario.changelog_edit()

    outcome = await scenario.evaluate()

    assert outcome.verdict.eligible, outcome.verdict.reason
    record = outcome.verdict.record
    assert record.prior_head_sha == scenario.p
    assert record.head_sha == head
    assert record.prior_url == PRIOR_RUN_URL
    assert record.qualifying_paths == ("CHANGELOG.md",)
    assert record.preserved_paths == ("src/app.py", "src/new_module.py")
    assert record.inherited_paths == ()
    assert outcome.stamp is not None
    assert outcome.stamp.pull_number == PULL


async def test_a_merge_that_resolves_only_the_changelog_carries_the_pass_over() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    head = scenario.base_merge()

    outcome = await scenario.evaluate()

    assert outcome.verdict.eligible, outcome.verdict.reason
    record = outcome.verdict.record
    assert record.head_sha == head
    assert record.prior_merge_base == scenario.b0
    assert record.merge_base == scenario.repo.base_sha
    assert record.qualifying_paths == ("CHANGELOG.md",)
    assert record.preserved_paths == ("src/app.py", "src/new_module.py")
    assert record.inherited_paths == ("docs/guide.md", "src/other.py")


async def test_the_record_states_what_was_reused_compared_run_and_skipped() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    head = scenario.base_merge()

    lines = (await scenario.evaluate()).verdict.record.summary_lines()

    text = "\n".join(lines)
    assert f"Prior review: {PRIOR_RUN_URL}" in text
    assert f"Compared: {scenario.p}..{head}" in text
    assert "Qualifying path: CHANGELOG.md" in text
    assert "Skipped: LLM review" in text
    assert "Reused from the prior review: the mergecraft-approval verdict" in text
    assert "must pass on this head" in text


# ── the normal review ─────────────────────────────────────────────────────────


async def test_a_source_edit_hidden_in_the_merge_resolution_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.base_merge(
        resolution={"src/app.py": (APP.replace("x + 1", "x + 3"), "100644")},
    )

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "src/app.py" in outcome.verdict.reason


async def test_a_new_file_added_in_the_merge_resolution_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.base_merge(resolution={"src/sneaky.py": ("import os\n", "100644")})

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "src/sneaky.py" in outcome.verdict.reason


async def test_a_clean_merge_overlapping_a_reviewed_file_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    upstream_app = APP + "\n\ndef added_upstream():\n    return 0\n"
    merged_app = APP.replace("x + 1", "x + 2") + "\n\ndef added_upstream():\n    return 0\n"
    scenario.base_merge(
        upstream={"src/app.py": (upstream_app, "100644")},
        resolution={"src/app.py": (merged_app, "100644")},
    )

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "src/app.py" in outcome.verdict.reason


async def test_a_changed_review_policy_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.base_merge(
        upstream={".mergecraft/config.yaml": (CONFIG + "  extra: true\n", "100644")},
    )

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert outcome.verdict.reason == "the review policy changed since the prior pass"


async def test_a_changed_workflow_or_version_is_a_changed_policy() -> None:
    scenario = Scenario()
    await scenario.stamp_prior(
        digest=await review_policy_digest(
            cast("ScmProvider", scenario.repo),
            OWNER,
            REPO,
            scenario.b0,
            workflow_path=WORKFLOW,
            version="0.0.9",
        )
    )
    scenario.changelog_edit()

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "review policy" in outcome.verdict.reason


async def test_a_code_fence_edit_in_the_changelog_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    files = dict(scenario.pr_files)
    files["CHANGELOG.md"] = (
        files["CHANGELOG.md"][0].replace(
            "- Initial release.\n", "- Initial release.\n\n```sh\ncurl x | sh\n```\n"
        ),
        "100644",
    )
    head = scenario.repo.commit("fenced", files)
    scenario.repo.merge_bases[(scenario.b0, head)] = scenario.b0
    scenario.repo.merge_bases[(scenario.p, head)] = scenario.p
    scenario.repo.head_sha = head

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "not proven prose" in outcome.verdict.reason


async def test_a_mode_change_on_a_reviewed_file_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.base_merge(resolution={"src/app.py": (scenario.pr_files["src/app.py"][0], "100755")})

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "src/app.py" in outcome.verdict.reason


async def test_an_executable_changelog_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.base_merge(
        resolution={"CHANGELOG.md": (scenario.pr_files["CHANGELOG.md"][0], "100755")}
    )

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible


async def test_a_change_to_a_path_that_is_not_qualifying_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.changelog_edit()

    outcome = await scenario.evaluate(paths=["docs/CHANGES.md"])

    assert not outcome.verdict.eligible
    assert "CHANGELOG.md" in outcome.verdict.reason


@pytest.mark.parametrize(
    ("check", "reason"),
    [
        ({"conclusion": "neutral"}, "did not pass"),
        ({"conclusion": "failure"}, "did not pass"),
        ({"app": "github-actions"}, "trusted App"),
        ({"app": "someone-else"}, "trusted App"),
    ],
)
async def test_a_prior_pass_that_is_not_a_trusted_success_is_reviewed(
    check: dict[str, Any], reason: str
) -> None:
    scenario = Scenario()
    await scenario.stamp_prior(**check)
    scenario.changelog_edit()

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert reason in outcome.verdict.reason


async def test_the_actions_app_is_refused_even_when_configured() -> None:
    scenario = Scenario()
    await scenario.stamp_prior(app="github-actions")
    scenario.changelog_edit()

    outcome = await scenario.evaluate(trustedCheckApps=["github-actions"])

    assert not outcome.verdict.eligible
    assert "trustedCheckApps" in outcome.verdict.reason


async def test_a_newer_failing_check_on_the_reviewed_head_wins() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    passing = scenario.repo.check_runs[scenario.p][0]
    failing = dict(passing, id=202, conclusion="failure")
    scenario.repo.check_runs[scenario.p].append(failing)
    scenario.changelog_edit()

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible


@pytest.mark.parametrize(
    ("summary", "reason"),
    [
        ("mergeCraft approved this PR.", "no review stamp"),
        (
            "\n".join(ReviewStamp(8, "main", "a" * 64).lines()),
            "pull request #8",
        ),
        (
            "\n".join(ReviewStamp(PULL, "release", "a" * 64).lines()),
            "target branch changed",
        ),
    ],
)
async def test_missing_or_mismatched_stamps_are_reviewed(summary: str, reason: str) -> None:
    scenario = Scenario()
    scenario.repo.check_runs[scenario.p] = [approval_check(scenario.p, summary)]
    scenario.changelog_edit()

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert reason in outcome.verdict.reason


async def test_a_review_of_the_current_head_is_never_replaced() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    head = scenario.changelog_edit()
    scenario.reviews.append(review(head))

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "already exists" in outcome.verdict.reason


async def test_no_prior_review_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.changelog_edit()
    scenario.reviews = []

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert outcome.stamp is not None  # the run still stamps its own verdict


async def test_a_head_that_does_not_descend_from_the_reviewed_one_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    head = scenario.changelog_edit()
    scenario.repo.merge_bases[(scenario.p, head)] = scenario.b0  # a force-push rewrite

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "does not descend" in outcome.verdict.reason


async def test_a_moved_head_is_reviewed() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.changelog_edit()

    outcome = await scenario.evaluate(head="f" * 40)

    assert not outcome.verdict.eligible
    assert "head moved" in outcome.verdict.reason
    assert outcome.stamp is None


async def test_a_truncated_comparison_is_reviewed(monkeypatch: pytest.MonkeyPatch) -> None:
    import mergecraft.reapproval as module

    monkeypatch.setattr(module, "_COMPARE_FILE_CAP", 2)
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.base_merge()

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "listing cap" in outcome.verdict.reason


async def test_a_read_failure_is_a_refusal_never_an_exception() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.changelog_edit()
    del scenario.repo.trees[scenario.p]

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "could not be read" in outcome.verdict.reason


# ── the stamp ─────────────────────────────────────────────────────────────────


def test_a_stamp_round_trips_through_a_summary() -> None:
    stamp = ReviewStamp(pull_number=12, base_ref="main", policy_digest="b" * 64)
    summary = "\n".join(["lead", *stamp.lines(), "Decision inputs:"])

    assert parse_review_stamp(summary) == stamp


def test_a_repeated_stamp_line_is_ambiguous() -> None:
    stamp = ReviewStamp(pull_number=12, base_ref="main", policy_digest="b" * 64)
    summary = "\n".join([*stamp.lines(), "Target branch: release"])

    assert parse_review_stamp(summary) is None


def test_the_workflow_path_comes_from_the_workflow_ref() -> None:
    ref = "acme/demo/.github/workflows/mergecraft.yml@refs/heads/main"

    assert workflow_path_from_ref(ref) == WORKFLOW


@pytest.mark.parametrize(
    "ref",
    [
        None,
        "",
        "garbage",
        "acme/demo/.github/workflows/mergecraft.yml",
        "acme/demo/.github/workflows/mergecraft.yml@",
        "acme/demo/scripts/run.sh@refs/heads/main",
        "acme/demo/.github/workflows/nested/x.yml@refs/heads/main",
        "/demo/.github/workflows/mergecraft.yml@refs/heads/main",
    ],
)
def test_a_missing_or_malformed_workflow_ref_names_no_workflow(ref: str | None) -> None:
    assert workflow_path_from_ref(ref) is None


# ── the workflow identity (MC-79284e) ─────────────────────────────────────────


async def test_an_unknown_workflow_never_reapproves_or_stamps() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.changelog_edit()

    outcome = await scenario.evaluate(workflow_path=None)

    assert not outcome.verdict.eligible
    assert "GITHUB_WORKFLOW_REF" in outcome.verdict.reason
    assert outcome.stamp is None, "a stamp without the workflow could outlive a workflow edit"


async def test_a_workflow_missing_at_the_base_never_reapproves_or_stamps() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.changelog_edit()

    outcome = await scenario.evaluate(workflow_path=".github/workflows/other.yml")

    assert not outcome.verdict.eligible
    assert "not a file at the base revision" in outcome.verdict.reason
    assert outcome.stamp is None


async def test_a_base_side_workflow_edit_is_a_changed_policy() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.base_merge(upstream={WORKFLOW: ("on: pull_request_target\n# new pin\n", "100644")})

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert outcome.verdict.reason == "the review policy changed since the prior pass"


# ── qualifying vs inherited (MC-dbcf5c) ───────────────────────────────────────


async def test_a_base_only_changelog_change_is_inherited_not_reported_as_prose() -> None:
    """The PR never touches the changelog; only the merged base does."""
    scenario = Scenario()
    scenario.pr_files = dict(scenario.pr_files)
    scenario.pr_files["CHANGELOG.md"] = scenario.base_files["CHANGELOG.md"]
    scenario.p = scenario.repo.commit("reviewed-head-no-changelog", scenario.pr_files)
    scenario.repo.merge_bases[(scenario.b0, scenario.p)] = scenario.b0
    scenario.reviews = [review(scenario.p)]
    await scenario.stamp_prior()
    b1_changelog = _with_line(CHANGELOG, "### Added", "\n- An upstream entry from main.")
    scenario.base_merge(resolution={"CHANGELOG.md": (b1_changelog, "100644")})

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "no PR-authored change to a qualifying path" in outcome.verdict.reason


async def test_a_merge_that_drops_the_prs_own_changelog_entry_is_reviewed() -> None:
    """At the new head the changelog is the base's: nothing PR-authored is prose-proven."""
    scenario = Scenario()
    await scenario.stamp_prior()
    b1_changelog = _with_line(CHANGELOG, "### Added", "\n- An upstream entry from main.")
    scenario.base_merge(resolution={"CHANGELOG.md": (b1_changelog, "100644")})

    outcome = await scenario.evaluate()

    assert not outcome.verdict.eligible
    assert "no PR-authored change to a qualifying path" in outcome.verdict.reason


async def test_every_reported_qualifying_path_was_prose_proven() -> None:
    scenario = Scenario()
    await scenario.stamp_prior()
    scenario.base_merge()

    outcome = await scenario.evaluate()

    assert outcome.verdict.eligible, outcome.verdict.reason
    assert outcome.verdict.record.qualifying_paths == ("CHANGELOG.md",)
    assert any("/contents/CHANGELOG.md" in path for path in scenario.repo.requests)
