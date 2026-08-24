"""Surgical YAML mutator for ``mergecraft workflow`` provider/model authoring (#484).

Extends the line-based mutation strategy from
:mod:`mergecraft.cli.tracing_logfire_wf_yaml` — PyYAML parses for assertions only;
owned ``with:`` / ``env:`` keys are edited in-place so comments and unrelated
YAML stay byte-stable.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from mergecraft.cli.tracing_logfire_wf_yaml import (
    DEFAULT_WORKFLOW_RELATIVE_PATH,
    LogfireWorkflowError,
    WiringChange,
    _create_env_block,
    _create_with_block,
    _find_mapping_block,
    _insert_owned_keys_into_block,
    _is_action_uses,
    _mutate_steps,
    _splice_secret,
)

if TYPE_CHECKING:
    from collections.abc import Callable

WORKFLOW_OWNED_WITH_KEYS: tuple[str, ...] = ("model",)

WORKFLOW_OWNED_ENV_PREFIXES: tuple[str, ...] = (
    "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_",
    "LLM_PROVIDER_",
)

WorkflowYamlError = LogfireWorkflowError
WorkflowChange = WiringChange


def _indexed_base_url_key(env_index: int) -> str:
    return f"MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{env_index}"


def _indexed_api_key_key(env_index: int) -> str:
    return f"LLM_PROVIDER_{env_index}_API_KEY"


def _read_workflow_text(workflow_path: Path) -> str:
    try:
        return workflow_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise WorkflowYamlError(f"workflow file not found: {workflow_path}") from exc
    except OSError as exc:
        raise WorkflowYamlError(f"could not read {workflow_path}: {exc}") from exc


def _assert_model_wired(text: str, *, step_identifiers: list[str], model_slug: str) -> None:
    if not step_identifiers:
        return
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WorkflowYamlError(f"mutation produced invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        return
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        return
    targets = set(step_identifiers)
    for job_def in jobs.values():
        if not isinstance(job_def, dict):
            continue
        steps = job_def.get("steps")
        if not isinstance(steps, list):
            continue
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str) or not _is_action_uses(uses):
                continue
            step_id = step.get("id") or step.get("name") or f"step[{i}]"
            if step_id not in targets:
                continue
            with_map = step.get("with")
            if not isinstance(with_map, dict) or with_map.get("model") != model_slug:
                raise WorkflowYamlError(
                    f"mergeCraft step {step_id!r} missing with.model={model_slug!r} after mutation"
                )


def _assert_provider_env_wired(
    text: str,
    *,
    step_identifiers: list[str],
    env_index: int,
    base_url: str,
    secret_name: str,
) -> None:
    if not step_identifiers:
        return
    base_key = _indexed_base_url_key(env_index)
    api_key = _indexed_api_key_key(env_index)
    expected_api = f"${{{{ secrets.{secret_name} }}}}"
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WorkflowYamlError(f"mutation produced invalid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        return
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        return
    targets = set(step_identifiers)
    for job_def in jobs.values():
        if not isinstance(job_def, dict):
            continue
        steps = job_def.get("steps")
        if not isinstance(steps, list):
            continue
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str) or not _is_action_uses(uses):
                continue
            step_id = step.get("id") or step.get("name") or f"step[{i}]"
            if step_id not in targets:
                continue
            env_map = step.get("env")
            if not isinstance(env_map, dict):
                raise WorkflowYamlError(f"mergeCraft step {step_id!r} missing env: mapping")
            if env_map.get(base_key) != base_url:
                raise WorkflowYamlError(
                    f"mergeCraft step {step_id!r} missing env.{base_key}={base_url!r}"
                )
            if env_map.get(api_key) != expected_api:
                raise WorkflowYamlError(
                    f"mergeCraft step {step_id!r} missing env.{api_key}={expected_api!r}"
                )


def apply_provider_env_wiring(
    *,
    workflow_path: Path,
    env_index: int,
    label: str,
    base_url: str,
    secret_name: str,
    step_selector: str,
    force: bool,
) -> WorkflowChange:
    """Insert indexed custom-provider ``env:`` keys into a mergeCraft step."""
    _ = label  # operator context only; workflow keys are index-based
    text = _read_workflow_text(workflow_path)
    validated_secret = _splice_secret(secret_name)
    base_key = _indexed_base_url_key(env_index)
    api_key = _indexed_api_key_key(env_index)
    env_canonical: list[tuple[str, str]] = [
        (base_key, base_url),
        (api_key, f"${{{{ secrets.{validated_secret} }}}}"),
    ]

    def _do(block: str, step_indent: int) -> tuple[str, bool]:
        block2, mod_env = _insert_owned_keys_into_block(
            block,
            key="env",
            canonical=env_canonical,
            env_style=True,
            force=force,
            at_indent=step_indent,
        )
        if not mod_env and _find_mapping_block(block2, "env", at_indent=step_indent) is None:
            block2 = _create_env_block(block2, env_canonical[0], at_indent=step_indent)
            mod_env = True
        block3, mod_env2 = _insert_owned_keys_into_block(
            block2,
            key="env",
            canonical=env_canonical,
            env_style=True,
            force=force,
            at_indent=step_indent,
        )
        return block3, mod_env or mod_env2

    def _post_check(cur_text: str, *, step_identifiers: list[str]) -> None:
        _assert_provider_env_wired(
            cur_text,
            step_identifiers=step_identifiers,
            env_index=env_index,
            base_url=base_url,
            secret_name=validated_secret,
        )

    return _mutate_steps(
        text,
        step_selector=step_selector,
        mutate_one=_do,
        post_mutation_check=_post_check,
    )


def apply_model_wiring(
    *,
    workflow_path: Path,
    model_slug: str,
    step_selector: str,
    force: bool,
) -> WorkflowChange:
    """Insert or replace ``with.model`` on a selected mergeCraft step."""
    _ = force  # ``model`` is workflow-owned; differing values are always replaced.
    text = _read_workflow_text(workflow_path)
    with_canonical: list[tuple[str, str]] = [("model", model_slug)]

    def _do(block: str, step_indent: int) -> tuple[str, bool]:
        block2, mod_with = _insert_owned_keys_into_block(
            block,
            key="with",
            canonical=with_canonical,
            env_style=False,
            force=True,
            at_indent=step_indent,
        )
        if not mod_with and _find_mapping_block(block2, "with", at_indent=step_indent) is None:
            block2 = _create_with_block(block2, with_canonical, at_indent=step_indent)
            mod_with = True
        return block2, mod_with

    def _post_check(cur_text: str, *, step_identifiers: list[str]) -> None:
        _assert_model_wired(cur_text, step_identifiers=step_identifiers, model_slug=model_slug)

    return _mutate_steps(
        text,
        step_selector=step_selector,
        mutate_one=_do,
        post_mutation_check=_post_check,
    )


def _find_prioritize_step_ids(text: str, model_slug: str, before_slug: str) -> tuple[str, str]:
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise WorkflowYamlError(f"could not parse workflow: {exc}") from exc
    if not isinstance(parsed, dict):
        raise WorkflowYamlError("workflow must be a mapping at the top level")
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        raise WorkflowYamlError("workflow has no jobs: mapping")

    before_ids: list[str] = []
    model_ids: list[str] = []
    for job_name, job_def in jobs.items():
        if not isinstance(job_def, dict):
            continue
        steps = job_def.get("steps")
        if not isinstance(steps, list):
            continue
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str) or not _is_action_uses(uses):
                continue
            step_id = str(step.get("id") or step.get("name") or f"job:{job_name}/step:{i}")
            with_map = step.get("with")
            model = with_map.get("model") if isinstance(with_map, dict) else None
            if model == before_slug:
                before_ids.append(step_id)
            elif model == model_slug:
                model_ids.append(step_id)

    if not before_ids:
        raise WorkflowYamlError(f"no mergeCraft step with with.model={before_slug!r} found")
    if len(before_ids) > 1:
        raise WorkflowYamlError(
            f"ambiguous mergeCraft steps with with.model={before_slug!r}; "
            "exactly one step must match"
        )
    if not model_ids:
        raise WorkflowYamlError(f"no mergeCraft step with with.model={model_slug!r} found")
    if len(model_ids) > 1:
        raise WorkflowYamlError(
            f"ambiguous mergeCraft steps with with.model={model_slug!r}; "
            "exactly one step must match"
        )
    return before_ids[0], model_ids[0]


def apply_model_prioritize(
    *,
    workflow_path: Path,
    model_slug: str,
    before_slug: str,
    force: bool,
) -> WorkflowChange:
    """Promote *model_slug* on the anchor step and demote *before_slug* to a fallback step."""
    original = _read_workflow_text(workflow_path)
    anchor_id, swap_id = _find_prioritize_step_ids(original, model_slug, before_slug)

    intermediate = _mutate_steps(
        original,
        step_selector=anchor_id,
        mutate_one=_model_mutator(model_slug, force),
        post_mutation_check=lambda cur, step_identifiers: _assert_model_wired(
            cur, step_identifiers=step_identifiers, model_slug=model_slug
        ),
    )

    final = _mutate_steps(
        intermediate.new_text,
        step_selector=swap_id,
        mutate_one=_model_mutator(before_slug, force),
        post_mutation_check=lambda cur, step_identifiers: _assert_model_wired(
            cur, step_identifiers=step_identifiers, model_slug=before_slug
        ),
    )
    return WorkflowChange(
        old_text=original,
        new_text=final.new_text,
        affected_steps=[anchor_id, swap_id],
    )


def _model_mutator(model_slug: str, force: bool) -> Callable[[str, int], tuple[str, bool]]:
    with_canonical: list[tuple[str, str]] = [("model", model_slug)]
    _ = force  # model is workflow-owned; always overwrite differing values

    def _do(block: str, step_indent: int) -> tuple[str, bool]:
        block2, mod_with = _insert_owned_keys_into_block(
            block,
            key="with",
            canonical=with_canonical,
            env_style=False,
            force=True,
            at_indent=step_indent,
        )
        if not mod_with and _find_mapping_block(block2, "with", at_indent=step_indent) is None:
            block2 = _create_with_block(block2, with_canonical, at_indent=step_indent)
            mod_with = True
        return block2, mod_with

    return _do


def render_workflow_diff(
    workflow_path: Path, change: WorkflowChange, *, max_lines: int = 200
) -> str:
    """Return a unified-diff text between ``change.old_text`` and ``change.new_text``."""
    rel = str(workflow_path)
    diff = difflib.unified_diff(
        change.old_text.splitlines(keepends=True),
        change.new_text.splitlines(keepends=True),
        fromfile=f"{rel} (current)",
        tofile=f"{rel} (proposed)",
        lineterm="",
    )
    lines = list(diff)
    if len(lines) > max_lines:
        truncation = f"... ({len(lines) - max_lines} more lines truncated)\n"
        lines = [*lines[:max_lines], truncation]
    return "".join(line if line.endswith("\n") else f"{line}\n" for line in lines)


__all__ = [
    "DEFAULT_WORKFLOW_RELATIVE_PATH",
    "WORKFLOW_OWNED_ENV_PREFIXES",
    "WORKFLOW_OWNED_WITH_KEYS",
    "WorkflowChange",
    "WorkflowYamlError",
    "apply_model_prioritize",
    "apply_model_wiring",
    "apply_provider_env_wiring",
    "render_workflow_diff",
]
