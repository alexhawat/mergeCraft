"""RED tests for the Codex custom OpenAI-compatible provider passthrough (#71 / W3).

These tests pin the contract ``src/mergecraft/agents/codex.py::write_mcp_config``
must satisfy once W3 lands:

- multiple ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>`` env-var
  pairs (operator-locked convention, N >= 1) each emit a Codex
  ``config.toml`` ``model_providers.<provider_id>`` block, where
  ``provider_id = "provider_" + str(N)``;
- the singleton ``MERGECRAFT_CUSTOM_PROVIDER_BASE_URL`` /
  ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY`` (PR #79's contract, D7) remains a
  back-compat alias for a single ``default`` provider when no indexed pair
  is set, and is **ignored** when any indexed pair is present;
- gaps in the index sequence are preserved (no renumbering);
- partial indexed pairs (only one half set) are dropped, not partial-written;
- absent env vars produce output byte-identical to today;
- the resolved API keys never appear in any log line emitted while the config
  is being written (convention 7 / D11).

The TOML assertions parse the written file with the stdlib ``tomllib`` (3.11+)
rather than relying on string matches; that way the schema W3 lands is the
schema the test pins, not a side-effect of one writer's formatting.

Wave plan: ``.ignorelocal/waves/issues-provider-routing-wave-plan.md`` (Batch B
/ W1). Cross-wave xfail markers use ``strict=False`` so an early-passing xfail
becomes XPASS (an upgrade, not a hard failure) — see the test-creator agent
contract.
"""

from __future__ import annotations

import importlib
import json
import tomllib
from pathlib import Path

import pytest
from tests.agents.conftest import make_agent_run_context

# -- module loader -----------------------------------------------------------


def _load_codex_module():
    try:
        return importlib.import_module("mergecraft.agents.codex")
    except ImportError as exc:
        pytest.fail(f"mergecraft.agents.codex not implemented: {exc}")


# -- constants (operator-locked W1 multi-provider convention) ---------------

# Singleton (PR #79 / D7 back-compat alias).
SINGLETON_BASE_URL_ENV = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"
SINGLETON_API_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"
SINGLETON_BASE_URL = "https://singleton.example.test/v1"
SINGLETON_API_KEY = "singleton-test-key"

# Indexed multi-provider convention.
INDEXED_API_KEY_FMT = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}"
INDEXED_BASE_URL_FMT = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{n}"

PROVIDER_1_BASE_URL = "https://provider-1.example.test/v1"
PROVIDER_1_API_KEY = "key-1"
PROVIDER_2_BASE_URL = "https://provider-2.example.test/v1"
PROVIDER_2_API_KEY = "key-2"
PROVIDER_3_BASE_URL = "https://provider-3.example.test/v1"
PROVIDER_3_API_KEY = "key-3"

# Provider id derivation rule: ``"provider_" + str(N)``. Singleton alias id:
# ``"default"``. Constants used by tests for explicit assertions.
PROVIDER_1_ID = "provider_1"
PROVIDER_2_ID = "provider_2"
PROVIDER_3_ID = "provider_3"
DEFAULT_PROVIDER_ID = "default"


