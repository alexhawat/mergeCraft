"""Shared minimal repository configuration for policy tests.

Exports:
    write_repo_config: Write a valid source-controlled test configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def write_repo_config(tmp_path: Path, *, extra_yaml: str = "") -> None:
    """Write a minimal config under the test repository, with optional settings."""
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    body = "models:\n  - anthropic/claude-sonnet\n  - openai/gpt-5.3-codex"
    if extra_yaml.strip():
        body = f"{body}\n{extra_yaml.strip()}"
    (cfg_dir / "config.yaml").write_text(body + "\n", encoding="utf-8")
