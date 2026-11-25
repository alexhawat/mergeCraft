"""The ``local_files`` tracing sink path is the literal default (#1562).

``_resolve_local_path`` claimed to resolve the sink path against
``GITHUB_WORKSPACE``, but its only caller passed ``None`` and the workspace
branch was unreachable; the dead branch is gone. The sink path is the literal
``.mergecraft/traces/`` whether or not ``GITHUB_WORKSPACE`` is set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.action.inputs import resolve_tracing_from_action_inputs

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _jsonl_sink_path(monkeypatch: pytest.MonkeyPatch, workspace: Path | None) -> str:
    """Resolve the local ``jsonl_file`` sink path for one workspace setting."""
    monkeypatch.setenv("INPUT_TRACING", "true")
    monkeypatch.setenv("INPUT_TRACING_TO", "local_files")
    monkeypatch.delenv("INPUT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("INPUT_OTEL_ENDPOINT", raising=False)
    monkeypatch.delenv("MERGECRAFT_TRACING_TO", raising=False)
    if workspace is None:
        monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    else:
        monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))
    resolved = resolve_tracing_from_action_inputs()
    sinks = resolved["sinks"]
    assert sinks == [{"type": "jsonl_file", "path": ".mergecraft/traces/"}]
    return str(sinks[0]["path"])


def test_local_sink_path_is_the_default_without_a_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``GITHUB_WORKSPACE``: the sink path is ``.mergecraft/traces/``."""
    assert _jsonl_sink_path(monkeypatch, None) == ".mergecraft/traces/"


def test_local_sink_path_is_the_default_with_a_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A set ``GITHUB_WORKSPACE`` does not change the sink path."""
    assert _jsonl_sink_path(monkeypatch, tmp_path) == ".mergecraft/traces/"
