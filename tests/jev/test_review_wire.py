"""J6 F-WIRE-REVIEW — ``mergecraft review`` constructs Jev when enabled (D4, D14)."""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.offline_review import run_offline_diff_review
from tests.jev.support import (
    loguru_lines,
    watch_async_jev_client,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_PATCH = "diff --git a/demo.py b/demo.py\n--- a/demo.py\n+++ b/demo.py\n@@ -0,0 +1 @@\n+print(1)\n"


def _repo_with_jev(tmp_path: Path, *, enabled: bool) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    config_dir = repo / ".mergecraft"
    config_dir.mkdir()
    flag = "true" if enabled else "false"
    (config_dir / "config.yaml").write_text(
        f"push: restricted\nshell: restricted\njev:\n  enabled: {flag}\n",
        encoding="utf-8",
    )
    diff = tmp_path / "change.diff"
    diff.write_text(_PATCH, encoding="utf-8")
    return repo, diff


def _skip_recorded(result: object, logs: list[str]) -> bool:
    reason = getattr(result, "jev_skip_reason", None) or getattr(result, "jev_reason", None)
    if reason == "credential_absent":
        return True
    return any("credential_absent" in line for line in logs)


async def test_enabled_review_without_credential_constructs_client_and_records_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-WIRE-REVIEW: enabled + no TYPESAFE_API_KEY is an honest skip, not a failure."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    repo, diff = _repo_with_jev(tmp_path, enabled=True)
    constructed = watch_async_jev_client(monkeypatch)
    with loguru_lines() as logs:
        result = await run_offline_diff_review(cwd=repo, diff_file=diff, dry_run=True)
    assert constructed, "run_offline_diff_review must construct AsyncJevClient when jev.enabled"
    assert result.success is True
    assert _skip_recorded(result, logs), (
        "enabled review without a credential must record credential_absent "
        "(log line or structured result field)"
    )


async def test_disabled_review_does_not_construct_client_or_require_a_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4 / D14: ``enabled: false`` is byte-identical — no client, no TypeSafe skip."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    repo, diff = _repo_with_jev(tmp_path, enabled=False)
    constructed = watch_async_jev_client(monkeypatch)
    with loguru_lines() as logs:
        result = await run_offline_diff_review(cwd=repo, diff_file=diff, dry_run=True)
    assert result.success is True
    assert constructed == []
    joined = "\n".join(logs).casefold()
    assert "credential_absent" not in joined
    assert "typesafe" not in joined


def test_cli_review_enabled_without_credential_records_skip_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F-WIRE-REVIEW at the CLI boundary ``mergecraft review``."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    repo, diff = _repo_with_jev(tmp_path, enabled=True)
    constructed = watch_async_jev_client(monkeypatch)
    env = {key: value for key, value in os.environ.items() if key != "TYPESAFE_API_KEY"}
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    with loguru_lines() as logs:
        invoked = CliRunner().invoke(
            app,
            ["review", "--cwd", str(repo), "--diff", str(diff), "--dry-run"],
            env=env,
        )
    assert invoked.exit_code == 0
    assert constructed, "mergecraft review must construct AsyncJevClient when jev.enabled"
    combined = [*logs, invoked.stdout or "", invoked.stderr or ""]
    assert _skip_recorded(invoked, combined) or any(
        "credential_absent" in line for line in combined
    )
