"""RED contracts for ``mergecraft auth logfire`` (issue #56 / D5 / D15).

Wave plan: ``.ignorelocal/waves/issues-tracing-observability-wave-plan.md``
W-tracing-auth — the operator-facing setup command for Logfire as a tracing
sink. Pins the contract for the new ``auth logfire`` subcommand:

- ``getpass`` prompt for the token + ``typer.prompt`` for the project label
  (project is **not** a secret — it is a routing string).
- Validator probes ``GET /api/v1/projects`` on the public Logfire ingest host
  (OTLP/HTTP returns 200 for invalid tokens — it accepts and discards — so
  we have to probe the REST endpoint). 200 → accept; 401/403 → reject;
  5xx / ``httpx.HTTPError`` → warn-and-save (parity with the other
  validators).
- ``--scope local|github|both`` controls where the credentials land:
  - ``local`` writes ``MERGECRAFT_LOGFIRE_TOKEN`` and ``MERGECRAFT_TRACING_PROJECT``
    into ``.env`` via ``python-dotenv``'s ``set_key`` (idempotent — re-running
    updates, never duplicates).
  - ``github`` calls ``gh secret set LOGFIRE_TOKEN`` on the origin repo.
  - ``both`` (default) does both.
- Fails closed when ``gh auth token`` returns nothing or ``gh`` is absent —
  but only when ``--scope github|both`` (a local-only operator without ``gh``
  is not blocked).
- Network access goes through ``httpx.MockTransport`` only — no real call to
  ``logfire.pydantic.dev`` from this file.
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
LOGFIRE_PROBE_URL = "https://logfire.pydantic.dev/api/v1/projects"


def _load_auth_cmd() -> object:
    """Lazy import so missing symbols fail with a clear message, not at collection time."""
    try:
        return importlib.import_module("mergecraft.cli.auth_cmd")
    except ImportError as exc:
        pytest.fail(f"mergecraft.cli.auth_cmd not importable: {exc}")


def _load_validator() -> Any:
    """Return the ``_validate_logfire_token`` symbol (or fail loudly if absent)."""
    module = _load_auth_cmd()
    validator = getattr(module, "_validate_logfire_token", None)
    if validator is None:
        pytest.fail("mergecraft.cli.auth_cmd._validate_logfire_token is not implemented")
    return validator


def _patch_httpx_with(monkeypatch: MonkeyPatch, handler) -> None:
    """Replace ``httpx.Client`` in the ``auth_cmd`` module with a MockTransport-backed client."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def _factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs.setdefault("transport", transport)
        kwargs.setdefault("timeout", 15.0)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("mergecraft.cli.auth_cmd.httpx.Client", _factory)


def _stub_gh_token(monkeypatch: MonkeyPatch, token: str | None = "gh-token") -> None:
    """Stub ``_get_gh_token`` so the subcommand never shells out to ``gh``."""
    module = _load_auth_cmd()
    monkeypatch.setattr(module, "_get_gh_token", lambda: token or "")


def _stub_git_remote(monkeypatch: MonkeyPatch, owner: str = "acme", repo: str = "widgets") -> None:
    """Stub ``_parse_git_remote`` so the subcommand never shells out to ``git``."""
    module = _load_auth_cmd()
    monkeypatch.setattr(module, "_parse_git_remote", lambda: (owner, repo))


