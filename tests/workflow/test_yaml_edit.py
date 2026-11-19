"""Behavioral compatibility for the shared workflow YAML editing API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.cli import tracing_logfire_wf_yaml as logfire_yaml
from mergecraft.cli import workflow_wf_yaml as provider_yaml
from mergecraft.workflow import yaml_edit

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


WORKFLOW = """\
# Preserve the workflow author's comments.
jobs:
  review:
    steps:
      - id: review
        uses: alexhawat/mergeCraft@main
        with:
          model: old
          prompt: keep # Preserve unrelated values and comments.
"""


def _replace_model(block: str, step_indent: int) -> tuple[str, bool]:
    """Use the public mapping editor as a step mutation callback."""
    return yaml_edit.insert_owned_keys_into_block(
        block,
        key="with",
        canonical=[("model", "new")],
        env_style=False,
        force=True,
        at_indent=step_indent,
    )


@pytest.mark.parametrize(
    "mutate",
    [yaml_edit.mutate_steps, logfire_yaml._mutate_steps, provider_yaml._mutate_steps],
    ids=["public-engine", "legacy-logfire", "legacy-provider"],
)
def test_mutation_keeps_legacy_result_and_diff_contracts(
    mutate: Callable[..., yaml_edit.WiringChange], tmp_path: Path
) -> None:
    """Old and new entry points return the same result type and preserve text."""
    change = mutate(WORKFLOW, step_selector="primary", mutate_one=_replace_model)

    assert change.old_text == WORKFLOW
    assert change.new_text == WORKFLOW.replace("model: old", "model: new")
    assert change.affected_steps == ["review"]
    assert change.was_modified
    assert type(change) is logfire_yaml.WiringChange
    assert type(change) is provider_yaml.WorkflowChange
    assert type(change) is yaml_edit.WorkflowChange
    workflow_path = tmp_path / "workflow.yml"
    diff = yaml_edit.render_workflow_diff(workflow_path, change)
    assert "-          model: old\n+          model: new\n" in diff
    assert logfire_yaml.render_workflow_diff(workflow_path, change) == diff
    assert provider_yaml.render_workflow_diff(workflow_path, change) == diff
    assert logfire_yaml.__all__ == [
        "DEFAULT_WORKFLOW_RELATIVE_PATH",
        "OWNED_ENV_KEYS",
        "OWNED_WITH_KEYS",
        "REQUIRED_ENV_KEYS",
        "LogfireWorkflowError",
        "WiringChange",
        "apply_logfire_wiring",
        "remove_logfire_wiring",
        "render_workflow_diff",
    ]
    assert provider_yaml.__all__ == [
        "DEFAULT_WORKFLOW_RELATIVE_PATH",
        "WORKFLOW_OWNED_ENV_PREFIXES",
        "WORKFLOW_OWNED_WITH_KEYS",
        "WorkflowChange",
        "WorkflowYamlError",
        "apply_harness_provider_env_wiring",
        "apply_model_prioritize",
        "apply_model_wiring",
        "apply_provider_env_wiring",
        "render_workflow_diff",
    ]


@pytest.mark.parametrize(
    "error_type",
    [logfire_yaml.LogfireWorkflowError, provider_yaml.WorkflowYamlError],
    ids=["legacy-logfire", "legacy-provider"],
)
def test_public_editor_refusal_is_catchable_through_legacy_errors(
    error_type: type[Exception],
) -> None:
    """Both legacy error imports still catch the public editor's refusal."""
    with pytest.raises(error_type) as exc_info:
        yaml_edit.insert_owned_keys_into_block(
            "with:\n  model: old\n",
            key="with",
            canonical=[("model", "new")],
            env_style=False,
            force=False,
        )

    assert type(exc_info.value) is yaml_edit.WorkflowYamlError
    assert type(exc_info.value).__name__ == "LogfireWorkflowError"
    assert str(exc_info.value) == (
        "existing values differ from canonical Logfire wiring: ['model']; pass --force to overwrite"
    )
