"""Operator model registry helpers (#479 / BC)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def allocate_model_index(entries: Sequence[Mapping[str, Any]]) -> int:
    """Return ``max(existing modelIndex) + 1``, or ``1`` when empty (D3).

    Gaps are preserved — freed indices are never recycled.
    """
    indices = [
        int(entry["modelIndex"])
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("modelIndex") is not None
    ]
    if not indices:
        return 1
    return max(indices) + 1


def normalize_model_id(provider_label: str, model_id: str) -> str:
    """Strip a leading ``{provider}/`` prefix from *model_id* (#479)."""
    stripped = model_id.strip()
    prefix = f"{provider_label.strip().lower()}/"
    if stripped.lower().startswith(prefix):
        return stripped[len(prefix) :]
    return stripped


def model_env_override_key(env_index: int, model_index: int) -> str:
    """Return ``LLM_PROVIDER_<N>_MODEL_<M>`` per D2."""
    return f"LLM_PROVIDER_{env_index}_MODEL_{model_index}"


def read_model_env_override(
    env_path: Path | str,
    env_index: int,
    model_index: int,
) -> str | None:
    """Read optional model override from ``.env`` without mutating ``os.environ``."""
    path = Path(env_path)
    if not path.is_file():
        return None
    key = model_env_override_key(env_index, model_index)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip()
    return None


def effective_model_id(
    stored_id: str,
    *,
    env_path: Path | str,
    env_index: int,
    model_index: int,
) -> str:
    """Return env override when present, otherwise the config *stored_id* (D2)."""
    override = read_model_env_override(env_path, env_index, model_index)
    if override is not None:
        return override
    return stored_id


__all__ = [
    "allocate_model_index",
    "effective_model_id",
    "model_env_override_key",
    "normalize_model_id",
    "read_model_env_override",
]
