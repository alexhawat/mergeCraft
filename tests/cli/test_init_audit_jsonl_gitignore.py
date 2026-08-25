"""CI #487 RED — ``mergecraft init`` must ignore ``.mergecraft/audit.jsonl`` (D10).

Issue #487: without an explicit gitignore entry, enterprise audit JSONL shows up
as untracked after review runs. D10 pins the line in the init scaffold — never
rely on consumers inventing ``/.mergecraft/*`` negation rules.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from tests.cli.support_init_audit_jsonl import (
    AUDIT_JSONL_GITIGNORE_LINE,
    audit_jsonl_path,
    audit_jsonl_rel_path,
    git_check_ignores,
    git_status_porcelain,
    gitignore_path,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "init@test.local"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Init Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("init scaffold\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )


def test_init_scaffolds_explicit_audit_jsonl_gitignore_line(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Happy — init writes the explicit ``.mergecraft/audit.jsonl`` ignore line."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    assert gitignore_path(tmp_path).is_file(), "init must scaffold or update .gitignore"
    text = gitignore_path(tmp_path).read_text(encoding="utf-8")
    assert AUDIT_JSONL_GITIGNORE_LINE in text, (
        f".gitignore must include explicit ignore for {AUDIT_JSONL_GITIGNORE_LINE!r} (D10)"
    )


def test_init_appends_audit_jsonl_when_gitignore_preexists(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Edge — init appends the audit line when .gitignore exists without it."""
    _init_git_repo(tmp_path)
    gitignore_path(tmp_path).write_text("node_modules/\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    text = gitignore_path(tmp_path).read_text(encoding="utf-8")
    assert "node_modules/" in text
    assert AUDIT_JSONL_GITIGNORE_LINE in text


def test_audit_jsonl_is_gitignored_after_init(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Functional — ``git check-ignore`` accepts audit.jsonl after init."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    rel = audit_jsonl_rel_path()
    audit_jsonl_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    audit_jsonl_path(tmp_path).write_text('{"event_type":"test"}\n', encoding="utf-8")
    assert git_check_ignores(tmp_path, rel), (
        f"{rel} must be ignored after init scaffold (D10 / #487)"
    )


def test_audit_jsonl_not_listed_as_untracked_after_init(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Functional — audit.jsonl does not appear in ``git status`` as untracked."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["init", "--force"])
    assert result.exit_code == 0, result.output
    rel = audit_jsonl_rel_path()
    audit_jsonl_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    audit_jsonl_path(tmp_path).write_text('{"event_type":"test"}\n', encoding="utf-8")
    status = git_status_porcelain(tmp_path, rel)
    assert status == "", (
        f"{rel} must not show as untracked after init; got git status line {status!r}"
    )


def test_init_does_not_duplicate_audit_jsonl_gitignore_line(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Edge — re-init with --force does not duplicate the audit.jsonl ignore line."""
    _init_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["init", "--force"])
    assert first.exit_code == 0, first.output
    second = runner.invoke(app, ["init", "--force"])
    assert second.exit_code == 0, second.output
    text = gitignore_path(tmp_path).read_text(encoding="utf-8")
    assert text.count(AUDIT_JSONL_GITIGNORE_LINE) == 1, (
        "init must not duplicate the audit.jsonl gitignore entry on re-run"
    )


def test_support_pins_audit_jsonl_gitignore_line() -> None:
    """Contract pin — gitignore line matches enterprise audit default path."""
    assert AUDIT_JSONL_GITIGNORE_LINE == ".mergecraft/audit.jsonl"
