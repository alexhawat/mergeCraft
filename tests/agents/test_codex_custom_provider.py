"""Codex custom OpenAI-compatible provider passthrough (#71 / W3).

These tests pin the contract ``src/mergecraft/agents/codex.py::write_mcp_config``
satisfies:

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
/ W1). W3 landed the behaviour, so these run green with no xfail markers.
"""

from __future__ import annotations

import importlib
import json
import tomllib
from pathlib import Path
from typing import Any

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
        # W14.1 / #222 — the operator sandbox override would flip
        # ``_sandbox_mode`` off ``read-only`` and silently disable the
        # permission profiles the #222 tests depend on.
        "MERGECRAFT_CODEX_SANDBOX",
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


@pytest.mark.parametrize(
    ("set_indexed", "expected_present", "expected_absent"),
    [
        # No env vars → no provider blocks (same as the structural test
        # above, repeated here to pin the contract in the parametrize
        # matrix).
        ({}, set(), set()),
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


# ---------------------------------------------------------------------------
# W14.1 / #222 — TOML root keys must precede tables (D17)
# ---------------------------------------------------------------------------
#
# ``write_mcp_config`` appends ``_append_custom_provider_lines`` (which emits
# ``[model_providers.<id>]`` *tables*) before ``_append_read_only_mcp_network_lines``
# (which emits the ``default_permissions`` *root key*). TOML scopes every
# bare key to the most recent table header, so with custom-provider env set
# the profile name lands at ``model_providers.<id>.default_permissions`` and
# Codex rejects the config — every review dies before it starts.
#
# These assertions parse with ``tomllib`` on purpose. A substring check for
# ``default_permissions =`` passes on the broken file, because the line *is*
# written — just in the wrong scope. Only a parse shows the nesting.

_PERMISSION_PROFILE = "mergecraft-review"


def _permission_profiles_active(tmp_path: Path, *, model: str | None) -> bool:
    """True when this context resolves to the permission-profile branch.

    Guard against a vacuous pass: if ``_codex_use_permission_profiles`` were
    False, ``default_permissions`` would never be emitted at all and the
    "not nested" assertions below would hold for the wrong reason.
    """
    codex_module = _load_codex_module()
    ctx = make_agent_run_context(tmp_path, resolved_model=model)
    ctx.payload.shell = "disabled"
    return bool(codex_module._codex_use_permission_profiles(ctx))


_CODEX_MODEL = "openai/gpt-5.3-codex"


def _scalar_keys_by_table(
    parsed: dict[str, Any],
    path: tuple[str, ...] = (),
) -> dict[str, list[str]]:
    """Map each table in a parsed config to the scalar keys it holds.

    The document root is the ``""`` scope. Reading the *parsed* document rather
    than the emitted text is what makes the D17 distinction expressible
    without pinning line order: ``base_url`` inside
    ``model_providers.provider_1`` is correct, ``default_permissions`` inside
    it is #222 — and a table with no scalar keys maps to an empty list, so
    callers can tell "no table" from "empty table".
    """
    scalars = [key for key, value in parsed.items() if not isinstance(value, dict)]
    tables = {".".join(path): scalars}
    for key, value in parsed.items():
        if isinstance(value, dict):
            tables.update(_scalar_keys_by_table(value, (*path, key)))
    return tables


# ``write_mcp_config``'s pre-W15 line order, reconstructed: provider tables
# were appended to the single ``lines`` list before ``default_permissions``,
# so the root key landed inside the last provider table. Used to prove the
# D17 guard below actually discriminates.
_PRE_W15_EMISSION = """\
approval_policy = "never"
experimental_instructions_file = "/run/x/mergecraft-instructions.md"
model_reasoning_effort = "high"

[model_providers.provider_1]
name = "provider_1"
base_url = "https://provider-1.example.test/v1"
env_key = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_1"
wire_api = "responses"
default_permissions = "mergecraft-review"

[permissions.mergecraft-review]
extends = ":read-only"
"""


def test_root_key_scope_helper_flags_the_pre_w15_emission_order() -> None:
    """Evidence the D17 guard below is not vacuous.

    Parsing the pre-W15 emission shape must place ``default_permissions``
    under the provider table and *not* at the root, while still attributing
    the table's own keys to the table.
    """
    scopes = _scalar_keys_by_table(tomllib.loads(_PRE_W15_EMISSION))

    assert scopes[""] == [
        "approval_policy",
        "experimental_instructions_file",
        "model_reasoning_effort",
    ]
    assert scopes["model_providers.provider_1"] == [
        "name",
        "base_url",
        "env_key",
        "wire_api",
        "default_permissions",
    ]
    assert scopes["permissions.mergecraft-review"] == ["extends"]


@pytest.mark.parametrize(
    ("env", "expected_provider_ids"),
    [
        pytest.param(
            {
                INDEXED_BASE_URL_FMT.format(n=1): PROVIDER_1_BASE_URL,
                INDEXED_API_KEY_FMT.format(n=1): PROVIDER_1_API_KEY,
            },
            (PROVIDER_1_ID,),
            id="one-indexed-pair",
        ),
        pytest.param(
            {
                INDEXED_BASE_URL_FMT.format(n=1): PROVIDER_1_BASE_URL,
                INDEXED_API_KEY_FMT.format(n=1): PROVIDER_1_API_KEY,
                INDEXED_BASE_URL_FMT.format(n=2): PROVIDER_2_BASE_URL,
                INDEXED_API_KEY_FMT.format(n=2): PROVIDER_2_API_KEY,
            },
            (PROVIDER_1_ID, PROVIDER_2_ID),
            id="two-indexed-pairs",
        ),
        pytest.param(
            {SINGLETON_BASE_URL_ENV: SINGLETON_BASE_URL, SINGLETON_API_KEY_ENV: SINGLETON_API_KEY},
            (DEFAULT_PROVIDER_ID,),
            id="singleton-alias",
        ),
    ],
)
def test_default_permissions_stays_a_root_key_with_custom_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    env: dict[str, str],
    expected_provider_ids: tuple[str, ...],
) -> None:
    """#222 / D17 — ``default_permissions`` must parse at the TOML top level.

    Both surfaces are active: custom-provider env vars *and* the read-only
    permission profiles. The key must not be scoped into any
    ``model_providers.<id>`` table.
    """
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert _permission_profiles_active(tmp_path, model="openai/gpt-5.3-codex")

    path = _write_config(tmp_path, model="openai/gpt-5.3-codex")
    parsed = _parse_toml(path)

    assert parsed.get("default_permissions") == _PERMISSION_PROFILE
    providers = parsed.get("model_providers")
    assert isinstance(providers, dict)
    for provider_id in expected_provider_ids:
        block = providers.get(provider_id)
        assert isinstance(block, dict), f"expected provider block for {provider_id}"
        assert "default_permissions" not in block, (
            f"default_permissions leaked into model_providers.{provider_id}"
        )


def test_default_permissions_survives_a_partial_provider_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A touched-but-incomplete pair emits a bare ``[model_providers]`` table.

    ``_append_custom_provider_lines`` writes an empty table in that case, so
    the nesting bug fires without any provider block existing at all.
    """
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), PROVIDER_1_API_KEY)
    assert _permission_profiles_active(tmp_path, model="openai/gpt-5.3-codex")

    parsed = _parse_toml(_write_config(tmp_path, model="openai/gpt-5.3-codex"))

    assert parsed.get("default_permissions") == _PERMISSION_PROFILE
    providers = parsed.get("model_providers")
    assert isinstance(providers, dict)
    assert "default_permissions" not in providers


def test_no_root_key_lands_inside_a_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D17's general invariant, not just the one key that broke.

    A bare key written after a ``[table]`` header silently changes scope, so
    the guard is "no key the writer means as top-level may parse into a
    table". The set of such keys is not hardcoded: a render with no
    custom-provider env has no table in front of its root keys, so its root
    scope *is* the writer's intended root set — the arm
    ``test_default_permissions_is_already_a_root_key_without_custom_providers``
    pins green. Deriving the set that way means a root key added to
    ``_add_read_only_mcp_network_profile`` later is covered without anyone
    editing this test.
    """
    baseline_home = tmp_path / "no-providers"
    baseline_home.mkdir()
    assert _permission_profiles_active(baseline_home, model=_CODEX_MODEL)
    baseline_scopes = _scalar_keys_by_table(
        _parse_toml(_write_config(baseline_home, model=_CODEX_MODEL))
    )
    root_key_names = set(baseline_scopes[""])
    assert "default_permissions" in root_key_names, (
        "oracle render lost the #222 key — the invariant would be vacuous"
    )

    provider_home = tmp_path / "with-providers"
    provider_home.mkdir()
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), PROVIDER_1_BASE_URL)
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), PROVIDER_1_API_KEY)
    assert _permission_profiles_active(provider_home, model=_CODEX_MODEL)

    scopes = _scalar_keys_by_table(_parse_toml(_write_config(provider_home, model=_CODEX_MODEL)))

    assert any(scope for scope in scopes), "no table emitted — nothing to be scoped into"
    misscoped = sorted(
        f"{scope}.{key}"
        for scope, keys in scopes.items()
        if scope
        for key in keys
        if key in root_key_names
    )
    assert misscoped == []
    assert root_key_names <= set(scopes[""])


