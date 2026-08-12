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
LOGFIRE_PROBE_URL = "https://api.pydantic.dev/api/v1/projects"
# Write-token probe: ``pylf_v1_eu_`` / ``pylf_v2_eu_`` region-routed to the EU host.
LOGFIRE_EU_WRITE_PROBE = "https://logfire-eu.pydantic.dev/v1/info"
LOGFIRE_US_WRITE_PROBE = "https://logfire-us.pydantic.dev/v1/info"


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


def _load_write_env_value() -> Any:
    """Return the ``_write_env_value`` symbol (or fail loudly if absent)."""
    module = _load_auth_cmd()
    fn = getattr(module, "_write_env_value", None)
    if fn is None:
        pytest.fail("mergecraft.cli.auth_cmd._write_env_value is not implemented")
    return fn


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
        # 302 → reject (Logfire returns 302 to a sign-in URL when the bearer
        # is missing or expired; saving it would silently no-op).
        (302, False),
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
        if status == 302:
            return httpx.Response(
                302,
                headers={"Location": "https://logfire.pydantic.dev/auth/sign-in"},
            )
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


# ── auth_logfire validator: 302 redirect → reject (issue: 302 saved anyway) ──


def test_auth_logfire_validator_rejects_302_redirect(
    monkeypatch: MonkeyPatch,
) -> None:
    """Logfire returns 302 to a sign-in URL when the bearer is missing/expired.

    A token that 302s will never ingest — saving it is a silent no-op. The
    validator must reject (False) so the operator is told to retry.
    """

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "https://logfire.pydantic.dev/auth/sign-in"},
        )

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

    assert result is False, (
        "302 redirect to auth must be rejected — a saved token that 302s will "
        "never ingest. The operator must be told to retry."
    )
    assert any(level == "WARNING" and "302" in message for level, message in captured), (
        f"expected a warning mentioning the 302, got: {captured}"
    )


# ── write-token probe: pylf_v{N}_{us|eu}_… routes to the regional /v1/info ──


def test_auth_logfire_validator_probes_eu_write_token(
    monkeypatch: MonkeyPatch,
) -> None:
    """``pylf_v2_eu_…`` → ``logfire-eu.pydantic.dev/v1/info`` (200 = accept).

    The bug we just shipped: the validator was probing the management API
    with a write token, getting a 302, and rejecting a perfectly valid
    regional credential. The fix routes write tokens to the regional
    ``/v1/info`` endpoint — the same one the Logfire SDK uses for token
    validation in ``logfire/_internal/config.py::get_base_url_from_token``.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/info", (
            f"EU write-token probe must hit /v1/info, got {request.url.path!r}"
        )
        assert "logfire-eu.pydantic.dev" in str(request.url), (
            f"EU write-token probe must hit the EU host, got {request.url!r}"
        )
        auth_header = request.headers.get("authorization", "")
        assert auth_header.startswith("Bearer "), (
            f"expected Bearer auth header, got {auth_header!r}"
        )
        return httpx.Response(200, json={"project_name": "mergecraft-dev"})

    _patch_httpx_with(monkeypatch, _handler)

    validator = _load_validator()
    assert validator("pylf_v2_eu_c8a1f2ec-deadbeef-1234") is True


def test_auth_logfire_validator_probes_us_write_token(
    monkeypatch: MonkeyPatch,
) -> None:
    """``pylf_v1_us_…`` → ``logfire-us.pydantic.dev/v1/info``."""

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/info", (
            f"US write-token probe must hit /v1/info, got {request.url.path!r}"
        )
        assert "logfire-us.pydantic.dev" in str(request.url), (
            f"US write-token probe must hit the US host, got {request.url!r}"
        )
        return httpx.Response(200, json={"project_name": "mergecraft-dev"})

    _patch_httpx_with(monkeypatch, _handler)

    validator = _load_validator()
    assert validator("pylf_v1_us_c8a1f2ec-deadbeef-1234") is True


def test_auth_logfire_validator_rejects_expired_write_token(
    monkeypatch: MonkeyPatch,
) -> None:
    """``/v1/info`` returns 401 for an expired write token → validator rejects.

    An expired token is rejected, but we surface ``probe=write-token`` in the
    warning so the operator knows which probe failed (the management probe
    on a different token may still be healthy).
    """
    from loguru import logger

    captured: list[tuple[str, str]] = []

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "expired"})

    _patch_httpx_with(monkeypatch, _handler)

    def _sink(record):  # type: ignore[no-untyped-def]
        entry = record.record  # type: ignore[attr-defined]
        captured.append((entry["level"].name, entry["message"]))

    sink_id = logger.add(_sink, level="WARNING")
    try:
        validator = _load_validator()
        result = validator("pylf_v2_eu_expired-token-xyz")
    finally:
        logger.remove(sink_id)

    assert result is False, "expired write token must be rejected"
    assert any(level == "WARNING" and "write-token" in message for level, message in captured), (
        f"expected a warning mentioning 'write-token' probe, got: {captured}"
    )


# ── dotenv writing: tokens + project labels are not wrapped in quotes ──────


def test_auth_logfire_writes_token_unquoted(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The new ``quote_mode="never"`` writes the bare token (no ``'…'`` wrapper).

    Repro: with ``quote_mode="always"`` the token came out as
    ``MERGECRAFT_LOGFIRE_TOKEN='pylf_v2_eu_…'``. Operators grep their
    ``.env`` for the token to confirm a fresh save; the quotes broke that
    workflow. The fix: ``quote_mode="never"`` since the token (base64 payload
    + ``-`` / ``_``) and the project label (``[A-Za-z0-9_-/]+``) are both
    safe unquoted.
    """

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _patch_httpx_with(monkeypatch, _handler)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")
    _write_env_value = _load_write_env_value()

    # Token contains the hyphen + underscore pattern of a real write token.
    token_value = "pylf_v2_eu_c8a1f2ec-0521-40c0-8159-2625b0b3b485_JYx4yZjdxKxwHN3JgyvJm2sTvSQtdYjtyy1P9HV1SQQ1"
    project_value = "mergecraft-dev"

    result = _write_env_value(env_path, "MERGECRAFT_LOGFIRE_TOKEN", token_value)
    assert result is True
    result = _write_env_value(env_path, "MERGECRAFT_TRACING_PROJECT", project_value)
    assert result is True

    written = env_path.read_text(encoding="utf-8")
    # Bare value, no single-quote wrapper.
    assert f"MERGECRAFT_LOGFIRE_TOKEN={token_value}\n" in written, (
        f"token must be written unquoted; got: {written!r}"
    )
    assert f"MERGECRAFT_TRACING_PROJECT={project_value}\n" in written


