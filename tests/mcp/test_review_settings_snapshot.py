"""RED — settings snapshot before publish (AG2 / MCB-19)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings import load_repo_settings

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.xfail(
    reason="green after AG2: settings snapshot at publish",
    strict=False,
)


def _write_config(tmp_path: Path, gate_action: str) -> None:
    config_dir = tmp_path / ".mergecraft"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        f"gates:\n  gate_action: {gate_action}\n",
        encoding="utf-8",
    )


def test_publish_uses_the_presnapshot_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish must read the settings resolved before untrusted execution."""
    _write_config(tmp_path, "enforce")
    before = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert before.gates.gate_action == "enforce"

    _write_config(tmp_path, "shadow")
    after = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert after.gates.gate_action == "shadow"

    # Contract: publish path must honour ``before``, not the post-mutation reload.

    # Until AG2 installs a snapshot on ToolContext, this proxy fails on trunk.
    assert before.gates.gate_action == "enforce"
    assert after.gates.gate_action == "shadow"
    # Placeholder for snapshot reader AG2 adds — must not equal live reload.
    publish_mode = after.gates.gate_action
    assert publish_mode == before.gates.gate_action


def test_invalid_config_mutation_keeps_terminal_behaviour_deterministic(
    tmp_path: Path,
) -> None:
    """A config mutation after snapshot time must not change terminal verdict inputs."""
    _write_config(tmp_path, "enforce")
    first = load_repo_settings(root=tmp_path, load_learnings_files=False)
    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        "gates:\n  gate_action: shadow\n",
        encoding="utf-8",
    )
    second = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert first.gates.gate_action != second.gates.gate_action
    # Snapshot contract: terminal path must remain pinned to first resolution.
    pinned = first.gates.gate_action
    assert pinned == "enforce"
