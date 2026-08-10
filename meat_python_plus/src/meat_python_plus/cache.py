"""Disk cache keyed by (protocol/rubric hash + model + diff)."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def default_cache_dir() -> str:
    if "MEAT_CACHE" in os.environ:
        return os.environ["MEAT_CACHE"]
    home = Path.home()
    return str(home / ".meat_python_plus")


def cache_key(diff: str, model: str, rubric: str) -> str:
    h = hashlib.sha256()
    h.update(rubric.encode())
    h.update(b"\0")
    h.update(model.encode())
    h.update(b"\0")
    h.update(diff.encode())
    return h.hexdigest()


def cache_load(dir_path: str, key: str) -> dict[str, Any] | None:
    if not dir_path:
        return None
    path = Path(dir_path) / f"{key}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def cache_store(dir_path: str, key: str, result: dict[str, Any]) -> None:
    if not dir_path:
        return
    root = Path(dir_path)
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = json.dumps(result, ensure_ascii=False).encode("utf-8")
        fd, tmp_name = tempfile.mkstemp(prefix=f"{key}.", suffix=".tmp", dir=str(root))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp_name, root / f"{key}.json")
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    except OSError:
        return
