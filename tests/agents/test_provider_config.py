"""HA1 RED suite — typed ``ProviderConfig`` with declarative capabilities.

Wave plan: ``.ignorelocal/01-review-integrity-wave-plan.md`` (PR HA1).
Locked decisions: **D12** (capabilities are declarative and fail loud) and
**D16** (the ``MERGECRAFT_CUSTOM_PROVIDER_*`` env-var surface is preserved;
HA1 types what already exists and does not change the wire contract).

``ProviderConfig`` lands in HA1.2 as a frozen Pydantic model on
``mergecraft.agents.openai_compatible_gateways`` — **not** the catalog
``mergecraft.models.ProviderConfig``. The key is read through ``api_key_env``
at use time and is never stored on the model (convention 5 / HA1 File 1).
``build_custom_provider`` and ``_custom_provider_ids`` consume the typed
records internally; emitted OpenCode JSON is byte-identical to
``origin/pre-0.0.1``.

HA1.2 landed the typed model; this suite is real passes (xfails cleared).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents.openai_compatible_gateways import (
    CAPABILITY_VALUES,
    resolve_gateway_endpoints,
)
from mergecraft.agents.opencode import _custom_provider_ids, build_custom_provider

# -- env-var surface (D16 / README "Custom OpenAI-compatible provider") ------

INDEXED_API_KEY_FMT = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}"
INDEXED_BASE_URL_FMT = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{n}"
SINGLETON_API_KEY_ENV = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"
SINGLETON_BASE_URL_ENV = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL"

PROVIDER_1_ID = "provider_1"
PROVIDER_2_ID = "provider_2"
PROVIDER_3_ID = "provider_3"

NOUS_MODEL = "nous/deepseek/deepseek-v4-flash"
NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"
TOKENHUB_MODEL = "tokenhub/hy3"
TOKENHUB_BASE_URL = "https://tokenhub-intl.tencentcloudmaas.com/v1"

# Unique canary — deliberately *not* ``sk-`` / ``ghp_`` shaped so sink
# deny-value redaction cannot hide a stored key. Guard-deletion proof:
# adding ``api_key`` to the model makes this value show up in repr / dump.
CANARY_API_KEY = "ha1-canary-NEVER-LEAK-9f3c2a1b"

# Closed capability vocabulary (HA1 File 1). ``context_limit`` is a sibling
# ``int | None`` field, not a set member. Deleting or widening
# ``CAPABILITY_VALUES`` must fail the round-trip pin.
_CLOSED_CAPABILITIES = frozenset(
    {
        "tool_calling",
        "streaming",
        "reasoning_controls",
        "structured_output",
        "custom_base_url",
        "openai_compatible",
        "native_opencode",
    }
)

# Snapshots of ``build_custom_provider`` at origin/pre-0.0.1 @ HEAD. HA1 is a
# refactor: emitted JSON must stay byte-identical for these inputs (D16).
_BYTE_IDENTITY_CASES: tuple[tuple[str, str, dict[str, str], object], ...] = (
    (
        "indexed_pairs",
        "provider_1/some-model",
        {
            INDEXED_BASE_URL_FMT.format(n=1): "https://provider-1.example.test/v1",
            INDEXED_API_KEY_FMT.format(n=1): "key-1",
            INDEXED_BASE_URL_FMT.format(n=2): "https://provider-2.example.test/v1",
            INDEXED_API_KEY_FMT.format(n=2): "key-2",
        },
        {
            "provider_1": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "provider_1",
                "options": {
                    "baseURL": "https://provider-1.example.test/v1",
                    "apiKey": "key-1",
                },
                "models": {"some-model": {"name": "some-model"}},
            },
            "provider_2": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "provider_2",
                "options": {
                    "baseURL": "https://provider-2.example.test/v1",
                    "apiKey": "key-2",
                },
                "models": {},
            },
        },
    ),
    (
        "named_nous",
        NOUS_MODEL,
        {"NOUS_API_KEY": "nous-key"},
        {
            "nous": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "nous",
                "options": {"baseURL": NOUS_BASE_URL, "apiKey": "nous-key"},
                "models": {"deepseek/deepseek-v4-flash": {"name": "deepseek/deepseek-v4-flash"}},
            }
        },
    ),
    (
        "named_tokenhub",
        TOKENHUB_MODEL,
        {"TOKENHUB_API_KEY": "th-key"},
        {
            "tokenhub": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "tokenhub",
                "options": {"baseURL": TOKENHUB_BASE_URL, "apiKey": "th-key"},
                "models": {"hy3": {"name": "hy3"}},
            }
        },
    ),
    (
        "custom_singleton",
        "default/some-model",
        {
            SINGLETON_BASE_URL_ENV: "https://custom.example.test/v1",
            SINGLETON_API_KEY_ENV: "custom-key",
        },
        {
            "default": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "default",
                "options": {
                    "baseURL": "https://custom.example.test/v1",
                    "apiKey": "custom-key",
                },
                "models": {"some-model": {"name": "some-model"}},
            }
        },
    ),
    (
        "custom_base_url_overrides_nous",
        NOUS_MODEL,
        {
            "NOUS_API_KEY": "nous-key",
            SINGLETON_BASE_URL_ENV: "https://override.example.test/v1",
            SINGLETON_API_KEY_ENV: "override-key",
        },
        {
            "nous": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "nous",
                "options": {
                    "baseURL": "https://override.example.test/v1",
                    "apiKey": "override-key",
                },
                "models": {"deepseek/deepseek-v4-flash": {"name": "deepseek/deepseek-v4-flash"}},
            }
        },
    ),
    (
        "partial_pair",
        "provider_1/some-model",
        {INDEXED_API_KEY_FMT.format(n=1): "key-1"},
        None,
    ),
    (
        "index_gaps",
        "provider_1/some-model",
        {
            INDEXED_BASE_URL_FMT.format(n=1): "https://provider-1.example.test/v1",
            INDEXED_API_KEY_FMT.format(n=1): "key-1",
            INDEXED_BASE_URL_FMT.format(n=3): "https://provider-3.example.test/v1",
            INDEXED_API_KEY_FMT.format(n=3): "key-3",
        },
        {
            "provider_1": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "provider_1",
                "options": {
                    "baseURL": "https://provider-1.example.test/v1",
                    "apiKey": "key-1",
                },
                "models": {"some-model": {"name": "some-model"}},
            },
            "provider_3": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "provider_3",
                "options": {
                    "baseURL": "https://provider-3.example.test/v1",
                    "apiKey": "key-3",
                },
                "models": {},
            },
        },
    ),
    (
        "indexed_overrides_singleton",
        "provider_1/some-model",
        {
            SINGLETON_BASE_URL_ENV: "https://default.example.test/v1",
            SINGLETON_API_KEY_ENV: "default-key",
            INDEXED_BASE_URL_FMT.format(n=1): "https://provider-1.example.test/v1",
            INDEXED_API_KEY_FMT.format(n=1): "key-1",
        },
        {
            "provider_1": {
                "npm": "@ai-sdk/openai-compatible",
                "name": "provider_1",
                "options": {
                    "baseURL": "https://provider-1.example.test/v1",
                    "apiKey": "key-1",
                },
                "models": {"some-model": {"name": "some-model"}},
            }
        },
    ),
)


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SINGLETON_BASE_URL_ENV, raising=False)
    monkeypatch.delenv(SINGLETON_API_KEY_ENV, raising=False)
    for n in range(1, 8):
        monkeypatch.delenv(INDEXED_API_KEY_FMT.format(n=n), raising=False)
        monkeypatch.delenv(INDEXED_BASE_URL_FMT.format(n=n), raising=False)
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.delenv("NOUS_BASE_URL", raising=False)
    monkeypatch.delenv("TOKENHUB_API_KEY", raising=False)
    monkeypatch.delenv("TOKENHUB_BASE_URL", raising=False)


def _canonical_json(value: object) -> str:
    """Stable byte form of ``build_custom_provider`` output (D16 pin)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _provider_config_type() -> type:
    """Import HA1's ``ProviderConfig`` — must not be the catalog namesake.

    Import lives in the callee so collection has zero errors until HA1.2.
    """
    from mergecraft.agents.openai_compatible_gateways import ProviderConfig
    from mergecraft.models import ProviderConfig as CatalogProviderConfig

    assert ProviderConfig is not CatalogProviderConfig, (
        "HA1 ProviderConfig must live on openai_compatible_gateways, "
        "not mergecraft.models.ProviderConfig"
    )
    return ProviderConfig


