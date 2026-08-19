"""AP3 structured handoff suite — typed specialist returns (D6).

Wave plan: ``.ignorelocal/03-agent-pipeline-wave-plan.md`` (PR AP3).
Covers ``mergecraft.agents.structured_handoff`` — specialists reason in
free-form prose and emit typed ``AgentFinding`` values at the boundary;
discovery dispatch prompts carry no finding schema; typed findings feed
``plan_agent_verifications`` without orchestrator prose re-judgement.

AP3.1: three tests; green after AP3.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    from pathlib import Path

_DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
"""

_SAMPLE_HANDOFF = """\
I read the diff end-to-end and traced the checkout path. The race is real
because two goroutines can observe the same version before either write lands.

---typed-findings---
[
  {
    "path": "internal/store/checkout.go",
    "body": "Concurrent checkouts can double-spend inventory when two requests read the same stock level.",
    "severity": "Major",
    "line": 142
  }
]
"""


def _write_config(tmp_path: Path, body: str) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(body.strip() + "\n", encoding="utf-8")


def _load_registry(tmp_path: Path) -> object:
    from mergecraft.agents.registry import load_registry

    settings = load_repo_settings(root=tmp_path)
    return load_registry(settings=settings, repo_root=tmp_path)


def test_specialist_returns_typed_findings(tmp_path: Path) -> None:
    """D6 — prose reasoning is preserved; findings at the boundary are typed."""
    from mergecraft.agents.registry import AgentRole
    from mergecraft.agents.structured_handoff import parse_specialist_handoff
    from mergecraft.agents.verifier import AgentFinding

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    reviewer = registry.resolve_role(AgentRole.reviewer)
    assert reviewer.output_schema == "mergecraft.agent_finding"

    handoff = parse_specialist_handoff(_SAMPLE_HANDOFF)
    assert "race is real" in handoff.reasoning
    assert len(handoff.findings) == 1
    finding = handoff.findings[0]
    assert isinstance(finding, AgentFinding)
    assert finding.path == "internal/store/checkout.go"
    assert finding.severity == "Major"
    assert finding.line == 142
    assert "double-spend" in finding.body


def test_free_form_discovery_is_not_constrained(tmp_path: Path) -> None:
    """Discovery dispatch must not pre-shape output with a finding schema (D6)."""
    from mergecraft.agents.registry import AgentRole
    from mergecraft.agents.structured_handoff import build_specialist_dispatch_prompt

    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    registry = _load_registry(tmp_path)
    reviewer = registry.resolve_role(AgentRole.reviewer)
    prompt = build_specialist_dispatch_prompt(reviewer)
    lowered = prompt.casefold()
    assert "json schema" not in lowered
    assert "output_schema" not in lowered
    assert "set_output" not in lowered
    assert '"findings"' not in prompt
    assert "typed-findings" not in lowered


def test_typed_findings_feed_the_verifier_directly(tmp_path: Path) -> None:
    """Typed handoff findings queue verifier dispatches without prose aggregation."""
    from mergecraft.agents.structured_handoff import (
        parse_specialist_handoff,
        verification_plan_from_handoff,
    )
    from mergecraft.agents.verifier import VERIFIER_SEVERITIES

    handoff = parse_specialist_handoff(_SAMPLE_HANDOFF)
    plan = verification_plan_from_handoff(handoff, budget=4)
    assert plan.budget == 4
    assert len(plan.dispatch) == 1
    dispatch = plan.dispatch[0]
    assert dispatch.finding.path == "internal/store/checkout.go"
    assert dispatch.finding.severity in VERIFIER_SEVERITIES
    assert "Verify one finding" in dispatch.brief
    assert plan.skipped_below_severity == []


# ---------------------------------------------------------------------------
# W14.2 / #261 — case-insensitive detect, exact-case split
# ---------------------------------------------------------------------------
#
# ``parse_specialist_handoff`` detects the marker with ``casefold()`` but then
# splits with ``text.partition(marker)`` against the lowercase literal. A
# specialist that emits ``---TYPED-FINDINGS---`` therefore passes the detect,
# gets an empty ``tail``, and the payload becomes ``""`` — which
# ``json.loads`` rejects, so the whole handoff raises instead of yielding the
# findings the specialist actually reported.

_MARKER_CASINGS = (
    pytest.param("---TYPED-FINDINGS---", id="upper"),
    pytest.param("---Typed-Findings---", id="title"),
    pytest.param("---tYpEd-FiNdInGs---", id="mixed"),
    pytest.param("---TYPED-findings---", id="upper-head"),
    pytest.param("---typed-FINDINGS---", id="upper-tail"),
)

