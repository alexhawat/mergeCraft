"""RED contracts for ``mergecraft tracing logfire enable|disable`` (issue #56 follow-up).

Symmetric with sevn's ``sevn tracing logfire enable|disable`` (`specs/04-tracing.md`).
Where :mod:`mergecraft.cli.auth_cmd` is the *interactive* setup, :mod:`mergecraft.cli.tracing_logfire_cmd`
is the *non-interactive* counterpart — operators can wire CI / operator scripts
to enable/disable tracing without re-prompting.

These tests cover the four failure modes and the two happy paths:

- ``enable`` writes ``MERGECRAFT_LOGFIRE_TOKEN`` + ``MERGECRAFT_TRACING_PROJECT``
  to ``.env`` and the ``LOGFIRE_TOKEN`` Actions secret.
- ``enable`` validates the bearer against ``GET /api/v1/projects`` and rejects
  302 / 401 / 403.
- ``disable`` clears the two env vars and removes the ``LOGFIRE_TOKEN`` secret.
- ``disable`` treats a missing ``LOGFIRE_TOKEN`` secret as success (the
  post-condition we want — secret is absent — already holds).
"""

from __future__ import annotations

import getpass
import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

LOGFIRE_PROBE_PATH = "/api/v1/projects"
LOGFIRE_PROBE_HOST = "api.pydantic.dev"


def _load_logfire_cmd() -> object:
    try:
        return importlib.import_module("mergecraft.cli.tracing_logfire_cmd")
    except ImportError as exc:
        pytest.fail(f"mergecraft.cli.tracing_logfire_cmd not importable: {exc}")