def _make_typed_config(**overrides: object) -> Any:
    """Construct a frozen ``ProviderConfig`` with HA1 File 1's locked fields."""
    provider_config_cls = _provider_config_type()
    kwargs: dict[str, object] = {
        "provider_id": PROVIDER_1_ID,
        "model_id": "some-model",
        "base_url": "https://provider-1.example.test/v1",
        "api_key_env": INDEXED_API_KEY_FMT.format(n=1),
        "adapter": "openai-compatible",
        "capabilities": frozenset(
            {"openai_compatible", "custom_base_url", "tool_calling", "streaming"}
        ),
        "extra_options": {},
        "context_limit": None,
    }
    kwargs.update(overrides)
    return provider_config_cls(**kwargs)


def _assert_key_absent_from_model(config: Any, secret: str) -> None:
    """Fail if the key is stored on the model or leaks through serialisation.

    Deleting the HA1 File 1 guard (adding an ``api_key`` field / computed
    field, or baking the resolved value into repr/dump) must fail this check.
    """
    fields = getattr(type(config), "model_fields", {})
    assert "api_key" not in fields, (
        "ProviderConfig must not store api_key; read it through api_key_env at use time"
    )
    computed = getattr(type(config), "model_computed_fields", {})
    assert "api_key" not in computed, "ProviderConfig must not expose api_key as a computed field"
    dumped = config.model_dump(mode="json")
    assert "api_key" not in dumped
    blob = json.dumps(dumped, default=str) + repr(config) + str(config)
    assert secret not in blob, (
        f"resolved API key leaked from ProviderConfig serialisation: {blob!r}"
    )


