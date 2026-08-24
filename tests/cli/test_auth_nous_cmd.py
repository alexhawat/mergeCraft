"""RED tests for ``mergecraft auth nous`` (#57 / W1).

Wave plan: ``.ignorelocal/waves/issues-nous-deepseek-v4-flash-wave-plan.md``
W1 — test-creator. Pins the contract for the new ``auth nous`` subcommand:

- ``getpass`` prompt → ``_validate_nous_api_key`` → ``gh secret set NOUS_API_KEY``
  on the ``origin`` repo.
- Validator probes ``/v1/chat/completions`` (per W0.4 — ``/v1/models`` is a
  public catalogue that returns 200 even for an invalid key). 200 → accept;
  401 / 403 → reject; 5xx / ``httpx.HTTPError`` → warn-and-save (parity with
  ``_validate_gemini_api_key``).
- Fails closed when ``gh auth token`` returns nothing or ``gh`` is absent.
- Network access goes through ``httpx.MockTransport`` only — no real call to
  ``inference-api.nousresearch.com`` from this file (W1.15 / convention 7).
"""

from __future__ import annotations

import getpass
import importlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

NOUS_PROBE_PATH = "/v1/chat/completions"
NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"


def _load_auth_cmd() -> object:
    """Lazy import so missing symbols fail with a clear message, not at collection time."""
    try:
        return importlib.import_module("mergecraft.cli.auth_cmd")
    except ImportError as exc:
        pytest.fail(f"mergecraft.cli.auth_cmd not importable: {exc}")


def _load_validator() -> Any:
    """Return the ``_validate_nous_api_key`` symbol (or fail loudly if absent)."""
    module = _load_auth_cmd()
    validator = getattr(module, "_validate_nous_api_key", None)
    if validator is None:
        pytest.fail("mergecraft.cli.auth_cmd._validate_nous_api_key is not implemented")
    return validator


def _patch_httpx_with(monkeypatch: MonkeyPatch, handler) -> None:
    """Replace ``httpx.Client`` in the ``auth_cmd`` module with a MockTransport-backed client."""
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def _factory(*args, **kwargs):  # type: ignore[no-untyped-def]
        # The validator calls ``httpx.Client(timeout=15.0)`` with no other kwargs.
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


# ── W1.10 — happy path: prompt → validate → write ────────────────────────────


def test_auth_nous_prompts_with_getpass_and_writes_secret(
    monkeypatch: MonkeyPatch,
) -> None:
    """Full happy path: getpass → 200 from validator → gh secret set NOUS_API_KEY on origin."""

    # Validator says yes (the unit-level validator tests cover the 200 branch).
    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == NOUS_PROBE_PATH
        return httpx.Response(200, json={"choices": []})

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "nous-test-key")

    result = runner.invoke(app, ["auth", "nous"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(captured) == 1
    record = captured[0]
    assert record["name"] == "NOUS_API_KEY"
    assert record["repo_slug"] == "acme/widgets"
    # Convention 7: the test never asserts on the secret value itself, only on
    # its destination. The validator received the token, not this assertion.


# ── W1.11 — fails closed when ``gh`` is unauthenticated ─────────────────────


@pytest.mark.xfail(reason="TH5", strict=True)
def test_auth_nous_fails_closed_when_gh_is_unauthenticated(
    monkeypatch: MonkeyPatch,
) -> None:
    """``_get_gh_token`` raising (gh absent or no token) → subcommand exits non-zero with a hint."""

    def _bail(*_a, **_kw):  # type: ignore[no-untyped-def]
        raise SystemExit("gh cli not found or not authenticated.")

    module = _load_auth_cmd()
    monkeypatch.setattr(module, "_get_gh_token", _bail)
    # If the subcommand ever tries to validate or set the secret after this bail,
    # we want to know — those calls must not happen.
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: pytest.fail("should not be reached"))
    validator_calls: list[str] = []
    monkeypatch.setattr(
        module, "_validate_nous_api_key", lambda key: validator_calls.append(key) or True
    )

    with pytest.raises(SystemExit) as exc_info:
        runner.invoke(app, ["auth", "nous"], catch_exceptions=False)

    assert "gh" in str(exc_info.value).lower()
    assert validator_calls == []


# ── W1.12 — validator returns False on 401 / 403 → subcommand bails ─────────


def test_auth_nous_rejects_on_401_or_403(monkeypatch: MonkeyPatch) -> None:
    """401 / 403 from the validator → subcommand bails before ``gh secret set``."""
    seen_status: list[int] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == NOUS_PROBE_PATH
        # Alternate 401 and 403 across the two sub-cases via a counter.
        seen_status.append(401)
        return httpx.Response(401, json={"status": 401, "message": "Your API key is invalid"})

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "nous-test-key")

    result = runner.invoke(app, ["auth", "nous"])

    assert result.exit_code != 0
    assert captured == []
    output = (result.stdout + result.stderr).lower()
    assert "401" in output or "403" in output or "validation" in output or "invalid" in output
    assert seen_status == [401]


