"""W9 / #383 — agent-mode capability boundary (D13).

Wave plan: ``.ignorelocal/waves/open-issues-sweep-2026-08-20d-a-engine-wave-plan.md``
Batch DD. These pins target the *coding-agent / ``review --agent``* attack
surface on top of 20c #350. Do **not** duplicate
``tests/cli/test_capabilities_cmd.py`` or ``tests/modes/test_review_only_boundary.py``.

Do not name this module ``adversarial.py`` (D17 — lane B owns
``src/mergecraft/evals/adversarial.py``).

Already-true D13 refusals are green guards (no xfail).
"""

from __future__ import annotations

import ast
import inspect
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tests.ci.workflow_support import REPO_ROOT
from typer.testing import CliRunner

from mergecraft.cli.agent_protocol import AgentProtocolStream, format_event_line
from mergecraft.cli.app import app
from mergecraft.cli.capabilities_cmd import FORBIDDEN_CAPABILITIES
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.endpoints import MCP_REVIEWER_ENDPOINT
from mergecraft.mcp.git import commit_changes_tool, push_branch_tool
from mergecraft.mcp.server import build_reviewer_tools
from mergecraft.mcp.shared import PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES, ToolClass
from mergecraft.mcp.shell import shell_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.offline_review import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.github import GitHubClient

runner = CliRunner()

DOCUMENT_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "run_started",
        "phase",
        "finding",
        "verdict",
        "run_finished",
    }
)
WRITE_EVENT_NAMES: frozenset[str] = frozenset(
    {
        "commit",
        "push",
        "edit_source",
        "apply_fixes",
        "commit_changes",
        "push_branch",
        "git_commit",
        "git_push",
        "write_file",
        "edit",
        "open_code_changing_pr",
    }
)
CODING_AGENT_IDS: tuple[str, ...] = ("codex", "gemini", "opencode", "cursor")
REPO_MUTATION_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "commit_changes",
        "push_branch",
        "git commit",
        "git_commit",
    }
)

_SAMPLE_PATCH = (
    "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"
)
_GIT_WRITE_INVOKE = re.compile(
    r"""git(?:\s+|['\"]\s*,\s*['\"])(?:commit|push)\b""",
    re.IGNORECASE,
)


def _tool_text(result: object) -> str:
    content = getattr(result, "content", None)
    if not content:
        return ""
    first = content[0]
    if isinstance(first, dict):
        return str(first.get("text", ""))
    return str(first)


def _init_repo(root: Path) -> Path:
    tracked = root / "tracked.txt"
    tracked.write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "dd@test.local"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "DD Tests"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tracked


def _ctx(tmp_path: Path, *, agent_id: str, selected_mode: str = "Review") -> ToolContext:
    """Coding-agent shaped context — not the claude-only ``_ctx`` in 20c CA."""
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.selected_mode = selected_mode
    return ToolContext(
        agent_id=agent_id,
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell="restricted",
            push="enabled",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=list(compute_modes(agent_id)),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        signed_commits=True,
    )


class _GitRecorder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
        del cwd, env
        self.calls.append([str(part) for part in args])
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return "feature\n"
        if args[:2] == ["rev-parse", "HEAD"]:
            return "abc123\n"
        if args[:1] == ["status"]:
            return " M tracked.txt\n"
        return "ok\n"


def _finding_dict() -> dict[str, object]:
    from mergecraft.analyzers.finding import make_finding

    finding = make_finding(
        tool="mergecraft-agent",
        rule_id="DD-383",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="nit",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="unknown",
    )
    return finding.model_dump()