# -- regression pins (must pass against current env-pair behaviour) ----------


def test_partial_pair_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only ``_1`` API key set (no base URL) → ``provider_1`` is absent.

    README: both halves of each numeric pair must be set; partial pairs are
    silently dropped. Pins today's ``resolve_gateway_endpoints`` /
    ``build_custom_provider`` / ``_custom_provider_ids`` behaviour.
    """
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), "key-1")

    records = resolve_gateway_endpoints()
    assert PROVIDER_1_ID not in records

    emitted = build_custom_provider("provider_1/some-model")
    if isinstance(emitted, dict):
        assert PROVIDER_1_ID not in emitted
    else:
        assert emitted is None

    assert _custom_provider_ids("provider_1/some-model") == []


def test_gaps_in_indices_are_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_1`` + ``_3`` set, ``_2`` absent → providers 1 and 3 present, 2 absent.

    Discovery preserves gaps (no renumbering). ``_custom_provider_ids``
    mirrors ``build_custom_provider``'s resolution order.
    """
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), "https://provider-1.example.test/v1")
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), "key-1")
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=3), "https://provider-3.example.test/v1")
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=3), "key-3")

    records = resolve_gateway_endpoints()
    assert PROVIDER_1_ID in records
    assert PROVIDER_3_ID in records
    assert PROVIDER_2_ID not in records

    emitted = build_custom_provider("provider_1/some-model")
    assert isinstance(emitted, dict)
    assert PROVIDER_1_ID in emitted
    assert PROVIDER_3_ID in emitted
    assert PROVIDER_2_ID not in emitted

    assert _custom_provider_ids("provider_1/some-model") == [PROVIDER_1_ID, PROVIDER_3_ID]