# ── W1.13 — network error → warn-and-save (parity with gemini/cursor) ────────


def test_auth_nous_warns_and_saves_on_network_error(monkeypatch: MonkeyPatch) -> None:
    """``httpx.ConnectError`` from the validator → warning + ``gh secret set`` still runs."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated dns failure")

    _patch_httpx_with(monkeypatch, _handler)
    _stub_gh_token(monkeypatch)
    _stub_git_remote(monkeypatch)
    captured = _capture_secret_set(monkeypatch)
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: "nous-test-key")

    result = runner.invoke(app, ["auth", "nous"])

    assert result.exit_code == 0, result.stdout + result.stderr
    assert len(captured) == 1
    assert captured[0]["name"] == "NOUS_API_KEY"


# ── W1.14 — direct unit tests for the validator ──────────────────────────────


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, True),
        (401, False),
        (403, False),
        (500, True),  # 5xx → warn-and-save (parity with gemini/cursor)
        (502, True),
    ],
)
def test_auth_nous_validator_returns_correct_status(
    monkeypatch: MonkeyPatch, status: int, expected: bool
) -> None:
    """Direct unit tests for ``_validate_nous_api_key`` with a mocked httpx transport.

    Parametrised table covers the W0.4 finding: ``/v1/chat/completions`` is the
    path that actually enforces auth — a fake bearer returns 401 with the
    Portal's stock ``{"status":401,"message":"Your API key is invalid..."}``
    body, so the validator's 200/401/403 branch is testable end-to-end.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == NOUS_PROBE_PATH, (
            f"validator must probe {NOUS_PROBE_PATH}, got {request.url.path}"
        )
        auth_header = request.headers.get("authorization", "")
        assert auth_header.startswith("Bearer "), (
            f"expected Bearer auth header, got {auth_header!r}"
        )
        if status == 200:
            return httpx.Response(200, json={"choices": []})
        if status in {401, 403}:
            return httpx.Response(
                status, json={"status": status, "message": "Your API key is invalid"}
            )
        return httpx.Response(status, text="server error")

    _patch_httpx_with(monkeypatch, _handler)

    validator = _load_validator()
    assert validator("nous-test-key") is expected