# -- fixture: clear every custom-provider env var ---------------------------


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wipe the full set of custom-provider env vars before each test."""
    for name in (
        SINGLETON_BASE_URL_ENV,
        SINGLETON_API_KEY_ENV,
        "NOUS_API_KEY",
        "NOUS_BASE_URL",
        "TOKENHUB_API_KEY",
        "TOKENHUB_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    # Wipe a generous index range so stray env vars from prior tests do
    # not leak into this one.
    for n in range(1, 8):
        monkeypatch.delenv(INDEXED_API_KEY_FMT.format(n=n), raising=False)
        monkeypatch.delenv(INDEXED_BASE_URL_FMT.format(n=n), raising=False)


# -- helpers -----------------------------------------------------------------


def _write_config(tmp_path: Path, *, model: str | None) -> Path:
    """Call ``write_mcp_config`` and return the path to the rendered ``config.toml``."""
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model=model)
    ctx.payload.shell = "disabled"
    return Path(codex_module.write_mcp_config(ctx))


def _parse_toml(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))


# -- W1.3 (existing): no provider block when no env vars are set ------------


def test_codex_config_toml_has_no_provider_block_without_env(tmp_path: Path) -> None:
    """Without any custom-provider env vars, ``config.toml`` must omit the provider keys."""
    path = _write_config(tmp_path, model="openai/gpt-5.3-codex")
    parsed = _parse_toml(path)

    assert "model_providers" not in parsed
    assert "openai_base_url" not in parsed


# -- W1.3 (extended): partial / parametrized coverage -----------------------


@pytest.mark.xfail(
    reason="green after W3: indexed env-var pairs populate model_providers; partial pairs dropped",
    strict=False,
)
@pytest.mark.parametrize(
    ("set_indexed", "expected_present", "expected_absent"),
    [
        # No env vars → no provider blocks (same as the structural test
        # above, repeated here to pin the contract in the parametrize
        # matrix).
        (set(), set(), set()),
        # Only ``_1`` API key, no ``_1`` base URL → provider_1 absent.
        ({1: {"api_key": True, "base_url": False}}, set(), {PROVIDER_1_ID}),
        # Only ``_1`` base URL, no ``_1`` API key → provider_1 absent.
        ({1: {"api_key": False, "base_url": True}}, set(), {PROVIDER_1_ID}),
        # Both ``_1`` set, ``_2`` partial (only API key) → provider_1
        # present, provider_2 absent.
        (
            {1: {"api_key": True, "base_url": True}, 2: {"api_key": True, "base_url": False}},
            {PROVIDER_1_ID},
            {PROVIDER_2_ID},
        ),
    ],
)
def test_codex_partial_indexed_coverage_writes_only_present_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    set_indexed: dict[int, dict[str, bool]],
    expected_present: set[str],
    expected_absent: set[str],
) -> None:
    """Partial coverage matrix: every entry in the parametrize table must
    produce exactly the expected provider set in the emitted TOML.

    Empty ``set_indexed`` means no env vars at all — same outcome as
    ``test_codex_config_toml_has_no_provider_block_without_env``.
    """
    for n, halves in set_indexed.items():
        if halves.get("api_key"):
            monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=n), f"key-{n}")
        if halves.get("base_url"):
            monkeypatch.setenv(
                INDEXED_BASE_URL_FMT.format(n=n), f"https://provider-{n}.example.test/v1"
            )

    path = _write_config(tmp_path, model=PROVIDER_1_ID + "/some-model")
    parsed = _parse_toml(path)

    providers = parsed.get("model_providers")
    if expected_present or expected_absent:
        assert isinstance(providers, dict), "expected model_providers table"
        for pid in expected_present:
            assert pid in providers, f"expected provider block for {pid}"
        for pid in expected_absent:
            assert pid not in providers, f"unexpected provider block for {pid}"
    else:
        # No env vars set → no providers section at all.
        assert "model_providers" not in parsed


@pytest.mark.xfail(
    reason="green after W3: singleton alone emits a 'default' provider block",
    strict=False,
)
def test_codex_singleton_alone_emits_default_provider_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Back-compat alias: only the singleton pair is set → a single
    ``model_providers.default`` block is emitted.
    """
    monkeypatch.setenv(SINGLETON_BASE_URL_ENV, SINGLETON_BASE_URL)
    monkeypatch.setenv(SINGLETON_API_KEY_ENV, SINGLETON_API_KEY)

    path = _write_config(tmp_path, model="default/some-model")
    parsed = _parse_toml(path)

    providers = parsed.get("model_providers")
    assert isinstance(providers, dict)
    assert DEFAULT_PROVIDER_ID in providers
    default_block = providers[DEFAULT_PROVIDER_ID]
    assert isinstance(default_block, dict)

    base_url = default_block.get("base_url") or parsed.get("openai_base_url")
    assert base_url == SINGLETON_BASE_URL


@pytest.mark.xfail(
    reason="green after W3: when any indexed pair is set, the singleton is ignored",
    strict=False,
)
def test_codex_indexed_wins_singleton_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Indexed + singleton → only indexed blocks present; singleton does
    NOT contribute an extra ``default`` entry.
    """
    monkeypatch.setenv(SINGLETON_BASE_URL_ENV, SINGLETON_BASE_URL)
    monkeypatch.setenv(SINGLETON_API_KEY_ENV, SINGLETON_API_KEY)
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), PROVIDER_1_BASE_URL)
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), PROVIDER_1_API_KEY)

    path = _write_config(tmp_path, model=PROVIDER_1_ID + "/some-model")
    parsed = _parse_toml(path)

    providers = parsed.get("model_providers")
    assert isinstance(providers, dict)
    assert PROVIDER_1_ID in providers
    assert DEFAULT_PROVIDER_ID not in providers


# -- W1.2 (extended): two indexed pairs both emit ---------------------------


@pytest.mark.xfail(
    reason="green after W3: write_mcp_config() emits model_providers.<id> for each indexed pair",
    strict=False,
)
def test_codex_config_toml_writes_both_indexed_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``_1`` AND ``_2`` set, both ``model_providers.provider_1`` and
    ``model_providers.provider_2`` appear in the emitted TOML. Parse the
    TOML — not a string match.
    """
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), PROVIDER_1_BASE_URL)
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), PROVIDER_1_API_KEY)
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=2), PROVIDER_2_BASE_URL)
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=2), PROVIDER_2_API_KEY)

    path = _write_config(tmp_path, model=PROVIDER_1_ID + "/some-model")
    parsed = _parse_toml(path)

    providers = parsed.get("model_providers")
    assert isinstance(providers, dict)
    assert PROVIDER_1_ID in providers
    assert PROVIDER_2_ID in providers

    block_1 = providers[PROVIDER_1_ID]
    block_2 = providers[PROVIDER_2_ID]
    assert isinstance(block_1, dict)
    assert isinstance(block_2, dict)

    # Each provider's base URL comes from its own env-var pair, not the
    # other's.
    url_1 = block_1.get("base_url") or parsed.get("openai_base_url")
    url_2 = block_2.get("base_url") or parsed.get("openai_base_url")
    assert url_1 == PROVIDER_1_BASE_URL
    assert url_2 == PROVIDER_2_BASE_URL


