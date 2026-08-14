"""Unit tests for built-in mode catalogs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from mergecraft.modes import (
    NON_COMMITTING_MODES,
    PR_SUMMARY_FORMAT,
    Mode,
    compute_modes,
    modes,
)
from mergecraft.review_taxonomy import (
    BODY_ONLY_EFFORT,
    BODY_ONLY_SEVERITY,
    FINDING_CATEGORIES,
    FINDING_CONFIDENCES,
    FINDING_EFFORTS,
    FINDING_SEVERITIES,
    VERIFY_FIRST_PREAMBLE,
    WITHDRAWN_FINDINGS_HEADING,
)
from mergecraft.types import format_mcp_tool_ref

EXPECTED_MODE_NAMES = [
    "Build",
    "AddressReviews",
    "Review",
    "IncrementalReview",
    "Plan",
    "Fix",
    "ResolveConflicts",
    "Task",
]


def test_compute_modes_returns_all_built_ins() -> None:
    result = compute_modes("opencode")
    assert [m.name for m in result] == EXPECTED_MODE_NAMES
    assert all(isinstance(m, Mode) for m in result)
    assert all(m.prompt and m.description for m in result)


def test_static_modes_match_opencode_default() -> None:
    assert [m.name for m in modes] == EXPECTED_MODE_NAMES
    assert "mergecraft_checkout_pr" in (modes[0].prompt or "")


def test_claude_tool_refs_use_mcp_prefix() -> None:
    build = compute_modes("claude")[0]
    assert "mcp__mergecraft__checkout_pr" in (build.prompt or "")
    assert "mcp__mergecraft__push_branch" in (build.prompt or "")
    assert "mergecraft_checkout_pr" not in (build.prompt or "")


def test_opencode_tool_refs_use_underscore() -> None:
    build = compute_modes("opencode")[0]
    assert "mergecraft_checkout_pr" in (build.prompt or "")
    assert "mcp__mergecraft__" not in (build.prompt or "")


def test_signed_commits_swaps_commit_and_push_flow() -> None:
    unsigned = next(m for m in compute_modes("opencode", signed_commits=False) if m.name == "Build")
    signed = next(m for m in compute_modes("opencode", signed_commits=True) if m.name == "Build")
    assert "git add . && git commit" in (unsigned.prompt or "")
    assert "mergecraft_push_branch" in (unsigned.prompt or "")
    assert "mergecraft_commit_changes" in (signed.prompt or "")
    assert "no push step" in (signed.prompt or "")


def test_resolve_conflicts_signed_commits_uses_no_commit_merge() -> None:
    rc = next(
        m for m in compute_modes("claude", signed_commits=True) if m.name == "ResolveConflicts"
    )
    assert "git merge --no-commit origin/<base_branch>" in (rc.prompt or "")
    assert "mcp__mergecraft__commit_changes" in (rc.prompt or "")


def test_non_committing_modes() -> None:
    assert frozenset({"Review", "IncrementalReview", "Plan"}) == NON_COMMITTING_MODES


def test_pr_summary_format_embedded_in_review_modes() -> None:
    assert "### Default format" in PR_SUMMARY_FORMAT
    assert "{head_sha_short}" in PR_SUMMARY_FORMAT
    for name in ("Review", "IncrementalReview"):
        mode = next(m for m in modes if m.name == name)
        assert "### Default format" in (mode.prompt or "")
        assert "Nitpicks" in (mode.prompt or "")


def test_pr_summary_format_names_every_taxonomy_value() -> None:
    """The prompt is the only consumer of the taxonomy — it must name all of it."""
    for value in (*FINDING_CATEGORIES, *FINDING_SEVERITIES, *FINDING_EFFORTS):
        assert value in PR_SUMMARY_FORMAT, value


def test_fix_all_block_carries_verify_first_preamble_verbatim() -> None:
    assert VERIFY_FIRST_PREAMBLE in PR_SUMMARY_FORMAT
    assert "### 🤖 Fix all findings" in PR_SUMMARY_FORMAT


def test_pre_merge_checks_table_present() -> None:
    assert "### 🚥 Pre-merge checks" in PR_SUMMARY_FORMAT
    for row in (
        "| Title |",
        "| Description |",
        "| Linked issues |",
        "| Scope |",
        "| Analyzers |",
        "| CI |",
    ):
        assert row in PR_SUMMARY_FORMAT, row


def test_pr_summary_format_names_every_confidence_value() -> None:
    for value in FINDING_CONFIDENCES:
        assert value in PR_SUMMARY_FORMAT, value


def test_pr_summary_format_includes_ci_failures_section() -> None:
    assert "### 🚨 CI failures" in PR_SUMMARY_FORMAT
    assert "reported, not blamed" in PR_SUMMARY_FORMAT


def test_review_modes_ci_failures_reported_not_blamed() -> None:
    for name in ("Review", "IncrementalReview"):
        prompt = next(m for m in modes if m.name == name).prompt or ""
        assert "reported, not blamed" in prompt, name
        assert "### 🚨 CI failures" in prompt, name


def test_pr_summary_format_includes_mechanical_findings_section() -> None:
    assert "### 🔧 Mechanical findings" in PR_SUMMARY_FORMAT


def test_review_modes_reference_ci_intelligence_tool() -> None:
    for agent, prefix in (("claude", "mcp__mergecraft__"), ("opencode", "mergecraft_")):
        for name in ("Review", "IncrementalReview"):
            prompt = next(m for m in compute_modes(agent) if m.name == name).prompt or ""
            assert f"{prefix}analyze_ci_failures" in prompt, (agent, name)
            assert "preMergeSummary" in prompt, (agent, name)


def test_review_modes_reference_analyzer_tools() -> None:
    for agent, prefix in (("claude", "mcp__mergecraft__"), ("opencode", "mergecraft_")):
        for name in ("Review", "IncrementalReview"):
            prompt = next(m for m in compute_modes(agent) if m.name == name).prompt or ""
            assert f"{prefix}run_analyzers" in prompt, (agent, name)
            assert "analyzer_findings" in prompt, (agent, name)
            assert "mergecraft-verifier" in prompt, (agent, name)


def test_trivial_findings_routed_to_nitpicks() -> None:
    assert BODY_ONLY_SEVERITY in PR_SUMMARY_FORMAT
    assert BODY_ONLY_EFFORT in PR_SUMMARY_FORMAT
    assert "never an inline comment" in PR_SUMMARY_FORMAT


def test_review_modes_run_static_checks_and_read_withdrawn_findings() -> None:
    for agent, expected_ref in (("claude", "mcp__mergecraft__"), ("opencode", "mergecraft_")):
        for name in ("Review", "IncrementalReview"):
            prompt = next(m for m in compute_modes(agent) if m.name == name).prompt or ""
            assert f"{expected_ref}run_static_checks" in prompt, (agent, name)
            assert WITHDRAWN_FINDINGS_HEADING in prompt, (agent, name)


def test_address_reviews_records_withdrawn_findings() -> None:
    prompt = next(m for m in modes if m.name == "AddressReviews").prompt or ""
    assert WITHDRAWN_FINDINGS_HEADING in prompt


def test_review_mode_has_data_integrity_and_copy_lenses() -> None:
    prompt = next(m for m in modes if m.name == "Review").prompt or ""
    assert "**data integrity & atomicity**" in prompt
    assert "**copy vs code**" in prompt


def test_review_mode_has_privilege_drop_ordering_lens() -> None:
    """Regression pin: the privilege-drop-ordering lens survives edits.

    mergeCraft shipped this exact bug shape against itself twice (root-owned
    ``$HOME`` after ``setpriv``'s uid/gid drop, then root-owned
    ``$CODEX_HOME``/``.gemini``/``.claude`` writes) before either was caught
    by review. The lens exists precisely because nothing else in the starter
    menu catches it reliably; a silent deletion should fail loudly here
    rather than surface again only as a production incident.
    """
    prompt = next(m for m in modes if m.name == "Review").prompt or ""
    assert "**privilege drop ordering**" in prompt
    assert "prepare_workspace_for_agent" in prompt


def test_mergecraft_reviewer_subagent_referenced() -> None:
    build = next(m for m in modes if m.name == "Build")
    review = next(m for m in modes if m.name == "Review")
    assert "mergecraft-reviewer" in (build.prompt or "")
    assert "mergecraft-reviewer" in (review.prompt or "")


def test_format_mcp_tool_ref_helpers() -> None:
    assert format_mcp_tool_ref("claude", "select_mode") == "mcp__mergecraft__select_mode"
    assert format_mcp_tool_ref("opencode", "select_mode") == "mergecraft_select_mode"


def test_expanded_prompts_have_no_template_markers() -> None:
    for agent in ("claude", "opencode"):
        for signed in (False, True):
            for mode in compute_modes(agent, signed_commits=signed):
                prompt = mode.prompt or ""
                assert "${" not in prompt, mode.name
                assert "<<<NEST>>>" not in prompt, mode.name


# ── S5 — per-mode prompt version + byte-identical split (#145) ───────────────

# Snapshot of every mode's rendered prompt on pre-0.0.1 HEAD. The
# ``test_mode_prompt_text_is_byte_identical_after_split`` test below is the
# load-bearing pin that defends this refactor: any silent prompt drift across
# the modes.py -> modes/ move fails this test loudly.
_PRE_SPLIT_PROMPTS_PATH: Final[Path] = (
    Path(__file__).parent / "_fixtures" / "pre_split_prompts.json"
)


def _load_pre_split_snapshot() -> Mapping[str, Mapping[str, str]]:
    """Load the snapshot fixture captured on the pre-split tree.

    Raises FileNotFoundError with a clear message if the fixture is missing
    rather than letting the test fail with an unrelated JSON decode error.
    """
    if not _PRE_SPLIT_PROMPTS_PATH.is_file():
        msg = (
            f"S5 snapshot fixture missing at {_PRE_SPLIT_PROMPTS_PATH}. "
            "Re-run the snapshot capture step before the modes.py -> modes/ move."
        )
        raise FileNotFoundError(msg)
    return json.loads(_PRE_SPLIT_PROMPTS_PATH.read_text(encoding="utf-8"))


def test_every_mode_exposes_a_prompt_version() -> None:
    """Every built-in mode carries a version constant (#145).

    The version is the prompt's content-identity — a hash of its rendered body
    — so an edit cannot silently keep the old version. The mode name maps to a
    module-level constant of the form ``<NAME>_PROMPT_VERSION``; ``Mode`` itself
    carries it on every instance so consumers can read it without an import dance.
    """
    expected = {m.name for m in compute_modes("opencode")}
    assert expected, "no built-in modes resolved — wiring is broken"

    for mode_name in expected:
        mode = next(m for m in compute_modes("opencode") if m.name == mode_name)
        assert hasattr(mode, "version"), mode_name
        version = getattr(mode, "version", "")
        assert isinstance(version, str), mode_name
        assert version, mode_name
        # Content-hash versions are short hex strings; pin the shape so a
        # future refactor that swaps the scheme has to revisit this test.
        assert len(version) >= 8, (mode_name, version)


def test_prompt_version_changes_when_prompt_text_changes() -> None:
    """Version is derived from the prompt body, not stored independently.

    Any function the catalog exposes that takes a prompt body and yields a
    version must produce different versions for different bodies, and the same
    version for identical bodies. Pin the contract on the helper directly so a
    silent change to the hashing scheme fails loudly.
    """
    from mergecraft.modes import compute_prompt_version

    assert compute_prompt_version("hello") == compute_prompt_version("hello")
    assert compute_prompt_version("hello") != compute_prompt_version("hello!")
    assert compute_prompt_version("") != compute_prompt_version("x")


def test_prompt_version_appears_in_evidence_packet() -> None:
    """The selected mode's version reaches the run's evidence packet (#145).

    The packet is the audit artifact for one merge; without a prompt version
    on it, an archived verdict cannot be attributed to the prompt that
    produced it. Only the mode that actually ran appears in the packet.
    """
    from mergecraft.evidence.run_packet import _mode_prompt_versions, _selected_modes
    from mergecraft.mcp.context import RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.mcp.tool_state import ToolState
    from mergecraft.utils.github import GitHubClient

    modes = compute_modes("opencode")
    review_mode = next(m for m in modes if m.name == "Review")

    # Homemade ToolContext with the specific mode in its catalog.
    ctx = ToolContext(
        agent_id="opencode",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=list(modes),
        tool_state=ToolState(repos={}, primary_repo_key="acme/demo"),
        mcp_server_url="",
        tmpdir="",
    )

    # Selected mode present → exactly one row with matching version.
    state = ToolState(repos={}, primary_repo_key="acme/demo", selected_mode="Review")
    rows = _mode_prompt_versions(_selected_modes(state, ctx))
    assert len(rows) == 1
    assert rows[0].mode_name == "Review"
    assert rows[0].prompt_version == review_mode.version

    # No selected mode → empty list.
    no_mode = ToolState(repos={}, primary_repo_key="acme/demo")
    assert _mode_prompt_versions(_selected_modes(no_mode, ctx)) == []


def test_prompt_version_appears_in_trace_attrs() -> None:
    """Every mode's version reaches the trace attrs emitted by the run (#145).

    Tracing's whole point is to identify what produced a row; a row with no
    prompt version cannot be attributed to the prompt that produced it.
    """
    from mergecraft.tracing.event import trace_attrs_for_mode

    review_mode = next(m for m in compute_modes("opencode") if m.name == "Review")
    attrs = trace_attrs_for_mode(review_mode)
    assert attrs.get("mergecraft.mode.name") == "Review"
    assert attrs.get("mergecraft.mode.prompt_version") == review_mode.version


def test_publish_span_attrs_source_emits_mode_attrs_end_to_end() -> None:
    """Regression pin: ``_publish_span_attrs`` spreads ``trace_attrs_for_mode``
    over the selected mode (#145 + post-#145 wiring).

    The audit found that ``trace_attrs_for_mode`` was unit-tested but never
    wired into production; the helper silently returned its dict into the
    void. This test guards against a re-introduction of that gap by
    exercising the module-scope ``_publish_span_attrs`` helper that
    ``main.py`` invokes for the ``mergecraft.publish`` span. Both
    ``run_succeeded`` and at least one set of per-mode attrs must be
    present — a future refactor that drops the spread (e.g. shrinks to
    ``{"run_succeeded": ...}``) fails this test loudly.
    """
    from mergecraft.main_outcome import _publish_span_attrs
    from mergecraft.run_outcome import RunOutcome

    review_mode = next(m for m in compute_modes("opencode") if m.name == "Review")

    emitted = _publish_span_attrs(RunOutcome.passed, review_mode)

    assert emitted.get("run_succeeded") is True
    assert emitted.get("mergecraft.mode.name") == "Review"
    assert emitted.get("mergecraft.mode.prompt_version") == review_mode.version


def test_publish_span_attrs_none_mode_yields_no_mode_attrs() -> None:
    """When no mode was selected, ``_publish_span_attrs`` omits mode keys."""
    from mergecraft.main_outcome import _publish_span_attrs
    from mergecraft.run_outcome import RunOutcome

    emitted = _publish_span_attrs(RunOutcome.configuration_error, None)

    assert emitted.get("run_succeeded") is False
    assert "mergecraft.mode.name" not in emitted
    assert "mergecraft.mode.prompt_version" not in emitted


def test_all_modes_still_resolve_by_name() -> None:
    """Regression pin: the names ``compute_modes`` returns are unchanged.

    The split relocates the per-mode modules; this test guards the public
    surface (``compute_modes``, ``_custom_modes``, ``modes``) against an
    accidental rename.
    """
    result = compute_modes("opencode")
    assert [m.name for m in result] == EXPECTED_MODE_NAMES

    # The static ``modes`` export (used by the UI) must mirror ``compute_modes``.
    assert [m.name for m in modes] == EXPECTED_MODE_NAMES

    # Custom mode merging is in main.py — guard that the public surface
    # used by main.py is still importable from the same location.
    from mergecraft.modes import _custom_modes

    assert _custom_modes([]) == []


def test_mode_prompt_text_is_byte_identical_after_split() -> None:
    """The load-bearing pin: every mode's rendered prompt is byte-identical
    against the snapshot captured on ``pre-0.0.1`` HEAD (#145).

    The split relocates ~84 KB of prompt text from ``modes.py`` to
    ``modes/<name>.py`` with no rewording, no reflowing, no "while I'm here"
    prompt edits. If this test fails, the move drifted text — restore the
    verbatim text; do NOT rewrite prompts.
    """
    snapshot = _load_pre_split_snapshot()
    current = {m.name: (m.description, m.prompt) for m in compute_modes("opencode")}

    assert set(snapshot) == set(current), (
        f"snapshot modes {set(snapshot) - set(current)} missing, "
        f"current modes {set(current) - set(snapshot)} extra"
    )

    for name, (description, prompt) in current.items():
        expected = snapshot[name]
        assert description == expected["description"], (f"{name}: description drifted",)
        assert prompt == expected["prompt"], f"{name}: prompt drifted"


def test_custom_modes_from_config_still_merge() -> None:
    """Regression pin: custom mode definitions from ``.mergecraft/config.yaml``
    still merge with the built-ins.

    The split must not touch ``_custom_modes`` (the helper ``main.py`` uses to
    project ``settings.modes`` into ``Mode`` objects). It is exported from the
    package root so the existing call sites do not change.
    """
    from mergecraft.config.settings import ModeDefinition
    from mergecraft.modes import _custom_modes

    custom = _custom_modes(
        [
            ModeDefinition(
                id="my-mode",
                name="MyMode",
                description="a custom mode",
                prompt="do the thing",
            ),
        ]
    )
    assert len(custom) == 1
    assert custom[0].name == "MyMode"
    assert custom[0].description == "a custom mode"
    assert custom[0].prompt == "do the thing"

    # Audit pin: a non-empty custom prompt must get the same content-hash
    # version as a built-in would — the evidence packet must attribute the
    # verdict to the consumer-supplied prompt exactly like a built-in.
    from mergecraft.modes import compute_prompt_version

    assert custom[0].version == compute_prompt_version("do the thing")

    # Built-ins still resolve alongside the custom mode.
    combined_names = [m.name for m in (*compute_modes("opencode"), *custom)]
    assert "MyMode" in combined_names
    assert "Build" in combined_names