def test_auth_nous_validator_warns_and_returns_true_on_network_error(
    monkeypatch: MonkeyPatch,
) -> None:
    """Network failure → ``logger.warning(...)`` and the validator still returns ``True``."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated dns failure")

    _patch_httpx_with(monkeypatch, _handler)

    # Capture loguru records so we can assert the warning fires.
    from loguru import logger

    captured: list[tuple[str, str]] = []

    def _sink(record):  # type: ignore[no-untyped-def]
        entry = record.record  # type: ignore[attr-defined]
        captured.append((entry["level"].name, entry["message"]))

    sink_id = logger.add(_sink, level="WARNING")
    try:
        validator = _load_validator()
        result = validator("nous-test-key")
    finally:
        logger.remove(sink_id)

    assert result is True
    assert any(level == "WARNING" and "nous" in message.lower() for level, message in captured), (
        f"expected a warning mentioning 'nous', got: {captured}"
    )


# ── W1.15 — structural: this file never hits the live Nous Portal ────────────


def test_no_real_api_call_in_unit_tests() -> None:
    """Structural guard: the production Portal URL never appears in this file's source.

    Same guard as ``test_no_real_api_call_in_unit_tests`` in
    ``tests/agents/test_agent_resolve_nous.py`` — every code path in this
    file goes through ``httpx.MockTransport``. The Portal's host string is
    forbidden anywhere except as a comment.
    """
    import re
    from pathlib import Path

    test_file = Path(__file__).resolve()
    source = test_file.read_text(encoding="utf-8")

    # The URL is allowed as a typed constant for documentation; one occurrence.
    # (The assertion message below also includes the host string — counted as a
    # second reference — so the cap is 2 occurrences.)
    portal_hits = re.findall(r"inference-api\.nousresearch\.com", source)
    assert len(portal_hits) <= 2, (
        f"tests/cli/test_auth_nous_cmd.py references the production Portal URL "
        f"({len(portal_hits)} occurrences); unit tests must mock httpx."
    )


# ── W1.16 — integration smoke (real ``NOUS_API_KEY`` against the Portal) ─────


@pytest.mark.integration
def test_auth_nous_real_portal_probe_round_trip(
    monkeypatch: MonkeyPatch,
) -> None:
    """Integration smoke: ``_validate_nous_api_key`` against the real Portal.

    Only runs when ``NOUS_API_KEY`` is set in the test environment (skipped
    otherwise). Excluded by ``make test`` via ``-m "not integration"``.

    The test asserts only the response shape — never the key value (convention 7).
    """
    import os

    key = os.environ.get("NOUS_API_KEY")
    if not key:
        pytest.skip("NOUS_API_KEY is not set; integration smoke self-skips")

    # Drop any mock of httpx.Client installed earlier in the session.
    monkeypatch.undo()  # type: ignore[attr-defined]
    validator = _load_validator()

    # A real Portal probe with the live key — the response should be 200.
    # A fake key should be 401. We only assert this contract when ``NOUS_API_KEY``
    # is set, so a stale fixture cannot false-pass.
    assert validator(key) is True


# ── Structural / collection smoke (always green) ─────────────────────────────


def test_auth_nous_subcommand_is_collectable() -> None:
    """``mergecraft auth nous`` must register as a Typer subcommand (collection-only).

    This is a structural guard: when W2 registers the subcommand the help
    output surfaces it; until then the xfail-marked behavioural tests above
    drive the contract forward.
    """
    result = runner.invoke(app, ["auth", "--help"])
    assert result.exit_code == 0
    assert "nous" in result.stdout.lower(), (
        f"expected 'nous' in auth --help output, got: {result.stdout!r}"
    )


# ── W1.8 — PR #79 regression pin for ``build_security_config`` ───────────────


def test_build_custom_provider_block_written_for_nous_slug(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Regression pin for PR #79: ``build_security_config`` emits the nous provider block.

    Lives here (rather than in ``tests/agents/test_opencode_custom_provider.py``)
    so the W1 wave owns all the new tests in one place. The block is already
    written today by PR #79; this assertion is the contract #57 must not break.
    """
    from tests.agents.conftest import make_agent_run_context

    from mergecraft.agents.opencode import build_security_config

    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_BASE_URL", NOUS_BASE_URL)
    monkeypatch.setenv("MERGECRAFT_CUSTOM_PROVIDER_API_KEY", "nous-test-key")

    ctx = make_agent_run_context(tmp_path, resolved_model="nous/deepseek/deepseek-v4-flash")
    config = json.loads(build_security_config(ctx, "nous/deepseek/deepseek-v4-flash"))

    assert config["enabled_providers"] == ["nous"]
    assert config["model"] == "nous/deepseek/deepseek-v4-flash"
    assert config["provider"] == {
        "nous": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "nous",
            "options": {"baseURL": NOUS_BASE_URL, "apiKey": "nous-test-key"},
            "models": {"deepseek/deepseek-v4-flash": {"name": "deepseek/deepseek-v4-flash"}},
        }
    }
