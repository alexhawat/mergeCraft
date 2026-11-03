"""``scripts/codex_auth_writeback.py`` — compare, write back, never print (#970)."""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.monkeypatch import MonkeyPatch

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "codex_auth_writeback.py"
_SPEC = importlib.util.spec_from_file_location("codex_auth_writeback", _SCRIPT)
assert _SPEC is not None
assert _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

_ORIGINAL_TOKEN = "rt-original-0123456789"
_NEW_TOKEN = "rt-refreshed-9876543210"
_ORIGINAL = json.dumps(
    {"tokens": {"refresh_token": _ORIGINAL_TOKEN, "access_token": "at-0", "account_id": "acct-1"}}
)
_REFRESHED = json.dumps(
    {"tokens": {"refresh_token": _NEW_TOKEN, "access_token": "at-1", "account_id": "acct-1"}}
)


def _gh_mock(tmp_path: Path, *, exit_code: int = 0) -> tuple[Path, Path]:
    """A ``gh`` stand-in recording argv and stdin, exiting with ``exit_code``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "gh-record.json"
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"record = {str(record)!r}\n"
        "json.dump({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}, open(record, 'w'))\n"
        f"print('boom', file=sys.stderr); sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
    return gh, record


def _run(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    *,
    exported: str | None,
    original: str = _ORIGINAL,
    gh_exit: int = 0,
    extra: list[str] | None = None,
) -> tuple[int, Path, Path]:
    export = tmp_path / "export" / "auth.json"
    if exported is not None:
        export.parent.mkdir()
        export.write_text(exported, encoding="utf-8")
    gh, record = _gh_mock(tmp_path, exit_code=gh_exit)
    monkeypatch.setenv("CODEX_AUTH_JSON_ORIGINAL", original)
    argv = [
        "--exported",
        str(export),
        "--original-env",
        "CODEX_AUTH_JSON_ORIGINAL",
        "--secret-name",
        "CODEX_AUTH_JSON",
        "--repo",
        "acme/demo",
        "--gh",
        str(gh),
        *(extra or []),
    ]
    return _MOD.main(argv), export, record


class TestDecide:
    def test_missing_export_means_nothing_to_do(self) -> None:
        decision = _MOD.decide(exported=None, original=_ORIGINAL)
        assert decision.write is False
        assert "no refreshed login" in decision.reason

    @pytest.mark.parametrize("body", ["{not json", "[1, 2]", '"text"'])
    def test_unparsable_or_non_object_is_refused(self, body: str) -> None:
        assert _MOD.decide(exported=body, original=_ORIGINAL).write is False

    def test_no_refresh_token_is_refused(self) -> None:
        body = json.dumps({"tokens": {"access_token": "at-only"}})
        decision = _MOD.decide(exported=body, original=_ORIGINAL)
        assert decision.write is False
        assert "no refresh token" in decision.reason

    def test_unchanged_token_is_not_rewritten(self) -> None:
        decision = _MOD.decide(exported=_ORIGINAL, original=_ORIGINAL)
        assert decision.write is False
        assert "unchanged" in decision.reason

    def test_different_account_is_refused(self) -> None:
        body = json.dumps({"tokens": {"refresh_token": _NEW_TOKEN, "account_id": "acct-2"}})
        decision = _MOD.decide(exported=body, original=_ORIGINAL)
        assert decision.write is False
        assert "different account" in decision.reason

    def test_expired_rung_is_refused_even_with_a_changed_token(self) -> None:
        decision = _MOD.decide(
            exported=_REFRESHED, original=_ORIGINAL, infra_reason=_MOD.EXPIRED_KIND
        )
        assert decision.write is False
        assert "expired" in decision.reason

    def test_empty_original_refuses_blind_write(self) -> None:
        assert _MOD.decide(exported=_REFRESHED, original="").write is False

    def test_changed_token_same_account_is_written(self) -> None:
        decision = _MOD.decide(exported=_REFRESHED, original=_ORIGINAL)
        assert decision.write is True

    def test_flat_refresh_token_spelling_is_understood(self) -> None:
        original = json.dumps({"refresh_token": _ORIGINAL_TOKEN})
        exported = json.dumps({"refresh_token": _NEW_TOKEN})
        assert _MOD.decide(exported=exported, original=original).write is True

    def test_reason_never_carries_token_material(self) -> None:
        for exported in (None, "{bad", _ORIGINAL, _REFRESHED):
            reason = _MOD.decide(exported=exported, original=_ORIGINAL).reason
            assert _ORIGINAL_TOKEN not in reason
            assert _NEW_TOKEN not in reason


class TestMain:
    def test_changed_token_is_sent_to_gh_on_stdin_and_export_removed(
        self, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
    ) -> None:
        code, export, record = _run(tmp_path, monkeypatch, exported=_REFRESHED)
        assert code == 0
        recorded = json.loads(record.read_text(encoding="utf-8"))
        assert recorded["argv"] == ["secret", "set", "CODEX_AUTH_JSON", "--repo", "acme/demo"]
        assert recorded["stdin"] == _REFRESHED
        assert not export.exists(), "the exported credential must be removed afterwards"
        out = capsys.readouterr()
        assert "::notice title=mergecraft codex login::" in out.out
        assert "CODEX_AUTH_JSON updated in acme/demo" in out.out
        assert _NEW_TOKEN not in out.out + out.err
        assert _ORIGINAL_TOKEN not in out.out + out.err

    def test_unchanged_token_writes_nothing_and_removes_export(
        self, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
    ) -> None:
        code, export, record = _run(tmp_path, monkeypatch, exported=_ORIGINAL)
        assert code == 0
        assert not record.exists(), "gh must not be invoked"
        assert not export.exists()
        assert "::notice" in capsys.readouterr().out

    def test_missing_export_is_a_notice_not_a_failure(
        self, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
    ) -> None:
        code, _, record = _run(tmp_path, monkeypatch, exported=None)
        assert code == 0
        assert not record.exists()
        assert "::notice" in capsys.readouterr().out

    def test_unparsable_export_is_a_notice(
        self, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
    ) -> None:
        code, export, record = _run(tmp_path, monkeypatch, exported="{nope")
        assert code == 0
        assert not record.exists()
        assert not export.exists()
        assert "not JSON" in capsys.readouterr().out

    def test_expired_rung_skips_the_write(
        self, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
    ) -> None:
        code, _, record = _run(
            tmp_path,
            monkeypatch,
            exported=_REFRESHED,
            extra=["--infra-reason", _MOD.EXPIRED_KIND],
        )
        assert code == 0
        assert not record.exists()
        assert "expired" in capsys.readouterr().out

    def test_gh_failure_is_a_warning_and_nonzero_exit(
        self, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
    ) -> None:
        code, export, record = _run(tmp_path, monkeypatch, exported=_REFRESHED, gh_exit=3)
        assert code == 1
        assert record.exists()
        assert not export.exists(), "the export is removed even when gh fails"
        out = capsys.readouterr().out
        assert "::warning title=mergecraft codex login::gh secret set CODEX_AUTH_JSON failed" in out
        assert _NEW_TOKEN not in out

    def test_unreadable_export_is_a_warning(
        self, tmp_path: Path, monkeypatch: MonkeyPatch, capsys: CaptureFixture[str]
    ) -> None:
        if os.getuid() == 0:
            pytest.skip("root reads every file")
        export = tmp_path / "auth.json"
        export.write_text(_REFRESHED, encoding="utf-8")
        export.chmod(0)
        monkeypatch.setenv("CODEX_AUTH_JSON_ORIGINAL", _ORIGINAL)
        try:
            code = _MOD.main(
                [
                    "--exported",
                    str(export),
                    "--original-env",
                    "CODEX_AUTH_JSON_ORIGINAL",
                    "--repo",
                    "acme/demo",
                ]
            )
        finally:
            export.chmod(0o600)
        assert code == 1
        assert "cannot read the exported login" in capsys.readouterr().out


def test_script_runs_on_the_runner_interpreter_without_the_project(tmp_path: Path) -> None:
    """The runner has only ``python3`` and the standard library."""
    export = tmp_path / "auth.json"
    export.write_text(_ORIGINAL, encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            str(_SCRIPT),
            "--exported",
            str(export),
            "--original-env",
            "ORIG",
            "--repo",
            "acme/demo",
        ],
        env={"ORIG": _ORIGINAL, "PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "unchanged" in completed.stdout
    assert _ORIGINAL_TOKEN not in completed.stdout + completed.stderr