def test_named_presets_still_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """``nous/*`` and ``tokenhub/*`` still resolve from their named env vars."""
    monkeypatch.setenv("NOUS_API_KEY", "nous-key")
    nous = build_custom_provider(NOUS_MODEL)
    assert nous == {
        "nous": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "nous",
            "options": {"baseURL": NOUS_BASE_URL, "apiKey": "nous-key"},
            "models": {"deepseek/deepseek-v4-flash": {"name": "deepseek/deepseek-v4-flash"}},
        }
    }
    assert _custom_provider_ids(NOUS_MODEL) == ["nous"]

    monkeypatch.delenv("NOUS_API_KEY")
    monkeypatch.setenv("TOKENHUB_API_KEY", "th-key")
    tokenhub = build_custom_provider(TOKENHUB_MODEL)
    assert tokenhub == {
        "tokenhub": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "tokenhub",
            "options": {"baseURL": TOKENHUB_BASE_URL, "apiKey": "th-key"},
            "models": {"hy3": {"name": "hy3"}},
        }
    }
    assert _custom_provider_ids(TOKENHUB_MODEL) == ["tokenhub"]


def test_emitted_opencode_config_is_byte_identical_for_existing_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compatibility pin: ``build_custom_provider`` output matches pre-0.0.1.

    Eight env combinations cover indexed gateway pairs, named presets,
    custom base URL (singleton + nous override), a dropped partial pair,
    preserved index gaps, and indexed-wins-over-singleton. Canonical JSON
    equality is the D16 wire-contract gate that keeps HA1 a refactor.
    """
    mismatches: list[str] = []
    for label, model, env, expected in _BYTE_IDENTITY_CASES:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        actual = build_custom_provider(model)
        if _canonical_json(actual) != _canonical_json(expected):
            mismatches.append(
                f"{label}: expected {_canonical_json(expected)}, got {_canonical_json(actual)}"
            )
        for key in env:
            monkeypatch.delenv(key, raising=False)
    assert not mismatches, "emitted OpenCode provider JSON drifted from pre-0.0.1:\n" + "\n".join(
        mismatches
    )


# -- HA1.2 typed ProviderConfig ----------------------------------------------


def test_gateway_env_pairs_produce_typed_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ``_N`` env-pair form yields ``ProviderConfig`` records with today's ids."""
    provider_config_cls = _provider_config_type()
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), "https://provider-1.example.test/v1")
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), "key-1")
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=2), "https://provider-2.example.test/v1")
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=2), "key-2")

    records = resolve_gateway_endpoints()
    assert set(records) == {PROVIDER_1_ID, PROVIDER_2_ID}
    for provider_id, record in records.items():
        assert isinstance(record, provider_config_cls)
        assert record.provider_id == provider_id
        index = provider_id.rsplit("_", 1)[-1]
        assert record.api_key_env == INDEXED_API_KEY_FMT.format(n=index)
        assert "api_key" not in type(record).model_fields


