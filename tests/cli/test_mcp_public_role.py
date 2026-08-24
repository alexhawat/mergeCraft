"""MP1.1 — public MCP role CLI contracts (RED until MP2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.mcp.public_mcp_support import (
    PUBLIC_TOOL_NAMES,
    RUNTIME_PRIMITIVE_SAMPLES,
    init_git_repo,
    mcp_list_names,
    write_minimal_config,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_list_role_public_prints_exactly_six_names(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    names = mcp_list_names(role="public", cwd=tmp_path)
    assert names == sorted(PUBLIC_TOOL_NAMES)


def test_list_role_reviewer_still_includes_runtime_primitives(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    names = mcp_list_names(role="reviewer", cwd=tmp_path)
    for sample in RUNTIME_PRIMITIVE_SAMPLES:
        assert sample in names


def test_unknown_role_rejected(tmp_path: Path) -> None:
    init_git_repo(tmp_path)
    write_minimal_config(tmp_path)
    public = runner.invoke(
        app,
        ["mcp", "list", "--role", "public", "--cwd", str(tmp_path)],
    )
    assert public.exit_code == 0, public.output
    typo = runner.invoke(
        app,
        ["mcp", "list", "--role", "pubic", "--cwd", str(tmp_path)],
    )
    assert typo.exit_code != 0
