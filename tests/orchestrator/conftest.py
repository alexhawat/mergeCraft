"""Shared fixtures for the AP6 orchestrator / pipeline suite."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

_DEFAULT_MODELS_YAML = """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
"""

_ORDERED_PIPELINE_YAML = """
steps:
  - id: classify
    kind: agent
    agent: classifier
  - id: review
    kind: agent
    agent: reviewer
  - id: verify
    kind: agent
    agent: verifier
  - id: submit
    kind: terminal
"""

_CONDITIONAL_PIPELINE_YAML = """
steps:
  - id: review
    kind: agent
    agent: reviewer
    when: "changed_paths matches '**/*.py'"
  - id: docs-only
    kind: agent
    agent: reviewer
    when: "changed_paths matches '**/*.md'"
  - id: verify
    kind: agent
    agent: verifier
  - id: submit
    kind: terminal
"""

_FAN_OUT_PIPELINE_YAML = """
steps:
  - id: lenses
    kind: fan_out
    agents:
      - reviewer
      - verifier
  - id: submit
    kind: terminal
"""

_ON_ERROR_PIPELINE_YAML = """
steps:
  - id: flaky
    kind: agent
    agent: reviewer
    on_error: continue
  - id: verify
    kind: agent
    agent: verifier
    on_error: fail
  - id: submit
    kind: terminal
"""

_TERMINAL_ONLY_PIPELINE_YAML = """
steps:
  - id: submit
    kind: terminal
"""

_HOSTILE_SKIP_VERIFIER_YAML = """
steps:
  - id: review
    kind: agent
    agent: reviewer
  - id: submit
    kind: terminal
"""

_OPERATOR_PIPELINE_YAML = """
steps:
  - id: review
    kind: agent
    agent: reviewer
  - id: verify
    kind: agent
    agent: verifier
  - id: submit
    kind: terminal
"""

_INVALID_AGENT_PIPELINE_YAML = """
steps:
  - id: rogue
    kind: agent
    agent: mergecraft-nonexistent-agent
  - id: submit
    kind: terminal
"""

_SAMPLE_DIFF = """diff --git a/src/widget.py b/src/widget.py
index 1111111..2222222 100644
--- a/src/widget.py
+++ b/src/widget.py
@@ -1 +1,2 @@
+# change
 pass
"""


def write_repo_config(tmp_path: Path, *, extra_yaml: str = "") -> None:
    """Write a minimal ``.mergecraft/config.yaml`` under ``tmp_path``."""
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    body = _DEFAULT_MODELS_YAML.strip()
    if extra_yaml.strip():
        body = f"{body}\n{extra_yaml.strip()}"
    (cfg_dir / "config.yaml").write_text(body + "\n", encoding="utf-8")


def write_pipeline_file(tmp_path: Path, body: str, *, name: str = "pipeline.yaml") -> Path:
    """Write a pipeline YAML file under ``.mergecraft/``."""
    cfg_dir = tmp_path / ".mergecraft"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / name
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path


def write_sample_diff(tmp_path: Path) -> Path:
    """Write a minimal unified diff fixture for ``pipeline show``."""
    diff_path = tmp_path / "sample.diff"
    diff_path.write_text(_SAMPLE_DIFF, encoding="utf-8")
    return diff_path


@pytest.fixture
def ordered_pipeline_yaml() -> str:
    return _ORDERED_PIPELINE_YAML


@pytest.fixture
def conditional_pipeline_yaml() -> str:
    return _CONDITIONAL_PIPELINE_YAML


@pytest.fixture
def fan_out_pipeline_yaml() -> str:
    return _FAN_OUT_PIPELINE_YAML


@pytest.fixture
def on_error_pipeline_yaml() -> str:
    return _ON_ERROR_PIPELINE_YAML


@pytest.fixture
def terminal_only_pipeline_yaml() -> str:
    return _TERMINAL_ONLY_PIPELINE_YAML


@pytest.fixture
def hostile_skip_verifier_yaml() -> str:
    return _HOSTILE_SKIP_VERIFIER_YAML


@pytest.fixture
def operator_pipeline_yaml() -> str:
    return _OPERATOR_PIPELINE_YAML


@pytest.fixture
def invalid_agent_pipeline_yaml() -> str:
    return _INVALID_AGENT_PIPELINE_YAML