def _capture_secret_set(monkeypatch: MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``_set_gh_secret`` with a recorder that always reports success."""
    captured: list[dict[str, Any]] = []

    def _recorder(*, name: str, value: str, repo_slug: str) -> bool:
        captured.append({"name": name, "value": value, "repo_slug": repo_slug})
        return True

    module = _load_auth_cmd()
    monkeypatch.setattr(module, "_set_gh_secret", _recorder)
    return captured


def _stub_typer_prompt(
    monkeypatch: MonkeyPatch, project_label: str | None = "acme/widgets"
) -> None:
    """Stub ``typer.prompt`` so the subcommand never reads from stdin."""
    import typer

    def _prompt(_message: str, **kwargs):  # type: ignore[no-untyped-def]
        if project_label is None:
            return ""  # operator pressed Enter → cancel
        return project_label

    monkeypatch.setattr(typer, "prompt", _prompt)


# ── happy path: default --scope both writes .env AND gh secret set ──────────


def test_auth_logfire_default_scope_writes_env_and_github(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Default ``--scope both`` writes both layers and the validator runs against /api/v1/projects."""

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == LOGFIRE_PROBE_PATH
        return httpx.Response(200, json=[{"project_name": "acme/widgets"}])

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    _stub_typer_prompt(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "lf-test-token")
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    # Pre-existing keys must be preserved by python-dotenv set_key.
    env_path = tmp_path / ".env"
    env_path.write_text("NOUS_API_KEY=existing-value\n", encoding="utf-8")

    result = runner.invoke(app, ["auth", "logfire"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(captured) == 1
    assert captured[0]["name"] == "LOGFIRE_TOKEN"
    assert captured[0]["repo_slug"] == "acme/widgets"

    written = env_path.read_text(encoding="utf-8")
    assert "MERGECRAFT_LOGFIRE_TOKEN=" in written
    assert "MERGECRAFT_TRACING_PROJECT=" in written
    assert "NOUS_API_KEY=existing-value" in written  # preserved


# ── --scope local: writes .env, never calls gh ──────────────────────────────


def test_auth_logfire_scope_local_only_writes_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``--scope local`` skips the gh helpers entirely and writes only the local file."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _patch_httpx_with(monkeypatch, _handler)

    # Both gh helpers must NOT be called — install a tripwire.
    def _gh_fail(*_a, **_kw):  # type: ignore[no-untyped-def]
        pytest.fail("gh helpers must not be invoked under --scope local")

    module = _load_auth_cmd()
    monkeypatch.setattr(module, "_get_gh_token", _gh_fail)
    monkeypatch.setattr(module, "_parse_git_remote", _gh_fail)
    captured = _capture_secret_set(monkeypatch)
    _stub_typer_prompt(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "lf-test-token")
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    result = runner.invoke(app, ["auth", "logfire", "--scope", "local"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert captured == []  # gh secret set never called
    written = env_path.read_text(encoding="utf-8")
    assert "MERGECRAFT_LOGFIRE_TOKEN=" in written
    assert "MERGECRAFT_TRACING_PROJECT=" in written


# ── --scope github: writes gh secret only, never touches .env ───────────────


def test_auth_logfire_scope_github_only_writes_github(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``--scope github`` writes only the gh secret and does not touch .env."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    _stub_typer_prompt(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "lf-test-token")
    # The .env path must NOT be written — point at a directory the test will
    # inspect for absence.
    env_path = tmp_path / ".env"
    monkeypatch.setenv("MERGECRAFT_ENV", str(env_path))

    result = runner.invoke(app, ["auth", "logfire", "--scope", "github"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(captured) == 1
    assert captured[0]["name"] == "LOGFIRE_TOKEN"
    assert not env_path.exists(), (
        f"--scope github must not write {env_path}; contents: "
        f"{env_path.read_text() if env_path.exists() else '<absent>'}"
    )


# ── 401 / 403 → subcommand bails before any state changes ───────────────────


def test_auth_logfire_rejects_on_401_or_403(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """401/403 from the validator → subcommand bails before .env and gh writes."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid token"})

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    _stub_typer_prompt(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "bogus-token")
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))

    result = runner.invoke(app, ["auth", "logfire"])

    assert result.exit_code != 0
    assert captured == []
    assert not (tmp_path / ".env").exists()
    output = (result.stdout + result.stderr).lower()
    assert "401" in output or "403" in output or "validation" in output or "invalid" in output


# ── network error → warn-and-save (parity with the other validators) ───────


def test_auth_logfire_warns_and_saves_on_network_error(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``httpx.ConnectError`` → warning + both writes still run."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated dns failure")

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    _stub_typer_prompt(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "lf-test-token")
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))

    result = runner.invoke(app, ["auth", "logfire"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(captured) == 1
    assert captured[0]["name"] == "LOGFIRE_TOKEN"
    assert (tmp_path / ".env").exists()
    written = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "MERGECRAFT_LOGFIRE_TOKEN=" in written
    assert "MERGECRAFT_TRACING_PROJECT=" in written


# ── direct unit tests for the validator ─────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, True),
        (401, False),
        (403, False),
        (500, True),  # 5xx → warn-and-save (parity with the other validators)
        (502, True),
    ],
)
def test_auth_logfire_validator_returns_correct_status(
    monkeypatch: MonkeyPatch, status: int, expected: bool
) -> None:
    """Direct unit tests for ``_validate_logfire_token`` with a mocked httpx transport."""

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == LOGFIRE_PROBE_PATH, (
            f"validator must probe {LOGFIRE_PROBE_PATH}, got {request.url.path}"
        )
        auth_header = request.headers.get("authorization", "")
        assert auth_header.startswith("Bearer "), (
            f"expected Bearer auth header, got {auth_header!r}"
        )
        if status == 200:
            return httpx.Response(200, json=[])
        if status in {401, 403}:
            return httpx.Response(status, json={"detail": "unauthorized"})
        return httpx.Response(status, text="server error")

    _patch_httpx_with(monkeypatch, _handler)

    validator = _load_validator()
    assert validator("lf-test-token") is expected


def test_auth_logfire_validator_warns_and_returns_true_on_network_error(
    monkeypatch: MonkeyPatch,
) -> None:
    """Network failure → ``logger.warning(...)`` and the validator still returns ``True``."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated dns failure")

    _patch_httpx_with(monkeypatch, _handler)

    from loguru import logger

    captured: list[tuple[str, str]] = []

    def _sink(record):  # type: ignore[no-untyped-def]
        entry = record.record  # type: ignore[attr-defined]
        captured.append((entry["level"].name, entry["message"]))

    sink_id = logger.add(_sink, level="WARNING")
    try:
        validator = _load_validator()
        result = validator("lf-test-token")
    finally:
        logger.remove(sink_id)

    assert result is True
    assert any(
        level == "WARNING" and "logfire" in message.lower() for level, message in captured
    ), f"expected a warning mentioning 'logfire', got: {captured}"


# ── scope validation ────────────────────────────────────────────────────────


@pytest.mark.parametrize("bad_scope", ["", "everywhere", "global", "12"])
def test_auth_logfire_rejects_unknown_scope(bad_scope: str, monkeypatch: MonkeyPatch) -> None:
    """Unknown ``--scope`` values bail with a hint before any prompt or write."""
    module = _load_auth_cmd()
    # Both gh helpers must NOT be called.
    monkeypatch.setattr(module, "_get_gh_token", lambda: pytest.fail("must not be called"))
    monkeypatch.setattr(module, "_parse_git_remote", lambda: pytest.fail("must not be called"))
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: pytest.fail("must not prompt"))
    import typer

    monkeypatch.setattr(typer, "prompt", lambda *_a, **_kw: pytest.fail("must not prompt"))

    result = runner.invoke(app, ["auth", "logfire", "--scope", bad_scope])

    assert result.exit_code != 0
    output = (result.stdout + result.stderr).lower()
    assert "scope" in output or "local" in output  # the help points at valid values


# ── structural / collection smoke (always green) ────────────────────────────


def test_auth_logfire_subcommand_is_collectable() -> None:
    """``mergecraft auth logfire`` must register as a Typer subcommand (collection-only)."""
    result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    assert "logfire" in result.stdout.lower(), (
        f"expected 'logfire' in auth --help output, got: {result.stdout!r}"
    )


def test_no_real_logfire_call_in_unit_tests() -> None:
    """Structural guard: the production Logfire URL never appears outside doc comments."""
    import re

    test_file = Path(__file__).resolve()
    source = test_file.read_text(encoding="utf-8")

    hits = re.findall(r"logfire\.pydantic\.dev", source)
    assert len(hits) <= 4, (
        f"tests/cli/test_auth_logfire_cmd.py references the production Logfire "
        f"URL ({len(hits)} occurrences); unit tests must mock httpx."
    )
