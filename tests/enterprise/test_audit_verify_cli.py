"""Thermos BR8 follow-up — ``mergecraft audit verify`` CLI preconditions (MCB-21, D13)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.enterprise.audit import MERGECRAFT_AUDIT_ROOT_ENV, resolve_audit_log_path

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


@pytest.fixture(autouse=True)
def _external_audit_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    audit_root = tmp_path / "audit-root"
    audit_root.mkdir()
    monkeypatch.setenv(MERGECRAFT_AUDIT_ROOT_ENV, str(audit_root))


def _invoke_verify(*args: str) -> object:
    from mergecraft.cli import audit_cmd

    return runner.invoke(audit_cmd.app, ["verify", *args], env=_DUMB_ENV)


def _combined_output(result: object) -> str:
    text = result.stdout + result.stderr  # type: ignore[attr-defined]
    return text.replace("\n", "")


def test_audit_verify_exits_1_when_explicit_path_missing(tmp_path: Path) -> None:
    """Verify fails closed when the audit JSONL path does not exist."""
    missing = tmp_path / "missing-audit.jsonl"
    result = _invoke_verify(str(missing))
    assert result.exit_code == 1
    combined = _combined_output(result)
    assert "audit log missing or not a regular file" in combined
    assert missing.as_posix() in combined


def test_audit_verify_exits_1_when_path_is_a_directory(tmp_path: Path) -> None:
    """Verify rejects directories before treating an empty chain as ok."""
    directory = tmp_path / "audit-dir"
    directory.mkdir()
    result = _invoke_verify(str(directory))
    assert result.exit_code == 1
    combined = _combined_output(result)
    assert "audit log missing or not a regular file" in combined
    assert directory.as_posix() in combined


def test_audit_verify_exits_1_when_default_audit_log_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default verify path must fail when no audit sink file exists yet."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    audit_path = resolve_audit_log_path(root=workspace)
    assert not audit_path.is_file()
    result = _invoke_verify()
    assert result.exit_code == 1
    combined = _combined_output(result)
    assert "audit log missing or not a regular file" in combined
    assert audit_path.as_posix() in combined


def test_audit_verify_reports_ok_for_valid_chain(tmp_path: Path) -> None:
    """Happy path: a valid hash chain prints ``audit chain ok``."""
    from mergecraft.enterprise.audit import append_audit_event

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    append_audit_event(
        {
            "event_type": "run_lifecycle",
            "outcome": "completed",
            "run_id": "verify-cli-ok",
            "context": {},
        },
        root=workspace,
    )
    audit_path = resolve_audit_log_path(root=workspace)
    result = _invoke_verify(str(audit_path))
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "audit chain ok" in result.stdout


def test_audit_verify_exits_1_and_lists_breaks_for_tampered_chain(tmp_path: Path) -> None:
    """Tampered records surface broken line numbers and exit 1."""
    from mergecraft.enterprise.audit import append_audit_event

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    append_audit_event(
        {
            "event_type": "run_lifecycle",
            "outcome": "started",
            "run_id": "verify-cli-break-1",
            "context": {},
        },
        root=workspace,
    )
    append_audit_event(
        {
            "event_type": "run_lifecycle",
            "outcome": "completed",
            "run_id": "verify-cli-break-2",
            "context": {},
        },
        root=workspace,
    )
    audit_path = resolve_audit_log_path(root=workspace)
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[1])
    tampered["outcome"] = "tampered"
    lines[1] = json.dumps(tampered, sort_keys=True)
    audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = _invoke_verify(str(audit_path))
    assert result.exit_code == 1
    assert "audit chain breaks at lines" in result.stdout
