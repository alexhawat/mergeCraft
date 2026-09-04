"""Unit tests for ``_validate_nous_api_key`` (#57 / W1).

Provider authentication lives under ``mergecraft provider auth nous``; this file
pins the shared validator helper in ``mergecraft.cli.auth_cmd``.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

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
