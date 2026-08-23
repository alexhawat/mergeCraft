"""Batch HH — Codex auth post-hook behaviour (#431, D7).

Covers ``mergecraft.action.post`` branches that classify refresh rotation,
malformed writeback state, and ``gh secret set`` outcomes — not import-only
coverage padding.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mergecraft.action.post import detect_codex_refresh, main

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_detect_codex_refresh_returns_none_for_invalid_json() -> None:
    assert detect_codex_refresh(auth_file_content="{not json", original_refresh="old") is None


def test_detect_codex_refresh_returns_none_when_refresh_unchanged() -> None:
    payload = {"tokens": {"refresh_token": "same-token"}}
    assert (
        detect_codex_refresh(
            auth_file_content=json.dumps(payload),
            original_refresh="same-token",
        )
        is None
    )


def test_detect_codex_refresh_detects_nested_tokens_shape() -> None:
    payload = {"tokens": {"refresh_token": "new-token", "access_token": "a"}}
    result = detect_codex_refresh(
        auth_file_content=json.dumps(payload),
        original_refresh="old-token",
    )
    assert result is not None
    parsed = json.loads(result)
    assert parsed["tokens"]["refresh_token"] == "new-token"


def test_detect_codex_refresh_detects_flat_refresh_field() -> None:
    payload = {"refresh": "rotated", "access_token": "a"}
    result = detect_codex_refresh(
        auth_file_content=json.dumps(payload),
        original_refresh="before",
    )
    assert result == json.dumps(payload)


def test_main_skips_when_writeback_state_missing(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("STATE_codex_writeback", raising=False)
    called = False

    def _boom(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", _boom)
    main()
    assert not called


def test_main_skips_on_malformed_writeback_state(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("STATE_codex_writeback", "{bad json")
    called = False

    def _boom(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", _boom)
    main()
    assert not called


def test_main_skips_on_incomplete_writeback_state(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("STATE_codex_writeback", json.dumps({"authPath": "/tmp/auth.json"}))
    called = False

    def _boom(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", _boom)
    main()
    assert not called


def test_main_skips_when_auth_file_missing(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    auth_path = tmp_path / "missing.json"
    state = {"authPath": str(auth_path), "originalRefresh": "old"}
    monkeypatch.setenv("STATE_codex_writeback", json.dumps(state))
    called = False

    def _boom(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", _boom)
    main()
    assert not called


def test_main_skips_when_refresh_chain_unchanged(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps({"tokens": {"refresh_token": "stable"}}),
        encoding="utf-8",
    )
    state = {"authPath": str(auth_path), "originalRefresh": "stable"}
    monkeypatch.setenv("STATE_codex_writeback", json.dumps(state))
    called = False

    def _boom(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal called
        called = True
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", _boom)
    main()
    assert not called


def test_main_persists_rotated_refresh_via_gh_secret_set(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    auth_path = tmp_path / "auth.json"
    payload = {"tokens": {"refresh_token": "new-chain", "access_token": "a"}}
    auth_path.write_text(json.dumps(payload), encoding="utf-8")
    state = {"authPath": str(auth_path), "originalRefresh": "old-chain"}
    monkeypatch.setenv("STATE_codex_writeback", json.dumps(state))
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")

    calls: list[list[str]] = []

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    main()
    assert calls
    assert calls[0][:3] == ["gh", "secret", "set"]
    assert calls[0][3] == "CODEX_AUTH_JSON"
    assert "owner/repo" in calls[0]


def test_main_warns_when_gh_secret_set_fails(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    payload = {"tokens": {"refresh_token": "new-chain"}}
    auth_path.write_text(json.dumps(payload), encoding="utf-8")
    state = {"authPath": str(auth_path), "originalRefresh": "old-chain"}
    monkeypatch.setenv("STATE_codex_writeback", json.dumps(state))

    def _fail_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if kwargs.get("check"):
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    calls: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run", _fail_run)
    main()
    assert calls
    assert calls[0][:3] == ["gh", "secret", "set"]
