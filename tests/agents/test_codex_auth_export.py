"""The Codex driver exports a refreshed ``auth.json`` for the secret write-back (#970).

Codex rotates the ChatGPT-subscription refresh token on use and rewrites
``$CODEX_HOME/auth.json``; the run temp dir that holds it is removed at exit.
``export_refreshed_codex_auth`` copies the file to a stable path — only when
the refresh token changed — so the self-review workflow can store it.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from loguru import logger
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents import codex as codex_module
from mergecraft.agents.shared import INFRA_REASON_KEY, AgentResult

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_ORIGINAL = json.dumps(
    {"tokens": {"refresh_token": "rt-old-aaaa", "access_token": "at-0", "account_id": "acct-1"}}
)
_REFRESHED = json.dumps(
    {"tokens": {"refresh_token": "rt-new-bbbb", "access_token": "at-1", "account_id": "acct-1"}}
)


def _home_with(tmp_path: Path, body: str | None) -> Path:
    home = tmp_path / "home"
    home.mkdir(parents=True)
    if body is not None:
        (home / "auth.json").write_text(body, encoding="utf-8")
    return home


def _capture_logs() -> tuple[list[str], int]:
    records: list[str] = []
    sink_id = logger.add(lambda message: records.append(str(message)), level="DEBUG")
    return records, sink_id


class TestExportRefreshedCodexAuth:
    def test_changed_refresh_token_is_exported_private(self, tmp_path: Path) -> None:
        export = tmp_path / "runner-temp" / "mergecraft-codex-auth" / "auth.json"
        written = codex_module.export_refreshed_codex_auth(
            codex_home=_home_with(tmp_path, _REFRESHED), original=_ORIGINAL, export_path=export
        )
        assert written is True
        assert export.read_text(encoding="utf-8") == _REFRESHED
        assert stat.S_IMODE(export.stat().st_mode) == 0o600
        assert stat.S_IMODE(export.parent.stat().st_mode) == 0o700

    def test_unchanged_refresh_token_exports_nothing(self, tmp_path: Path) -> None:
        export = tmp_path / "out" / "auth.json"
        written = codex_module.export_refreshed_codex_auth(
            codex_home=_home_with(tmp_path, _ORIGINAL), original=_ORIGINAL, export_path=export
        )
        assert written is False
        assert not export.exists()

    def test_missing_auth_file_exports_nothing(self, tmp_path: Path) -> None:
        export = tmp_path / "out" / "auth.json"
        written = codex_module.export_refreshed_codex_auth(
            codex_home=_home_with(tmp_path, None), original=_ORIGINAL, export_path=export
        )
        assert written is False
        assert not export.exists()

    @pytest.mark.parametrize(
        "body", ["{broken", "[]", json.dumps({"tokens": {"access_token": "x"}})]
    )
    def test_unparsable_or_tokenless_file_exports_nothing(self, tmp_path: Path, body: str) -> None:
        export = tmp_path / "out" / "auth.json"
        written = codex_module.export_refreshed_codex_auth(
            codex_home=_home_with(tmp_path, body), original=_ORIGINAL, export_path=export
        )
        assert written is False
        assert not export.exists()

    def test_different_account_exports_nothing(self, tmp_path: Path) -> None:
        body = json.dumps({"tokens": {"refresh_token": "rt-new-bbbb", "account_id": "acct-9"}})
        export = tmp_path / "out" / "auth.json"
        written = codex_module.export_refreshed_codex_auth(
            codex_home=_home_with(tmp_path, body), original=_ORIGINAL, export_path=export
        )
        assert written is False
        assert not export.exists()

    def test_expired_credential_exports_nothing(self, tmp_path: Path) -> None:
        export = tmp_path / "out" / "auth.json"
        written = codex_module.export_refreshed_codex_auth(
            codex_home=_home_with(tmp_path, _REFRESHED),
            original=_ORIGINAL,
            export_path=export,
            credential_expired=True,
        )
        assert written is False
        assert not export.exists()

    def test_logs_name_paths_never_tokens(self, tmp_path: Path) -> None:
        records, sink_id = _capture_logs()
        try:
            codex_module.export_refreshed_codex_auth(
                codex_home=_home_with(tmp_path, _REFRESHED),
                original=_ORIGINAL,
                export_path=tmp_path / "out" / "auth.json",
            )
            codex_module.export_refreshed_codex_auth(
                codex_home=_home_with(tmp_path / "second", "{broken"),
                original=_ORIGINAL,
                export_path=tmp_path / "out2" / "auth.json",
            )
        finally:
            logger.remove(sink_id)
        joined = "\n".join(records)
        assert "exported refreshed Codex login" in joined
        assert "rt-new-bbbb" not in joined
        assert "rt-old-aaaa" not in joined


class TestExportForRun:
    def test_unset_env_does_nothing(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        monkeypatch.delenv(codex_module.CODEX_AUTH_EXPORT_ENV, raising=False)
        ctx = make_agent_run_context(tmp_path, resolved_model=None)
        home = codex_module._codex_home(ctx)
        home.mkdir(parents=True)
        (home / "auth.json").write_text(_REFRESHED, encoding="utf-8")
        codex_module._export_refreshed_login_for_run(ctx, original=_ORIGINAL, result=None)
        assert not list(tmp_path.rglob("mergecraft-codex-auth"))

    def test_env_path_receives_the_refreshed_login(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        export = tmp_path / "export" / "auth.json"
        monkeypatch.setenv(codex_module.CODEX_AUTH_EXPORT_ENV, str(export))
        ctx = make_agent_run_context(tmp_path, resolved_model=None)
        home = codex_module._codex_home(ctx)
        home.mkdir(parents=True)
        (home / "auth.json").write_text(_REFRESHED, encoding="utf-8")
        codex_module._export_refreshed_login_for_run(
            ctx, original=_ORIGINAL, result=AgentResult(success=True)
        )
        assert export.read_text(encoding="utf-8") == _REFRESHED

    def test_expired_result_suppresses_the_export(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        export = tmp_path / "export" / "auth.json"
        monkeypatch.setenv(codex_module.CODEX_AUTH_EXPORT_ENV, str(export))
        ctx = make_agent_run_context(tmp_path, resolved_model=None)
        home = codex_module._codex_home(ctx)
        home.mkdir(parents=True)
        (home / "auth.json").write_text(_REFRESHED, encoding="utf-8")
        result = AgentResult(
            success=False,
            error="dead",
            metadata={INFRA_REASON_KEY: codex_module.CODEX_CREDENTIAL_EXPIRED_KIND},
        )
        codex_module._export_refreshed_login_for_run(ctx, original=_ORIGINAL, result=result)
        assert not export.exists()

    def test_no_original_credential_does_nothing(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """An API-key run has no subscription login to write back."""
        export = tmp_path / "export" / "auth.json"
        monkeypatch.setenv(codex_module.CODEX_AUTH_EXPORT_ENV, str(export))
        ctx = make_agent_run_context(tmp_path, resolved_model=None)
        home = codex_module._codex_home(ctx)
        home.mkdir(parents=True)
        (home / "auth.json").write_text(_REFRESHED, encoding="utf-8")
        codex_module._export_refreshed_login_for_run(ctx, original="", result=None)
        assert not export.exists()

    def test_export_failure_never_raises(self, tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setenv(codex_module.CODEX_AUTH_EXPORT_ENV, str(blocker / "auth.json"))
        ctx = make_agent_run_context(tmp_path, resolved_model=None)
        home = codex_module._codex_home(ctx)
        home.mkdir(parents=True)
        (home / "auth.json").write_text(_REFRESHED, encoding="utf-8")
        codex_module._export_refreshed_login_for_run(ctx, original=_ORIGINAL, result=None)
        assert blocker.read_text(encoding="utf-8") == "not a directory"


def test_chown_is_a_no_op_for_non_root(tmp_path: Path) -> None:
    if os.getuid() == 0:
        pytest.skip("root would really chown")
    target = tmp_path / "file"
    target.write_text("x", encoding="utf-8")
    before = target.stat()
    codex_module._chown_to_parent_owner(target)
    after = target.stat()
    assert (before.st_uid, before.st_gid) == (after.st_uid, after.st_gid)
