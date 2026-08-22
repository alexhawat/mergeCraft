"""Recall pass — anti-verifier subagent (RC10, D1, D7) — W7.1 RED suite.

Wave plan: ``.ignorelocal/waves/review-convergence-wave-plan.md`` (W7).
Pins ``AgentRole.recall``, ``mergecraft.agents.recall``, and registry wiring.
Implementation lands in W7.2.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from tests.analyzers.support import import_module
from tests.ci.workflow_support import REPO_ROOT

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.config.settings import load_repo_settings
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.shared import REVIEWER_ALLOWED_TOOL_CLASSES, ToolClass
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

_DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
  - google/gemini-3.1-pro-preview
"""

_TERMINAL_PROTOCOL_TOOL = "submit_review_verdict"
_MUTATION_TOOLS = frozenset(
    {
        "push_branch",
        "commit_changes",
        "create_pull_request_review",
        "record_finding_verdict",
        "set_output",
    }
)

_SAMPLE_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,4 @@ def handler():
+    timeout = None
     return value
"""


def _recall_mod() -> Any:
    return import_module("mergecraft.agents.recall")


def _write_config(tmp_path: Path, body: str) -> None:
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(body.strip() + "\n", encoding="utf-8")


def _tool_ctx(tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell="restricted",
            push="restricted",
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def _load_registry(tmp_path: Path) -> object:
    from mergecraft.agents.registry import load_registry

    settings = load_repo_settings(root=tmp_path)
    return load_registry(settings=settings, repo_root=tmp_path)


def _resolve_recall(registry: object) -> object:
    from mergecraft.agents.registry import AgentRole

    return registry.resolve_role(AgentRole.recall)


def _tool_names(registry: object, binding: object, ctx: ToolContext) -> frozenset[str]:
    return frozenset(registry.resolve_tool_names(binding, ctx))


def _draft_agent_row(*, path: str = "src/app.py", line: int = 12, body: str) -> dict[str, object]:
    return {
        "severity": "Major",
        "path": path,
        "line": line,
        "body": body,
    }


def _agent_finding(
    *,
    path: str = "src/app.py",
    start: int = 12,
    body: str,
    severity: str = "Major",
) -> object:
    finding_mod = import_module("mergecraft.analyzers.finding")
    return finding_mod.make_finding(
        tool="mergecraft-agent",
        rule_id="agent:recall-fixture",
        category="Functional Correctness",
        severity=severity,
        confidence="likely",
        message=body,
        path=path,
        start_line=start,
        end_line=start,
        source="agent",
        introduced_by_pr="true",
    )


def test_recall_role_is_registered_with_read_only_tool_classes(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``AgentRole.recall`` uses ``REVIEWER_ALLOWED_TOOL_CLASSES`` (read-only subagent surface)."""
    _write_config(tmp_path, _DEFAULT_MODELS_YAML)
    monkeypatch.chdir(tmp_path)

    from mergecraft.agents.registry import AgentRole

    registry = _load_registry(tmp_path)
    binding = _resolve_recall(registry)

    assert AgentRole.recall.value == "recall"
    assert binding.role is AgentRole.recall
    assert binding.tool_classes == REVIEWER_ALLOWED_TOOL_CLASSES
    assert ToolClass.TERMINAL_PROTOCOL not in binding.tool_classes
    assert ToolClass.REVIEW_WRITE not in binding.tool_classes
    assert ToolClass.VERIFICATION not in binding.tool_classes


def test_recall_pass_receives_the_draft_finding_list() -> None:
    """The recall brief must include the aggregated draft findings plus the diff."""
    recall = _recall_mod()
    draft = [
        _draft_agent_row(body="Missing timeout on retry path."),
        _draft_agent_row(path="src/util.py", line=4, body="Unchecked null before return."),
    ]

    brief = recall.build_recall_pass_brief(
        diff_text=_SAMPLE_DIFF,
        draft_findings=draft,
    )

    assert isinstance(brief, str)
    assert "Missing timeout on retry path." in brief
    assert "Unchecked null before return." in brief
    assert "src/util.py" in brief
    prompt = recall.RECALL_SYSTEM_PROMPT.casefold()
    assert "draft" in prompt
    assert "diff" in prompt


