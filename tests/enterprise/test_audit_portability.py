"""Audit module does not require POSIX locking on Windows."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from mergecraft.enterprise import audit

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_windows_audit_import_and_append_without_fcntl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import builtins

    original_import = builtins.__import__

    def portable_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "fcntl":
            raise ModuleNotFoundError("fcntl is unavailable on Windows")
        return original_import(name, *args, **kwargs)

    monkeypatch.setenv("MERGECRAFT_AUDIT_ROOT", str(tmp_path))
    with monkeypatch.context() as imports:
        imports.setattr(builtins, "__import__", portable_import)
        importlib.reload(audit)
        imports.setattr(audit, "sys", SimpleNamespace(platform="win32"))
        audit.append_audit_event(
            {"event_type": "review", "outcome": "blocked", "context": {}, "run_id": "portable"},
            root=tmp_path,
        )
        assert audit.verify_audit_chain(tmp_path / "audit.jsonl") == []
    assert (tmp_path / "audit.jsonl").is_file()