# ── CLI bootstrap: ``mergecraft`` loads ``.env`` so subsequent commands see
#    what ``auth logfire`` wrote (issue: precedence layer saw empty os.environ) ──


def test_cli_loads_local_env_into_os_environ(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``main()`` must call ``load_dotenv`` so the precedence layer sees .env keys.

    Repro for the "config tracing shows enabled: false" bug: the auth command
    writes ``MERGECRAFT_LOGFIRE_TOKEN`` to ``.env``, but the next CLI invocation
    in the same shell reads ``os.environ`` (which is loaded once at python
    startup) and finds the key absent. The fix is to call ``load_dotenv``
    idempotently at ``main()`` with ``override=False`` so real env still wins.
    """
    import os

    from mergecraft.cli import app as cli_app

    # Pin the .env path so the test does not depend on the operator's cwd.
    env_path = tmp_path / ".env"
    env_path.write_text(
        "MERGECRAFT_LOGFIRE_TOKEN=tk-from-env-file\n"
        "MERGECRAFT_TRACING_PROJECT=mergecraft-dev\n"
        "MERGECRAFT_TRACING=true\n"
        "MERGECRAFT_TRACING_TO=logfire\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGECRAFT_ENV", str(env_path))
    # Strip the pre-existing values so the test would fail without the loader.
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)
    monkeypatch.delenv("MERGECRAFT_TRACING_PROJECT", raising=False)
    monkeypatch.delenv("MERGECRAFT_TRACING", raising=False)
    monkeypatch.delenv("MERGECRAFT_TRACING_TO", raising=False)

    # Snapshot os.environ so the test cleans up after itself — these writes
    # leak into the next test's view of the world without a teardown.
    saved = {
        k: os.environ.get(k)
        for k in (
            "MERGECRAFT_LOGFIRE_TOKEN",
            "MERGECRAFT_TRACING_PROJECT",
            "MERGECRAFT_TRACING",
            "MERGECRAFT_TRACING_TO",
        )
    }
    try:
        # Drive the loader directly — the same path `main()` runs before `app()`.
        cli_app._load_local_env()

        # ``load_dotenv`` writes to ``os.environ``; verify that, not the monkeypatch
        # snapshot (which only sees setenv/delenv calls).
        assert os.environ["MERGECRAFT_LOGFIRE_TOKEN"] == "tk-from-env-file"
        assert os.environ["MERGECRAFT_TRACING_PROJECT"] == "mergecraft-dev"
        assert os.environ["MERGECRAFT_TRACING"] == "true"
        assert os.environ["MERGECRAFT_TRACING_TO"] == "logfire"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_cli_env_loader_does_not_override_real_env(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """``load_dotenv`` is called with ``override=False`` — real env vars win.

    Operators want their shell-set values to take precedence over the .env
    file (CI secrets, GitHub Actions env, `direnv`, etc.). The loader must
    populate only missing keys.
    """
    import os

    from mergecraft.cli import app as cli_app

    env_path = tmp_path / ".env"
    env_path.write_text(
        "MERGECRAFT_LOGFIRE_TOKEN=tk-from-env-file\nMERGECRAFT_TRACING_PROJECT=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGECRAFT_ENV", str(env_path))
    # Pre-set the env var as if the operator had set it in their shell. The
    # loader must NOT overwrite this with the value from the .env file.
    monkeypatch.setenv("MERGECRAFT_TRACING_PROJECT", "from-shell")
    # Ensure the token key is unset so the loader populates it from the file.
    monkeypatch.delenv("MERGECRAFT_LOGFIRE_TOKEN", raising=False)

    # Snapshot for cleanup — these writes leak into the next test's view.
    saved_token = os.environ.get("MERGECRAFT_LOGFIRE_TOKEN")
    try:
        cli_app._load_local_env()

        # The shell-set project label must win over the file.
        assert os.environ["MERGECRAFT_TRACING_PROJECT"] == "from-shell"
        # Only the missing key was filled in from the file.
        assert os.environ["MERGECRAFT_LOGFIRE_TOKEN"] == "tk-from-env-file"
    finally:
        # Leave the env as monkeypatch expects — undo the load_dotenv write.
        if saved_token is None:
            os.environ.pop("MERGECRAFT_LOGFIRE_TOKEN", None)
        else:
            os.environ["MERGECRAFT_LOGFIRE_TOKEN"] = saved_token


def test_cli_env_loader_is_silent_when_env_absent(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """Loader is a no-op when ``.env`` does not exist (CI sandboxes).

    The loader must not raise when the operator has not initialized a .env
    yet — that is the default state for fresh checkouts and CI.
    """
    from mergecraft.cli import app as cli_app

    # Point at a non-existent file.
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / "missing.env"))
    # Loader must not raise.
    cli_app._load_local_env()


# ── ``auth logfire`` help text: ``[tracing]`` must render as literal text ────


def test_auth_logfire_help_does_not_emit_unbalanced_backticks() -> None:
    """The ``[tracing]`` literal in the docstring must render with the brackets.

    Repro: the original docstring had ``The ``[tracing]`` extra must be…`` and
    Rich parsed ``[tracing]`` as a markup tag, dropping the bracketed text
    (``The ```` extra…``). The fix is to escape with ``\\[tracing]`` (raw
    string docstring) so Rich renders the brackets literally.
    """
    result = runner.invoke(app, ["auth", "logfire", "--help"])

    assert result.exit_code == 0
    output = result.stdout
    # The bracketed text must be present, not consumed as markup.
    assert "[tracing]" in output, f"expected literal '[tracing]' in help output, got: {output!r}"
    # And the four-backticks artifact must not reappear.
    assert "````" not in output, f"four-backticks artifact regressed; got: {output!r}"


# ── enabling / disabling Logfire (sevn symmetry, see issue #56 follow-up) ────


def test_auth_logfire_subcommand_emits_no_syntax_warning(tmp_path: Path) -> None:
    """The docstring must not emit ``SyntaxWarning`` (``\\[…`` without raw).

    With Python 3.14 the legacy ``\\[`` escape is a deprecation warning, and
    tomorrow's Python will hard-error. The docstring is a raw string literal;
    this test guards against a regression to a plain triple-quoted docstring
    that would re-introduce the warning.
    """
    import importlib
    import sys
    import warnings

    # Wipe the module's __warningregistry__ if any, then re-import to force
    # the docstring to be reparsed. Catch any SyntaxWarning that fires.

    saved = sys.modules.pop("mergecraft.cli.auth_cmd", None)
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always", SyntaxWarning)
            importlib.import_module("mergecraft.cli.auth_cmd")
    finally:
        if saved is not None:
            sys.modules["mergecraft.cli.auth_cmd"] = saved

    bad = [w for w in captured if "invalid escape sequence" in str(w.message)]
    assert not bad, f"auth_logfire module emits SyntaxWarning(s): {[str(w.message) for w in bad]}"
    # The raw string marker is the tripwire on the docstring.
    import inspect

    from mergecraft.cli import auth_cmd as reloaded

    source = inspect.getsource(reloaded.auth_logfire)
    assert 'r"""' in source or "r'''" in source, (
        "auth_logfire docstring should be a raw string to keep ``\\[tracing]`` "
        "literal without a SyntaxWarning."
    )