def _patch_httpx_with(monkeypatch: MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def _factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("transport", transport)
        kwargs.setdefault("timeout", 15.0)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("mergecraft.cli.auth_cmd.httpx.Client", _factory)


def _stub_repo_slug(monkeypatch: MonkeyPatch, slug: str = "acme/widgets") -> None:
    """Stub ``_parse_repo_slug`` in the consumer module so the gh helpers never shell out."""
    consumer_module = importlib.import_module("mergecraft.cli.tracing_logfire_cmd")

    def _factory() -> str:
        return slug

    monkeypatch.setattr(consumer_module, "_parse_repo_slug", _factory)


def _capture_secret_set(monkeypatch: MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def _recorder(*, name: str, value: str, repo_slug: str) -> bool:
        captured.append({"name": name, "value": value, "repo_slug": repo_slug})
        return True

    # The consumer module imports by name, so the monkeypatch must land on the
    # *consumer* module — auth_cmd._set_gh_secret and consumer._set_gh_secret
    # are two distinct references that resolve to the same callable.
    consumer_module = importlib.import_module("mergecraft.cli.tracing_logfire_cmd")
    monkeypatch.setattr(consumer_module, "_set_gh_secret", _recorder)
    return captured


def _capture_secret_delete(monkeypatch: MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def _recorder(*, name: str, repo_slug: str) -> bool:
        captured.append({"name": name, "repo_slug": repo_slug})
        return True

    consumer_module = importlib.import_module("mergecraft.cli.tracing_logfire_cmd")
    monkeypatch.setattr(consumer_module, "_delete_gh_secret", _recorder)
    return captured


# Backwards-compat aliases for the existing test names.
def _stub_gh_token(monkeypatch: MonkeyPatch, token: str | None = "gh-token") -> None:
    _stub_repo_slug(monkeypatch)


def _stub_git_remote(monkeypatch: MonkeyPatch, slug: str = "acme/widgets") -> None:
    _stub_repo_slug(monkeypatch, slug)


# ── structural: ``mergecraft tracing logfire`` is a Typer subcommand ─────────


def test_tracing_logfire_subcommand_is_collectable() -> None:
    """``mergecraft tracing logfire`` must register as a Typer subcommand."""
    result = runner.invoke(app, ["tracing", "--help"])
    assert result.exit_code == 0
    assert "logfire" in result.stdout.lower(), (
        f"expected 'logfire' in tracing --help output, got: {result.stdout!r}"
    )
    result = runner.invoke(app, ["tracing", "logfire", "--help"])
    assert result.exit_code == 0
    assert "enable" in result.stdout.lower()
    assert "disable" in result.stdout.lower()


# ── enable: writes local + gh secret when validator passes ───────────────────


def test_tracing_logfire_enable_writes_env_and_gh_secret(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``enable --token X --project Y --scope both`` writes both layers."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"project_name": "acme/widgets"}])

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "tracing",
            "logfire",
            "enable",
            "--token",
            "lf-test-token",
            "--project",
            "mergecraft-dev",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(captured) == 1
    assert captured[0]["name"] == "LOGFIRE_TOKEN"
    assert captured[0]["repo_slug"] == "acme/widgets"
    written = env_path.read_text(encoding="utf-8")
    assert "MERGECRAFT_LOGFIRE_TOKEN=" in written
    assert "MERGECRAFT_TRACING_PROJECT=" in written
    assert "mergecraft-dev" in written  # value (may be quoted or not)


def test_tracing_logfire_enable_prompts_for_token_when_missing(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``enable`` without ``--token`` reads via getpass so the secret never lands in shell history."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "lf-prompted-token")
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    result = runner.invoke(
        app,
        ["tracing", "logfire", "enable", "--project", "mergecraft-dev"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(captured) == 1
    assert captured[0]["value"] == "lf-prompted-token"


def test_tracing_logfire_enable_requires_project() -> None:
    """``enable`` without ``--project`` bails — logfire is a named export target."""
    result = runner.invoke(
        app,
        ["tracing", "logfire", "enable", "--token", "x"],
    )
    assert result.exit_code != 0
    output = (result.stdout + result.stderr).lower()
    assert "project" in output


def test_tracing_logfire_enable_rejects_401(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``enable`` fails closed on bad tokens (validator 401/403/302)."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid"})

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))

    result = runner.invoke(
        app,
        [
            "tracing",
            "logfire",
            "enable",
            "--token",
            "bad-token",
            "--project",
            "mergecraft-dev",
        ],
    )

    assert result.exit_code != 0
    assert captured == []
    assert not (tmp_path / ".env").exists()


def test_tracing_logfire_enable_rejects_302(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``enable`` rejects 302 redirects to the auth page (token that 302s never ingests)."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "https://logfire.pydantic.dev/auth/sign-in"},
        )

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))

    result = runner.invoke(
        app,
        [
            "tracing",
            "logfire",
            "enable",
            "--token",
            "stale-token",
            "--project",
            "mergecraft-dev",
        ],
    )

    assert result.exit_code != 0
    assert captured == []
    assert not (tmp_path / ".env").exists()


def test_tracing_logfire_enable_scope_local_only_writes_env(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``--scope local`` skips gh helpers entirely, writes only the local file."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _patch_httpx_with(monkeypatch, _handler)

    def _gh_fail(*_a, **_kw):  # type: ignore[no-untyped-def]
        pytest.fail("gh helpers must not be invoked under --scope local")

    module = importlib.import_module("mergecraft.cli.auth_cmd")
    monkeypatch.setattr(module, "_get_gh_token", _gh_fail)
    monkeypatch.setattr(module, "_parse_git_remote", _gh_fail)
    captured = _capture_secret_set(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "tracing",
            "logfire",
            "enable",
            "--token",
            "lf-test-token",
            "--project",
            "mergecraft-dev",
            "--scope",
            "local",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured == []
    written = env_path.read_text(encoding="utf-8")
    assert "MERGECRAFT_LOGFIRE_TOKEN=" in written
    assert "MERGECRAFT_TRACING_PROJECT=" in written
    assert "mergecraft-dev" in written


# ── disable: clears env vars + gh secret ─────────────────────────────────────


def test_tracing_logfire_disable_clears_env_and_gh_secret(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``disable`` clears the two env vars and calls ``gh secret delete``."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_delete(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MERGECRAFT_LOGFIRE_TOKEN=tk\n"
        "MERGECRAFT_TRACING_PROJECT=mergecraft-dev\n"
        "NOUS_API_KEY=keep-me\n",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["tracing", "logfire", "disable"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(captured) == 1
    assert captured[0]["name"] == "LOGFIRE_TOKEN"
    assert captured[0]["repo_slug"] == "acme/widgets"
    import re

    written = env_path.read_text(encoding="utf-8")
    # The two Logfire keys are now empty (still present, blank value).
    assert re.search(r"^MERGECRAFT_LOGFIRE_TOKEN=['\"]?['\"]?$", written, re.MULTILINE), (
        f"expected MERGECRAFT_LOGFIRE_TOKEN to be blank, got: {written!r}"
    )
    assert re.search(r"^MERGECRAFT_TRACING_PROJECT=['\"]?['\"]?$", written, re.MULTILINE), (
        f"expected MERGECRAFT_TRACING_PROJECT to be blank, got: {written!r}"
    )
    # Unrelated keys are preserved.
    assert "NOUS_API_KEY=keep-me" in written
    assert "tk" not in written
    assert "mergecraft-dev" not in written


def test_tracing_logfire_disable_scope_github_only_calls_delete(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``--scope github`` only deletes the secret; the .env is untouched."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_delete(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MERGECRAFT_LOGFIRE_TOKEN=tk\nMERGECRAFT_TRACING_PROJECT=mergecraft-dev\n",
        encoding="utf-8",
    )
    pre = env_path.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        ["tracing", "logfire", "disable", "--scope", "github"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(captured) == 1
    assert captured[0]["name"] == "LOGFIRE_TOKEN"
    # .env is untouched.
    assert env_path.read_text(encoding="utf-8") == pre


def test_tracing_logfire_disable_handles_missing_gh_secret(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``disable`` is a no-op when the secret is already absent (post-condition holds)."""

    # ``_delete_gh_secret`` returns True when the secret is missing — same as
    # the success path. The subcommand must not bail.
    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _patch_httpx_with(monkeypatch, _handler)
    monkeypatch.setattr(
        "mergecraft.cli.tracing_logfire_cmd._delete_gh_secret",
        lambda *, name, repo_slug: True,
    )
    monkeypatch.setattr(
        "mergecraft.cli.auth_cmd._get_gh_token",
        lambda: pytest.fail("must not be called when --scope local"),
    )
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    result = runner.invoke(
        app,
        ["tracing", "logfire", "disable", "--scope", "github"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    # The local file is not touched under --scope github.
    assert env_path.read_text(encoding="utf-8") == ""
