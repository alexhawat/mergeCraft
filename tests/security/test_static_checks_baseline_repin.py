"""Trusted ``run_static_checks`` re-pins the read-only integrity baseline.

A trusted run executes the repo's own gates in place, and gates write build
output into the checkout (``make`` targets that build ``dist/``, regenerate docs).
Like ``checkout_pr`` (#989), the tool re-pins the baseline at that boundary, after
first checking nothing changed since the last pin, so mergeCraft's own gate run
does not fail the review closed while an agent's write still does.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.static_checks import run_static_checks_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_checks import StaticCheckConfig
from mergecraft.security.review_integrity import TreeBaseline, hash_tree
from mergecraft.utils.github import GitHubClient

# A gate that builds a wheel into ``dist/`` (gitignored, but still hashed).
_BUILD_GATE = f"{sys.executable} -c \"import pathlib; p = pathlib.Path('dist'); p.mkdir(exist_ok=True); (p / 'pkg.whl').write_text('built')\""


def _ctx(tmp_path: Path) -> tuple[ToolContext, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("print('reviewed')\n", encoding="utf-8")
    (repo / ".gitignore").write_text("dist/\n", encoding="utf-8")
    ctx = ToolContext(
        agent_id="opencode",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown"), shell="enabled"),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("opencode"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(repo)),
        mcp_server_url="",
        tmpdir=str(tmp_path / "run"),
        static_checks=[StaticCheckConfig(name="build", command=_BUILD_GATE)],
        static_checks_enabled=True,
        trust_tier="trusted",
    )
    ctx.tool_state.review_tree_baseline = TreeBaseline(root=repo, digest=hash_tree(repo))
    return ctx, repo


async def _run(ctx: ToolContext) -> dict[str, Any]:
    result = await run_static_checks_tool(ctx).execute({})
    return json.loads(result.content[0]["text"])


@pytest.mark.asyncio
async def test_gate_build_output_does_not_fail_the_review(tmp_path: Path) -> None:
    ctx, repo = _ctx(tmp_path)

    payload = await _run(ctx)

    assert payload["checks"][0]["status"] == "passed", payload
    assert (repo / "dist" / "pkg.whl").read_text(encoding="utf-8") == "built"
    ctx.tool_state.review_tree_baseline.verify()


@pytest.mark.asyncio
async def test_a_change_after_the_gate_run_still_fails(tmp_path: Path) -> None:
    ctx, repo = _ctx(tmp_path)
    await _run(ctx)

    (repo / "app.py").write_text("tampered\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="checkout integrity failure"):
        ctx.tool_state.review_tree_baseline.verify()


@pytest.mark.asyncio
async def test_the_re_pin_does_not_absorb_a_change_made_before_it(tmp_path: Path) -> None:
    """An ignored file planted before the call is caught, not swept into the new pin."""
    ctx, repo = _ctx(tmp_path)
    (repo / "dist").mkdir()
    (repo / "dist" / "planted.whl").write_text("agent wrote this", encoding="utf-8")

    await _run(ctx)

    with pytest.raises(RuntimeError, match="before run_static_checks"):
        ctx.tool_state.review_tree_baseline.verify()