def test_api_key_never_appears_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Convention 5: the resolved key never appears in ``repr`` / ``str``."""
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), CANARY_API_KEY)
    config = _make_typed_config()
    _assert_key_absent_from_model(config, CANARY_API_KEY)
    assert CANARY_API_KEY not in repr(config)
    assert CANARY_API_KEY not in str(config)


def test_api_key_never_appears_in_json_dump(monkeypatch: pytest.MonkeyPatch) -> None:
    """Convention 5: ``model_dump`` / ``model_dump_json`` never carry the key."""
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), CANARY_API_KEY)
    config = _make_typed_config()
    _assert_key_absent_from_model(config, CANARY_API_KEY)
    dumped = config.model_dump(mode="json")
    dumped_json = config.model_dump_json()
    assert "api_key" not in dumped
    assert CANARY_API_KEY not in dumped_json
    assert CANARY_API_KEY not in json.dumps(dumped)


def test_api_key_never_reaches_trace_attrs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Construct, emit a span, assert the key is absent from the event.

    The attrs payload is the model's own dump — the path production tracing
    will take once HA1.2 serialises ``ProviderConfig`` onto a span. If the
    guard is deleted (key stored on the model), the canary appears in the
    dump *before* sink deny-key redaction can hide a field named ``api_key``.
    """
    from mergecraft.tracing import MemorySink, Tracer

    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), CANARY_API_KEY)
    config = _make_typed_config()
    payload = config.model_dump(mode="json")
    _assert_key_absent_from_model(config, CANARY_API_KEY)

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="ha1-session", run_id="ha1-run")
    with tracer.start_span("provider.config", attrs_source=lambda: {"provider": payload}):
        pass

    assert sink.events, "expected one emitted span"
    event = sink.events[0]
    blob = json.dumps(event.model_dump(), default=str)
    assert CANARY_API_KEY not in blob
    assert CANARY_API_KEY not in json.dumps(payload)


def test_api_key_never_reaches_run_packet(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The resolved key must not land in the run packet's serialised form."""
    from mergecraft.evidence.run_packet import build_run_packet
    from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
    from mergecraft.modes import compute_modes
    from mergecraft.utils.github import GitHubClient

    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), CANARY_API_KEY)
    config = _make_typed_config()
    _assert_key_absent_from_model(config, CANARY_API_KEY)

    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    diff_path = tmp_path / "pr-42.diff"
    diff_path.write_text(
        "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n",
        encoding="utf-8",
    )
    primary_repo_state(tool_state).diff_path = str(diff_path)
    ctx = ToolContext(
        agent_id="opencode",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request", issue_number=42)),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("opencode"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        resolved_model="provider_1/some-model",
    )
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    blob = packet.model_dump_json() + json.dumps(config.model_dump(mode="json"))
    assert CANARY_API_KEY not in blob
    assert "api_key" not in config.model_dump(mode="json")


def test_unsupported_capability_is_a_configuration_error() -> None:
    """D12: requesting an unsupported capability is a configuration error
    *before* agent execution, not a runtime degradation.
    """
    from mergecraft.agents.openai_compatible_gateways import require_capabilities
    from mergecraft.main import _ConfigurationError

    config = _make_typed_config(
        capabilities=frozenset({"openai_compatible", "custom_base_url"}),
    )
    with pytest.raises(_ConfigurationError, match="structured_output"):
        require_capabilities(config, frozenset({"structured_output"}))


def test_capability_declaration_round_trips() -> None:
    """Declared capabilities survive dump/validate and into the harness records."""
    declared = frozenset({"tool_calling", "streaming", "openai_compatible", "custom_base_url"})
    config = _make_typed_config(
        capabilities=declared, extra_options={"wire": "chat"}, context_limit=128_000
    )
    assert config.capabilities == declared
    assert declared <= _CLOSED_CAPABILITIES
    assert CAPABILITY_VALUES == _CLOSED_CAPABILITIES
    provider_config_cls = _provider_config_type()
    restored = provider_config_cls.model_validate(config.model_dump(mode="json"))
    assert restored.capabilities == declared
    assert restored.extra_options == {"wire": "chat"}
    assert restored.context_limit == 128_000
    assert restored.adapter == "openai-compatible"
    assert restored.api_key_env == INDEXED_API_KEY_FMT.format(n=1)


def test_custom_base_url_validates() -> None:
    """A malformed base URL is rejected at construction, before execution."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _make_typed_config(base_url="not a url")