def test_permission_profile_tables_are_unchanged_with_custom_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Green guard: W15 must reorder, not drop, the profile tables.

    The ``[permissions.<profile>]`` tree already parses correctly today
    because it is written as tables. Reordering the emission must leave the
    profile, its ``extends``, and the localhost network allowances intact.
    """
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), PROVIDER_1_BASE_URL)
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), PROVIDER_1_API_KEY)

    parsed = _parse_toml(_write_config(tmp_path, model="openai/gpt-5.3-codex"))

    permissions = parsed.get("permissions")
    assert isinstance(permissions, dict)
    profile = permissions.get(_PERMISSION_PROFILE)
    assert isinstance(profile, dict)
    assert profile.get("extends") == ":read-only"
    network = profile.get("network")
    assert isinstance(network, dict)
    assert network.get("enabled") is True
    assert network.get("allow_local_binding") is True
    domains = network.get("domains")
    assert isinstance(domains, dict)
    assert domains.get("127.0.0.1") == "allow"
    assert domains.get("localhost") == "allow"


def test_default_permissions_is_already_a_root_key_without_custom_providers(
    tmp_path: Path,
) -> None:
    """Green guard: the no-provider path is correct today and must stay so.

    This is the arm that proves #222 is a key-ordering bug rather than a
    missing key — with no ``[model_providers.*]`` table in front of it, the
    same line parses at the top level.
    """
    assert _permission_profiles_active(tmp_path, model="openai/gpt-5.3-codex")

    parsed = _parse_toml(_write_config(tmp_path, model="openai/gpt-5.3-codex"))

    assert parsed.get("default_permissions") == _PERMISSION_PROFILE
    assert "model_providers" not in parsed


def test_custom_provider_blocks_keep_their_own_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Green guard: reordering must not disturb the provider table contents (#71)."""
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), PROVIDER_1_BASE_URL)
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), PROVIDER_1_API_KEY)

    path = _write_config(tmp_path, model="openai/gpt-5.3-codex")
    parsed = _parse_toml(path)

    providers = parsed.get("model_providers")
    assert isinstance(providers, dict)
    block = providers.get(PROVIDER_1_ID)
    assert isinstance(block, dict)
    assert block.get("base_url") == PROVIDER_1_BASE_URL
    assert block.get("wire_api") == "responses"
    assert block.get("env_key") == INDEXED_API_KEY_FMT.format(n=1)
    # Convention 7 — the env-var *name* is written, never the resolved value.
    assert PROVIDER_1_API_KEY not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "control",
    [
        pytest.param("\x1b", id="escape"),
        pytest.param("\x01", id="start-of-heading"),
        pytest.param("\x08", id="backspace"),
        pytest.param("\x7f", id="delete"),
    ],
)
def test_control_character_in_a_base_url_still_parses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    control: str,
) -> None:
    """A consumer-supplied control character must not render an unparseable file.

    ``base_url`` reaches the renderer straight from the environment, and TOML
    forbids every control character in a basic string, not just the three with
    a named escape. A raw one lands in ``config.toml`` and ``tomllib`` refuses
    the whole file — the failure the escaping was added to prevent.
    """
    hostile = f"{PROVIDER_1_BASE_URL}{control}"
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), hostile)
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), PROVIDER_1_API_KEY)

    parsed = _parse_toml(_write_config(tmp_path, model="openai/gpt-5.3-codex"))

    providers = parsed.get("model_providers")
    assert isinstance(providers, dict)
    block = providers.get(PROVIDER_1_ID)
    assert isinstance(block, dict)
    assert block.get("base_url") == hostile


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({}, id="bare"),
        pytest.param(
            {INDEXED_API_KEY_FMT.format(n=1): PROVIDER_1_API_KEY}, id="empty-model-providers"
        ),
        pytest.param(
            {
                INDEXED_BASE_URL_FMT.format(n=1): PROVIDER_1_BASE_URL,
                INDEXED_API_KEY_FMT.format(n=1): PROVIDER_1_API_KEY,
            },
            id="indexed-provider",
        ),
    ],
)
def test_rendered_codex_config_matches_tomli_w_byte_for_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
) -> None:
    """The hand-rolled renderer stays byte-identical to ``tomli_w`` on real shapes.

    Covers the no-provider path, the empty ``[model_providers]`` table a
    partial pair emits, and a full provider block with the quoted
    ``127.0.0.1`` domain key the permission profile carries.
    """
    import tomli_w

    for name, value in env.items():
        monkeypatch.setenv(name, value)

    text = _write_config(tmp_path, model=_CODEX_MODEL).read_text(encoding="utf-8")
    parsed = tomllib.loads(text)
    redump = tomli_w.dumps(parsed)

    assert text == redump


@pytest.mark.parametrize("codepoint", [*range(0x01, 0x20), 0x7F])
def test_toml_string_escapes_every_forbidden_control_character(codepoint: int) -> None:
    """Each control character TOML forbids must survive a ``tomllib`` round-trip.

    U+0000 is excluded because the OS refuses it in an env var, so it cannot
    reach the renderer; every other code point below U+0020, plus U+007F, can.
    """
    codex_module = _load_codex_module()
    value = f"a{chr(codepoint)}b"

    rendered = codex_module._toml_string(value)

    assert tomllib.loads(f"k = {rendered}")["k"] == value
