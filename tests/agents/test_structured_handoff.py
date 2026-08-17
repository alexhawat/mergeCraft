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