_FINDINGS_JSON = """\
[
  {
    "path": "internal/store/checkout.go",
    "body": "Concurrent checkouts can double-spend inventory.",
    "severity": "Major",
    "line": 142
  }
]
"""

_REASONING = "I traced the checkout path and the race is real.\n"


def _handoff_text(marker: str, *, payload: str = _FINDINGS_JSON) -> str:
    return f"{_REASONING}\n{marker}\n{payload}"


@pytest.mark.xfail(
    reason="green after W16: exact-case partition empties the payload for a mixed-case marker",
    strict=False,
)
@pytest.mark.parametrize("marker", _MARKER_CASINGS)
def test_mixed_case_marker_parses_the_findings_payload(marker: str) -> None:
    """#261 — a marker that passes the case-insensitive detect must also split.

    The failure mode is not "no findings": ``payload`` becomes the empty
    string, so ``json.loads`` raises and the caller sees a ``ValueError``
    wrapping a ``JSONDecodeError`` rather than the finding.
    """
    from mergecraft.agents.structured_handoff import parse_specialist_handoff

    handoff = parse_specialist_handoff(_handoff_text(marker))

    assert len(handoff.findings) == 1
    finding = handoff.findings[0]
    assert finding.path == "internal/store/checkout.go"
    assert finding.severity == "Major"
    assert finding.line == 142
    assert "double-spend" in finding.body


@pytest.mark.xfail(
    reason="green after W16: the mixed-case marker must not be left in the reasoning",
    strict=False,
)
@pytest.mark.parametrize("marker", _MARKER_CASINGS)
def test_mixed_case_marker_is_stripped_from_the_reasoning(marker: str) -> None:
    """The prose half must stop at the marker regardless of its casing.

    Without this, a fix that only rescues the payload could still hand the
    orchestrator a ``reasoning`` blob containing the marker and the raw JSON.
    """
    from mergecraft.agents.structured_handoff import parse_specialist_handoff

    handoff = parse_specialist_handoff(_handoff_text(marker))

    assert "race is real" in handoff.reasoning
    assert marker not in handoff.reasoning
    assert "typed-findings" not in handoff.reasoning.casefold()
    assert "double-spend" not in handoff.reasoning


@pytest.mark.xfail(
    reason="green after W16: an empty array tail after a mixed-case marker must parse",
    strict=False,
)
@pytest.mark.parametrize("marker", _MARKER_CASINGS)
def test_mixed_case_marker_with_an_empty_array_yields_no_findings(marker: str) -> None:
    """A specialist that found nothing must not raise either.

    ``[]`` after a mixed-case marker is the "clean review" shape. Today it
    raises for the same reason a populated array does, so the empty case
    needs its own pin — the fix must not special-case a falsy tail back to
    ``"[]"`` and call it done.
    """
    from mergecraft.agents.structured_handoff import parse_specialist_handoff

    handoff = parse_specialist_handoff(_handoff_text(marker, payload="[]"))

    assert handoff.findings == ()
    assert "race is real" in handoff.reasoning


def test_lowercase_marker_still_parses() -> None:
    """Green guard: the documented lowercase casing is correct today.

    W16 replaces the ``partition`` with a casefolded index lookup; the arm
    that already works must not regress.
    """
    from mergecraft.agents.structured_handoff import parse_specialist_handoff

    handoff = parse_specialist_handoff(_handoff_text("---typed-findings---"))

    assert len(handoff.findings) == 1
    assert handoff.findings[0].path == "internal/store/checkout.go"
    assert "race is real" in handoff.reasoning
    assert "---typed-findings---" not in handoff.reasoning


def test_no_marker_at_all_yields_prose_only() -> None:
    """Green guard: absent marker keeps the whole text as reasoning, no findings."""
    from mergecraft.agents.structured_handoff import parse_specialist_handoff

    handoff = parse_specialist_handoff("Just prose, no typed tail here.")

    assert handoff.findings == ()
    assert handoff.reasoning == "Just prose, no typed tail here."


def test_malformed_tail_still_raises_a_value_error() -> None:
    """Green guard: W16 must not swallow a genuinely invalid tail.

    The error-message contract matters — the caller distinguishes "the
    specialist emitted garbage" from "mergeCraft dropped the payload".
    """
    from mergecraft.agents.structured_handoff import parse_specialist_handoff

    with pytest.raises(ValueError, match="not valid JSON"):
        parse_specialist_handoff(_handoff_text("---typed-findings---", payload="{not json"))


def test_non_array_tail_still_raises_a_value_error() -> None:
    """Green guard: a JSON object tail is still a contract violation."""
    from mergecraft.agents.structured_handoff import parse_specialist_handoff

    with pytest.raises(ValueError, match="must be a JSON array"):
        parse_specialist_handoff(_handoff_text("---typed-findings---", payload='{"path": "a"}'))
