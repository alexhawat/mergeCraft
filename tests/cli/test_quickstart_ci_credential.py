"""The quickstart wires the CI workflow to the secret ``provider auth`` stores (#1333).

``init`` -> ``provider auth <label> --scope github`` -> ``doctor`` must leave a
workflow that passes the stored secret to the Action, and ``doctor`` must fail
when the workflow passes no credential the repository actually holds.
"""

from __future__ import annotations

import getpass
import re
import subprocess
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from mergecraft.cli import auth_cmd, doctor_cmd, provider_cmd
from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_CONFIGURATION_EXIT_CODE
from mergecraft.workflow.auth_manifest import workflow_secret_bindings

if TYPE_CHECKING:
    from pathlib import Path

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ENV = {"NO_COLOR": "1", "TERM": "dumb", "COLUMNS": "300"}
_WORKFLOW = ".github/workflows/mergecraft.yml"


def _invoke(*argv: str) -> tuple[int, str]:
    """Run the CLI and return ``(exit_code, plain output)``."""
    result = CliRunner().invoke(app, list(argv), env=_ENV)
    return result.exit_code, _ANSI.sub("", result.stdout + result.stderr)


@pytest.fixture
def consumer_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh consumer checkout after ``mergecraft init``."""
    monkeypatch.delenv("MERGECRAFT_CONFIG", raising=False)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / "unused.env"))
    root = tmp_path / "consumer"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    monkeypatch.chdir(root)
    code, out = _invoke("init")
    assert code == 0, out
    return root.resolve()


@pytest.fixture
def stored_secrets(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Record ``gh secret set`` calls instead of running ``gh``.

    ``doctor`` reads the same record back as the repository's secret list.
    """
    stored: dict[str, str] = {}

    def _target(scope: str, *, cwd: Path | None = None) -> auth_cmd.AuthTarget:
        assert scope == "github"
        return auth_cmd.AuthTarget(
            local=False,
            github=auth_cmd.GitHubSecretTarget(repo_slug="acme/widget"),
            env_path=None,
        )

    def _set(*, name: str, value: str, repo_slug: str | None = None) -> bool:
        stored[name] = value
        return True

    monkeypatch.setattr(auth_cmd, "_resolve_auth_target", _target)
    monkeypatch.setattr(auth_cmd, "_set_gh_secret", _set)
    monkeypatch.setattr(provider_cmd, "_validate_api_key_for_label", lambda *_a: True)
    monkeypatch.setattr(doctor_cmd, "repository_secret_names", lambda _root: frozenset(stored))
    return stored


_CREDENTIALS = {
    "anthropic": "sk-ant-oat01-quickstart-test-token",
    "opencode-go": "oc-go-quickstart-test-key",
    "opencode": "oc-zen-quickstart-test-key",
    "google": "gemini-quickstart-test-key",
}


@pytest.mark.parametrize("label", sorted(_CREDENTIALS), ids=sorted(_CREDENTIALS))
def test_init_auth_doctor_wires_the_stored_secret(
    consumer_repo: Path,
    stored_secrets: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    label: str,
) -> None:
    """After auth the workflow references the stored secret and ``doctor`` passes."""
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: _CREDENTIALS[label])

    code, out = _invoke("provider", "auth", label, "--scope", "github")
    assert code == 0, out
    assert stored_secrets, "provider auth stored no secret"

    referenced = {secret for _env, secret in workflow_secret_bindings(consumer_repo / _WORKFLOW)}
    assert set(stored_secrets) <= referenced, (sorted(stored_secrets), sorted(referenced))

    code, out = _invoke("workflow", "sync", "--check")
    assert code == 0, out

    code, out = _invoke("doctor")
    assert code == 0, out
    assert re.search(r"workflow auth\W+ok", out), out


def test_doctor_fails_when_the_workflow_secret_is_not_stored(
    consumer_repo: Path, stored_secrets: dict[str, str]
) -> None:
    """Straight after ``init`` no secret exists, so CI has no credential: doctor fails."""
    code, out = _invoke("doctor")
    assert code == CLI_CONFIGURATION_EXIT_CODE, out
    assert "workflow auth" in out
    assert "CLAUDE_CODE_OAUTH_TOKEN" in out
    assert "provider auth" in out


def test_doctor_fails_when_the_roster_provider_is_not_wired(
    consumer_repo: Path, stored_secrets: dict[str, str]
) -> None:
    """A roster provider the workflow never passes a credential for fails doctor."""
    config = consumer_repo / ".mergecraft" / "config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8")
        + "agents:\n  reviewer:\n    role: reviewer\n    modelChain:\n      - google/gemini-pro\n",
        encoding="utf-8",
    )
    code, out = _invoke("doctor")
    assert code == CLI_CONFIGURATION_EXIT_CODE, out
    assert "google" in out
    assert "workflow sync --apply" in out or "provider auth google" in out


def test_doctor_reports_unverified_secrets_without_gh(
    consumer_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a readable secret list the probe warns instead of guessing."""
    monkeypatch.setattr(doctor_cmd, "repository_secret_names", lambda _root: None)
    code, out = _invoke("doctor")
    assert code == 0, out
    assert re.search(r"workflow auth\W+warn", out), out
