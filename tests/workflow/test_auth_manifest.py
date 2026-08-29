"""Direct tests for workflow auth-manifest parsing (wave plan 11 / W7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.cli.support_agent_roster import (
    WORKFLOW_GATED_STEP,
    WORKFLOW_INDEXED_STEP,
    scaffold_workflow_file,
)

from mergecraft.workflow.auth_manifest import (
    WorkflowAuthManifestError,
    is_mergecraft_action_uses,
    parse_auth_manifest,
    secret_name_to_provider_label,
    workflow_secret_bindings,
)


def test_is_mergecraft_action_uses_requires_ref() -> None:
    assert is_mergecraft_action_uses("alexhawat/mergeCraft@pre-0.0.1")
    assert not is_mergecraft_action_uses("alexhawat/mergeCraft@")
    assert not is_mergecraft_action_uses("actions/checkout@v4")


def test_parse_auth_manifest_reads_indexed_provider(tmp_path: Path) -> None:
    workflow_path = scaffold_workflow_file(tmp_path, WORKFLOW_INDEXED_STEP)
    labels = parse_auth_manifest(workflow_path)
    assert "nous" in labels


def test_parse_auth_manifest_reads_secret_gated_provider(tmp_path: Path) -> None:
    workflow_path = scaffold_workflow_file(tmp_path, WORKFLOW_GATED_STEP)
    labels = parse_auth_manifest(workflow_path)
    assert "openai" in labels


def test_parse_auth_manifest_missing_file_raises() -> None:
    with pytest.raises(WorkflowAuthManifestError, match=r"could not read"):
        parse_auth_manifest(Path("/no/such/mergecraft.yml"))


def test_secret_name_to_provider_label_maps_known_keys() -> None:
    assert secret_name_to_provider_label("ANTHROPIC_API_KEY") == "anthropic"
    assert secret_name_to_provider_label("CURSOR_API_KEY") == "cursor"


def test_workflow_secret_bindings_reads_secret_refs(tmp_path: Path) -> None:
    workflow_path = scaffold_workflow_file(tmp_path, WORKFLOW_INDEXED_STEP)
    bindings = workflow_secret_bindings(workflow_path)
    assert ("LLM_PROVIDER_1_API_KEY", "NOUS_API_KEY") in bindings
    assert ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY") in bindings
