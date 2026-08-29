"""Parse CI auth manifest from consumer ``mergecraft.yml`` workflow files (D1 / W7)."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_WORKFLOW_RELATIVE_PATH = ".github/workflows/mergecraft.yml"
_ACTION_USES = "alexhawat/mergeCraft"

_SECRET_REF_RE = re.compile(r"^\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}$")
_INDEXED_LABEL_RE = re.compile(r"^LLM_PROVIDER_(\d+)$")
_INDEXED_CREDENTIAL_RE = re.compile(r"^LLM_PROVIDER_(\d+)_(.+)$")

_UNREGISTERED_FLAT_SECRETS: dict[str, tuple[str, ...]] = {
    "cursor": ("CURSOR_API_KEY",),
}


class WorkflowAuthManifestError(ValueError):
    """Raised when a workflow file cannot be parsed as an auth manifest."""


def is_mergecraft_action_uses(uses: str, action_uses: str = _ACTION_USES) -> bool:
    """Return True when *uses* is the canonical mergeCraft action with a non-empty ref."""
    if not uses.startswith(action_uses + "@"):
        return False
    ref = uses[len(action_uses) + 1 :]
    return bool(ref)


def _flat_secret_names(canonical: str) -> tuple[str, ...]:
    from mergecraft.models import PROVIDERS
    from mergecraft.utils.secrets import CLOUD_BYOK_ENV_VARS_BY_LABEL

    provider = PROVIDERS.get(canonical)
    if provider is None:
        return _UNREGISTERED_FLAT_SECRETS.get(canonical, ())
    names: list[str] = []
    for key in (
        *(provider.managed_credentials or ()),
        *(provider.env_vars or ()),
        *CLOUD_BYOK_ENV_VARS_BY_LABEL.get(canonical, ()),
    ):
        if key not in names:
            names.append(key)
    return tuple(names)


@lru_cache(maxsize=1)
def _secret_name_to_provider_label_map() -> dict[str, str]:
    from mergecraft.models import PROVIDERS

    mapping: dict[str, str] = {}
    for label in (*PROVIDERS.keys(), "cursor"):
        for secret_name in _flat_secret_names(label):
            mapping.setdefault(secret_name, label)
    return mapping


def secret_name_to_provider_label(secret_name: str) -> str | None:
    """Map a credential env var or Actions secret name to a provider label."""
    return _secret_name_to_provider_label_map().get(secret_name)


def _secret_names_from_env_value(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    match = _SECRET_REF_RE.match(value.strip())
    if match is None:
        return ()
    return (match.group(1),)


def _indexed_labels_from_env(env_map: dict[str, Any]) -> dict[int, str]:
    labels: dict[int, str] = {}
    for key, value in env_map.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        match = _INDEXED_LABEL_RE.match(key)
        if match is None:
            continue
        stripped = value.strip()
        if not stripped or _SECRET_REF_RE.match(stripped):
            continue
        labels[int(match.group(1))] = stripped.lower()
    return labels


def _labels_from_env_map(env_map: dict[str, Any]) -> set[str]:
    wired: set[str] = set()
    secret_to_label = _secret_name_to_provider_label_map()
    indexed_labels = _indexed_labels_from_env(env_map)

    for label in indexed_labels.values():
        wired.add(label)

    for key, value in env_map.items():
        if not isinstance(key, str):
            continue
        indexed_match = _INDEXED_CREDENTIAL_RE.match(key)
        if indexed_match is not None:
            index = int(indexed_match.group(1))
            if index in indexed_labels:
                wired.add(indexed_labels[index])
            for secret_name in _secret_names_from_env_value(value):
                mapped = secret_to_label.get(secret_name)
                if mapped is not None:
                    wired.add(mapped)
            continue
        mapped_key = secret_to_label.get(key)
        if mapped_key is not None:
            wired.add(mapped_key)
        for secret_name in _secret_names_from_env_value(value):
            mapped = secret_to_label.get(secret_name)
            if mapped is not None:
                wired.add(mapped)
    return wired


def parse_auth_manifest(workflow_path: Path) -> frozenset[str]:
    """Return provider labels CI can authenticate from mergeCraft review steps."""
    try:
        text = workflow_path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"could not read {workflow_path}: {exc}"
        raise WorkflowAuthManifestError(msg) from exc
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"could not parse {workflow_path}: {exc}"
        raise WorkflowAuthManifestError(msg) from exc
    if not isinstance(parsed, dict):
        msg = f"{workflow_path} must be a mapping at the top level"
        raise WorkflowAuthManifestError(msg)

    wired: set[str] = set()
    jobs = parsed.get("jobs")
    if not isinstance(jobs, dict):
        return frozenset()

    for job_def in jobs.values():
        if not isinstance(job_def, dict):
            continue
        steps = job_def.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str) or not is_mergecraft_action_uses(uses):
                continue
            env_map = step.get("env")
            if isinstance(env_map, dict):
                wired.update(_labels_from_env_map(env_map))
    return frozenset(wired)


__all__ = [
    "DEFAULT_WORKFLOW_RELATIVE_PATH",
    "WorkflowAuthManifestError",
    "is_mergecraft_action_uses",
    "parse_auth_manifest",
    "secret_name_to_provider_label",
]
