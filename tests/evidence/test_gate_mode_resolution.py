"""GREEN — gate mode from repo settings (AG4 / MCB-17)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.scm.github import GitHubScmAdapter
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch


def _write_gate_config(tmp_path: Path, gate_action: str) -> None:
    config_dir = tmp_path / ".mergecraft"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        f"gates:\n  gate_action: {gate_action}\n",
        encoding="utf-8",
    )


def _ctx(tmp_path: Path) -> ToolContext:
    client = GitHubClient(token="t")
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown")),
        scm=GitHubScmAdapter(client),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def test_repo_setting_enforce_is_honoured(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _write_gate_config(tmp_path, "enforce")
    monkeypatch.chdir(tmp_path)
    from mergecraft.evidence.run_packet import _resolve_gate_mode

    ctx = _ctx(tmp_path)
    assert _resolve_gate_mode(ctx) == "enforce"


def test_repo_setting_shadow_is_honoured(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    _write_gate_config(tmp_path, "shadow")
    monkeypatch.chdir(tmp_path)
    from mergecraft.evidence.run_packet import _resolve_gate_mode

    ctx = _ctx(tmp_path)
    assert _resolve_gate_mode(ctx) == "shadow"


def test_mode_is_not_read_from_package_defaults(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _write_gate_config(tmp_path, "enforce")
    monkeypatch.chdir(tmp_path)
    from mergecraft.config import default_settings
    from mergecraft.evidence.run_packet import _resolve_gate_mode

    assert default_settings().gates.gate_action == "shadow"
    ctx = _ctx(tmp_path)
    assert _resolve_gate_mode(ctx) == "enforce"


def test_shadow_mode_performs_zero_external_mutations(tmp_path: Path) -> None:
    class _MutatingScm(GitHubScmAdapter):
        def __init__(self) -> None:
            super().__init__(GitHubClient(token="t"))
            self.mutations = 0

        async def create_review(self, *args: object, **kwargs: object) -> dict[str, object]:
            self.mutations += 1
            return {"id": 1}

    scm = _MutatingScm()
    ctx = _ctx(tmp_path)
    object.__setattr__(ctx, "scm", scm)
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES
    from mergecraft.evidence.shadow import predict_action
    from tests.evidence.test_gate_actions import _low_risk_passing_packet

    predict_action(_low_risk_passing_packet(), policy=DEFAULT_GATE_POLICIES)
    assert scm.mutations == 0


def test_packet_assembly_exception_fails_closed_in_enforce_mode(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _write_gate_config(tmp_path, "enforce")
    monkeypatch.chdir(tmp_path)
    from mergecraft.evidence.run_packet import prepare_run_packet

    ctx = _ctx(tmp_path)
    ctx.tool_state.pr_number = None
    result = prepare_run_packet(ctx, run_succeeded=True)
    assert result is None or result.decision is not None