def test_recall_pass_output_excludes_findings_already_drafted() -> None:
    """Novelty filter must delegate to ``findings.dedup.dedupe_findings``, not a second matcher."""
    recall = _recall_mod()

    drafted_body = "Race when two workers claim the same database row."
    paraphrase_body = "Concurrent workers can claim the same row without locking."
    novel_body = "Timeout is never assigned before the retry loop runs."

    draft = [_agent_finding(start=20, body=drafted_body)]
    recalled = [
        _agent_finding(start=20, body=paraphrase_body),
        _agent_finding(start=44, body=novel_body),
    ]

    source = inspect.getsource(recall.filter_novel_recall_findings)
    assert "dedupe_findings" in source

    filtered = recall.filter_novel_recall_findings(draft, recalled)
    bodies = {row.message for row in filtered}
    assert novel_body in bodies
    assert paraphrase_body not in bodies
    assert drafted_body not in bodies
    assert len(filtered) == 1


def test_recall_findings_land_in_the_deferred_lane_regardless_of_claimed_severity() -> None:
    """D1 — recall output is always non-blocking deferred placement."""
    budget = import_module("mergecraft.analyzers.budget")

    critical = _agent_finding(body="Unbounded retry can wedge the queue.", severity="Critical")
    placement = budget.place_findings([critical], inline_budget=0)

    assert isinstance(placement, budget.FindingPlacement)
    assert placement.inline == []
    assert len(placement.deferred) == 1
    assert placement.deferred[0].severity == "Critical"
    assert placement.deferred_section is not None


def test_recall_pass_is_off_by_default_and_on_in_this_repo_config(tmp_path: Path) -> None:
    """D7 — ``review.recallPass`` defaults false; mergeCraft's own config enables it."""
    consumer = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert consumer.review.recall_pass is False

    mergecraft_settings = load_repo_settings(root=REPO_ROOT, load_learnings_files=False)
    assert mergecraft_settings.review.recall_pass is True


def test_recall_pass_respects_the_subagent_budget_and_timeout(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Recall inherits registry ``budget`` / ``timeout_s`` like other subagent roles."""
    _write_config(
        tmp_path,
        _DEFAULT_MODELS_YAML
        + """
agents:
  recall:
    budget: 4
    timeoutS: 90
""",
    )
    monkeypatch.chdir(tmp_path)

    from mergecraft.agents.registry import AgentRole, effective_agent_limits
    from mergecraft.mcp.convergence_runtime import build_recall_dispatch_plan

    registry = _load_registry(tmp_path)
    binding = registry.resolve_role(AgentRole.recall)
    settings = load_repo_settings(root=tmp_path)
    limits = effective_agent_limits(binding, settings=settings)

    assert binding.budget == 4
    assert binding.timeout_s == 90
    assert limits.budget == 4
    assert limits.timeout_s == 90

    plan = build_recall_dispatch_plan(
        diff_text=_SAMPLE_DIFF,
        draft_findings=[],
        binding=binding,
        settings=settings,
        tool_state=_tool_ctx(tmp_path).tool_state,
    )
    assert plan.budget == 4
    assert plan.timeout_s == 90


def test_recall_pass_cannot_call_terminal_or_mutation_tools(tmp_path: Path) -> None:
    """Recall subagent deny-list matches reviewer subagent containment (no terminal or repo writes)."""
    recall = _recall_mod()
    ctx = _tool_ctx(tmp_path)
    registry = _load_registry(tmp_path)
    binding = _resolve_recall(registry)
    names = _tool_names(registry, binding, ctx)

    assert _TERMINAL_PROTOCOL_TOOL not in names
    leaked = names & _MUTATION_TOOLS
    assert not leaked, f"recall role admitted mutation tools: {sorted(leaked)}"

    denied = recall.recall_denied_tool_names(ctx)
    assert denied == subagent_denied_tool_names(ctx)
    assert _TERMINAL_PROTOCOL_TOOL in denied
    assert "push_branch" in denied
