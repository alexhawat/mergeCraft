"""Batch HH — Harbor review agent behaviour (#431, D7).

Behaviour tests for ``mergecraft.harbor.agent`` — patch-path resolution, version
parsing, and findings ingestion. Requires the optional ``harbor`` extra
(``uv sync --extra harbor``); skipped when the dependency is absent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip(
    "harbor.agents.installed.base",
    reason="harbor extra required (uv sync --extra harbor)",
)

from harbor.models.agent.context import AgentContext

from mergecraft.harbor.agent import MergecraftReviewAgent, _resolve_patch_path

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


@pytest.mark.parametrize(
    ("instruction", "expected"),
    [
        ("Review task.patch", "task.patch"),
        ("use changes.patch for the diff", "changes.patch"),
        ("no patch mentioned", None),
        ("apply my-fix.patch please", "my-fix.patch"),
    ],
)
def test_resolve_patch_path_prefers_known_candidates(
    instruction: str, expected: str | None
) -> None:
    assert _resolve_patch_path(instruction) == expected


def test_mergecraft_review_agent_name_is_mergecraft() -> None:
    assert MergecraftReviewAgent.name() == "mergecraft"


def test_parse_version_returns_first_non_empty_line() -> None:
    agent = MergecraftReviewAgent(logs_dir=Path("/tmp"))
    assert agent.parse_version("\n\nmergecraft 0.1.0\n") == "mergecraft 0.1.0"
    assert agent.parse_version("") == "unknown"


def test_populate_context_post_run_records_findings_count(tmp_path: Path) -> None:
    findings = {"findings": [{"id": "f1"}, {"id": "f2"}]}
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(findings), encoding="utf-8")

    agent = MergecraftReviewAgent(logs_dir=tmp_path)
    context = AgentContext()
    agent.populate_context_post_run(context)

    assert context.metadata is not None
    assert context.metadata["findings_count"] == 2


def test_populate_context_post_run_tolerates_missing_findings_file(tmp_path: Path) -> None:
    agent = MergecraftReviewAgent(logs_dir=tmp_path)
    context = AgentContext()
    agent.populate_context_post_run(context)
    assert context.metadata is None or "findings_count" not in (context.metadata or {})


def test_build_run_env_prefers_explicit_model_name(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    for key in list(os.environ):
        if key.startswith("MERGECRAFT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MERGECRAFT_MODEL", "from-env")
    agent = MergecraftReviewAgent(logs_dir=tmp_path, model_name="from-model")
    env = agent._build_run_env()
    assert env["MERGECRAFT_MODEL"] == "from-model"