@pytest.mark.xfail(
    reason="green after W3: N=3 indexed pairs emit three provider blocks",
    strict=False,
)
def test_codex_config_toml_writes_three_indexed_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parametrise the multi-provider contract to N=3."""
    for n, base_url, api_key in [
        (1, PROVIDER_1_BASE_URL, PROVIDER_1_API_KEY),
        (2, PROVIDER_2_BASE_URL, PROVIDER_2_API_KEY),
        (3, PROVIDER_3_BASE_URL, PROVIDER_3_API_KEY),
    ]:
        monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=n), base_url)
        monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=n), api_key)

    path = _write_config(tmp_path, model=PROVIDER_1_ID + "/some-model")
    parsed = _parse_toml(path)

    providers = parsed.get("model_providers")
    assert isinstance(providers, dict)
    for n in (1, 2, 3):
        assert f"provider_{n}" in providers, f"expected provider_{n} block"


# -- W1.5 (extended): no API key leaks into logs ----------------------------


# Sentinel key values that would be catastrophic to leak. The test asserts
# the literal substring never appears in any captured log record.
SENTINEL_KEY_1 = "sk-provider-1-SENTINEL-LEAK-CHECK-0001"
SENTINEL_KEY_2 = "sk-provider-2-SENTINEL-LEAK-CHECK-0002"
SENTINEL_URL_1 = "https://provider-1-leak-check.example.test/v1"
SENTINEL_URL_2 = "https://provider-2-leak-check.example.test/v1"


@pytest.mark.xfail(
    reason="green after W3: shared helper + harness writers never emit any resolved api_key",
    strict=False,
)
def test_generated_configs_never_log_either_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Convention 7 / D11: writing either config must not leak either key.

    Drives BOTH harnesses with two indexed pairs configured; both sentinel
    keys must remain absent from every captured log record.
    """
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), SENTINEL_URL_1)
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), SENTINEL_KEY_1)
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=2), SENTINEL_URL_2)
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=2), SENTINEL_KEY_2)

    # Codex.
    codex_path = _write_config(tmp_path, model=PROVIDER_1_ID + "/some-model")
    # Ensure the file itself doesn't leak — the file is on disk, not in
    # logs, but a paranoid guard is cheap.
    codex_text = codex_path.read_text(encoding="utf-8")
    assert SENTINEL_KEY_1 not in codex_text
    assert SENTINEL_KEY_2 not in codex_text

    # OpenCode.
    from mergecraft.agents.opencode import build_security_config

    ctx = make_agent_run_context(tmp_path, resolved_model=PROVIDER_1_ID + "/some-model")
    config_json = build_security_config(ctx, PROVIDER_1_ID + "/some-model")
    config = json.loads(config_json)
    # The provider block IS expected to contain the key on disk; this
    # test only pins the *log* contract.
    assert "provider" in config

    # Walk the loguru logger to capture its output, since this codebase
    # uses loguru exclusively under ``src/mergecraft/`` (see CLAUDE.md).
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(
        lambda message: captured.append(str(message.record.message)),
        level="DEBUG",
    )
    try:
        # Re-run the writers now that the sink is attached; loguru is
        # configured globally, so anything the writers log will be
        # captured.
        ctx = make_agent_run_context(tmp_path, resolved_model=PROVIDER_1_ID + "/some-model")
        build_security_config(ctx, PROVIDER_1_ID + "/some-model")
        codex_path2 = _write_config(tmp_path, model=PROVIDER_1_ID + "/some-model")
        # Read the file so any IO-related logging fires.
        _ = codex_path2.read_text(encoding="utf-8")
    finally:
        loguru_logger.remove(sink_id)

    joined = "\n".join(captured + [r.getMessage() for r in caplog.records])
    assert SENTINEL_KEY_1 not in joined, "api_key 1 leaked into logs"
    assert SENTINEL_KEY_2 not in joined, "api_key 2 leaked into logs"