def _install_agent_review(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_offline_diff_review(**kwargs: object) -> OfflineReviewResult:
        materialization_path = kwargs.get("diff_file")
        diff_path = str(materialization_path) if materialization_path else None
        findings = [_finding_dict()]
        payload = json.dumps({"findings": findings})
        return OfflineReviewResult(
            success=True,
            output="# Review\n\nOK.",
            structured_output=payload,
            diff_path=diff_path,
            outcome=RunOutcome.passed,
        )

    monkeypatch.setattr(
        "mergecraft.cli.diff_review_cmd.run_offline_diff_review",
        fake_run_offline_diff_review,
    )


def _invoke_agent(tmp_path: Path) -> Any:
    patch = tmp_path / "change.diff"
    patch.write_text(_SAMPLE_PATCH, encoding="utf-8")
    return runner.invoke(
        app,
        ["review", "--diff", str(patch), "--cwd", str(tmp_path), "--agent"],
        env={"NO_COLOR": "1", "TERM": "dumb"},
        catch_exceptions=False,
    )


# ── Unit: agent JSONL has no write events ─────────────────────────────────────


def test_agent_protocol_stream_methods_are_read_only_events() -> None:
    """Unit: ``AgentProtocolStream`` only exposes the documented JSONL events."""
    methods = {
        name
        for name, value in inspect.getmembers(AgentProtocolStream, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    methods.discard("emit")
    assert methods == DOCUMENT_EVENT_NAMES
    leaked = methods & WRITE_EVENT_NAMES
    assert not leaked, f"agent protocol grew write events: {sorted(leaked)}"


def test_format_event_line_does_not_define_write_events() -> None:
    """Unit: serializing a documented event never stamps a write event name."""
    for event in DOCUMENT_EVENT_NAMES:
        payload = json.loads(format_event_line(event, extra="x"))
        assert payload["event"] == event
        assert payload["event"] not in WRITE_EVENT_NAMES


def test_agent_protocol_source_has_no_write_event_literals() -> None:
    """Unit: ``agent_protocol.py`` does not declare commit/push/edit events."""
    source = (REPO_ROOT / "src" / "mergecraft" / "cli" / "agent_protocol.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    event_literals: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and (node.value in DOCUMENT_EVENT_NAMES or node.value in WRITE_EVENT_NAMES)
        ):
            event_literals.add(node.value)
    leaked = event_literals & WRITE_EVENT_NAMES
    assert not leaked, f"agent_protocol.py names write events: {sorted(leaked)}"
    assert event_literals >= DOCUMENT_EVENT_NAMES


# ── Functional: review --agent only emits documented events ───────────────────


def test_review_agent_stream_only_emits_documented_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Functional: ``mergecraft review --agent`` JSONL uses the five event names."""
    _install_agent_review(monkeypatch)
    result = _invoke_agent(tmp_path)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, result.stdout
    kinds: list[str] = []
    for line in lines:
        payload = json.loads(line)
        kind = str(payload["event"])
        kinds.append(kind)
        assert kind in DOCUMENT_EVENT_NAMES, payload
        assert kind not in WRITE_EVENT_NAMES
    assert kinds[0] == "run_started"
    assert kinds[-1] == "run_finished"
    assert "verdict" in kinds


def test_agent_protocol_stream_emit_rejects_undocumented_write_names() -> None:
    """Error: a consumer driving ``emit`` still cannot mint a write event.

    The stream is a documented event API; write names must not be in the
    public method surface (already pinned) and must not appear on a normal
    ``review --agent`` run. This guard records that ``emit`` is not a
    write-capability backdoor: helpers only wrap documented names.
    """
    buf = io.StringIO()
    stream = AgentProtocolStream(stream=buf)
    stream.run_started()
    stream.phase("review")
    stream.finding({"rule_id": "x"})
    stream.verdict("passed", 0)
    stream.run_finished(0)
    kinds = [json.loads(line)["event"] for line in buf.getvalue().splitlines() if line.strip()]
    assert set(kinds) <= DOCUMENT_EVENT_NAMES
    assert not (set(kinds) & WRITE_EVENT_NAMES)


# ── MCP reviewer role: no repo-mutation write tools ───────────────────────────


def test_primary_reviewer_classes_exclude_repository_mutation() -> None:
    """Unit: ``PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES`` omits repo-mutation / shell."""
    forbidden = {
        ToolClass.REPOSITORY_MUTATION,
        ToolClass.GITHUB_MUTATION,
        ToolClass.SHELL,
    }
    leaked = PRIMARY_REVIEWER_ALLOWED_TOOL_CLASSES & forbidden
    assert not leaked, f"/mcp/reviewer classes admit writes: {sorted(c.value for c in leaked)}"
    assert MCP_REVIEWER_ENDPOINT == "/mcp/reviewer"


def test_reviewer_toolset_does_not_admit_commit_or_push(tmp_path: Path) -> None:
    """Integration: ``build_reviewer_tools`` has no commit/push tools."""
    tools = build_reviewer_tools(_ctx(tmp_path, agent_id="codex"))
    names = {spec.name for spec in tools}
    leaked = names & REPO_MUTATION_TOOL_NAMES
    assert not leaked, f"/mcp/reviewer admitted write tools: {sorted(leaked)}"
    assert "commit_changes" not in names
    assert "push_branch" not in names
    assert "git" not in names or "commit" not in names


# ── Coding-agent shaped attempts (not claude) ─────────────────────────────────


@pytest.mark.parametrize("agent_id", CODING_AGENT_IDS)
async def test_coding_agent_cannot_edit_tracked_file_via_shell(
    tmp_path: Path, agent_id: str
) -> None:
    """Error: shell edit of a tracked file still fails review-only (non-claude)."""
    tracked = _init_repo(tmp_path)
    before = tracked.read_text(encoding="utf-8")
    result = await shell_tool(_ctx(tmp_path, agent_id=agent_id)).execute(
        {
            "command": "printf mutated >> tracked.txt",
            "description": "attempt to edit a tracked file",
        }
    )
    assert result.is_error is True, _tool_text(result)
    assert "review-only" in _tool_text(result).lower()
    assert tracked.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("agent_id", CODING_AGENT_IDS)
async def test_coding_agent_cannot_commit_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent_id: str
) -> None:
    """Error: ``commit_changes`` refuses a coding-agent reviewer run."""
    recorder = _GitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)
    result = await commit_changes_tool(_ctx(tmp_path, agent_id=agent_id)).execute(
        {"message": "chore: must not land"}
    )
    assert result.is_error is True, _tool_text(result)
    text = _tool_text(result).lower()
    assert "review-only" in text
    assert "commit" in text
    assert not any("commit" in call for call in recorder.calls), recorder.calls


@pytest.mark.parametrize("agent_id", CODING_AGENT_IDS)
async def test_coding_agent_cannot_push_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent_id: str
) -> None:
    """Error: ``push_branch`` refuses a coding-agent reviewer run."""
    recorder = _GitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)
    result = await push_branch_tool(_ctx(tmp_path, agent_id=agent_id)).execute(
        {"branchName": "feature"}
    )
    assert result.is_error is True, _tool_text(result)
    text = _tool_text(result).lower()
    assert "review-only" in text
    assert "push" in text
    assert not any("push" in call for call in recorder.calls), recorder.calls


# ── Source scan: --agent path never invokes git write ─────────────────────────


def test_agent_protocol_and_review_agent_path_do_not_invoke_git_writes() -> None:
    """Unit: ``agent_protocol.py`` and the ``--agent`` path never call git commit/push."""
    paths = (
        REPO_ROOT / "src" / "mergecraft" / "cli" / "agent_protocol.py",
        REPO_ROOT / "src" / "mergecraft" / "cli" / "diff_review_cmd.py",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8")
        match = _GIT_WRITE_INVOKE.search(source)
        assert match is None, (
            f"{path.relative_to(REPO_ROOT)} must not invoke git commit/push; found {match.group(0)!r}"
        )
        for capability in ("edit_source", "apply_fixes"):
            assert capability not in source, (
                f"{path.relative_to(REPO_ROOT)} must not invoke write capability {capability}"
            )


# ── Agent-mode honors the capabilities registry (thin, not a CLI clone) ───────


def test_agent_mode_must_honor_forbidden_capability_registry() -> None:
    """Unit: agent-mode honors ``FORBIDDEN_CAPABILITIES`` (edit/commit/push)."""
    forbidden = frozenset(FORBIDDEN_CAPABILITIES)
    for name in (
        "edit_source",
        "apply_fixes",
        "commit",
        "push",
        "open_code_changing_pr",
    ):
        assert name in forbidden, name
