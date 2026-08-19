"""Custom OpenAI-compatible provider wiring for the opencode harness."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents.opencode import (
    CUSTOM_PROVIDER_API_KEY_ENV,
    CUSTOM_PROVIDER_BASE_URL_ENV,
    build_security_config,
)

if TYPE_CHECKING:
    from pathlib import Path

NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"
NOUS_MODEL = "nous/deepseek/deepseek-v4-flash"


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CUSTOM_PROVIDER_BASE_URL_ENV, raising=False)
    monkeypatch.delenv(CUSTOM_PROVIDER_API_KEY_ENV, raising=False)
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    monkeypatch.delenv("NOUS_BASE_URL", raising=False)
    monkeypatch.delenv("TOKENHUB_API_KEY", raising=False)
    monkeypatch.delenv("TOKENHUB_BASE_URL", raising=False)
    # W1 indexed multi-provider env vars (operator-locked convention):
    # `MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>` for any N >= 1.
    # Wipe a generous range so a stray index from a previous test does
    # not leak into this one.
    for n in range(1, 8):
        monkeypatch.delenv(f"MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}", raising=False)
        monkeypatch.delenv(f"MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{n}", raising=False)


def _config(tmp_path: Path, model: str | None) -> dict[str, object]:
    ctx = make_agent_run_context(tmp_path, resolved_model=model)
    return json.loads(build_security_config(ctx, model))


def test_custom_provider_is_registered_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CUSTOM_PROVIDER_BASE_URL_ENV, NOUS_BASE_URL)
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, "nous-key")

    config = _config(tmp_path, NOUS_MODEL)

    assert config["provider"] == {
        "nous": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "nous",
            "options": {"baseURL": NOUS_BASE_URL, "apiKey": "nous-key"},
            "models": {"deepseek/deepseek-v4-flash": {"name": "deepseek/deepseek-v4-flash"}},
        }
    }
    assert config["enabled_providers"] == ["nous"]
    assert config["model"] == NOUS_MODEL


@pytest.mark.parametrize(
    ("base_url", "api_key"),
    [(NOUS_BASE_URL, ""), ("", "nous-key"), ("", "")],
)
def test_provider_omitted_unless_both_env_vars_are_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_url: str, api_key: str
) -> None:
    monkeypatch.setenv(CUSTOM_PROVIDER_BASE_URL_ENV, base_url)
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, api_key)

    assert "provider" not in _config(tmp_path, NOUS_MODEL)


def test_provider_omitted_for_an_unprefixed_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CUSTOM_PROVIDER_BASE_URL_ENV, NOUS_BASE_URL)
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, "nous-key")

    assert "provider" not in _config(tmp_path, "deepseek-v4-flash")


def test_unconfigured_environment_leaves_config_unchanged(tmp_path: Path) -> None:
    config = _config(tmp_path, NOUS_MODEL)

    assert "provider" not in config
    assert config["enabled_providers"] == ["nous"]


def test_nous_api_key_alone_registers_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOUS_API_KEY", "nous-key")

    config = _config(tmp_path, NOUS_MODEL)

    assert config["provider"] == {
        "nous": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "nous",
            "options": {"baseURL": NOUS_BASE_URL, "apiKey": "nous-key"},
            "models": {"deepseek/deepseek-v4-flash": {"name": "deepseek/deepseek-v4-flash"}},
        }
    }


def test_tokenhub_api_key_registers_hy3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKENHUB_API_KEY", "th-key")

    config = _config(tmp_path, "tokenhub/hy3")

    assert config["provider"] == {
        "tokenhub": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "tokenhub",
            "options": {
                "baseURL": "https://tokenhub-intl.tencentcloudmaas.com/v1",
                "apiKey": "th-key",
            },
            "models": {"hy3": {"name": "hy3"}},
        }
    }
    assert config["enabled_providers"] == ["tokenhub"]
    assert config["model"] == "tokenhub/hy3"


def test_custom_provider_env_overrides_named_preset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOUS_API_KEY", "nous-key")
    monkeypatch.setenv(CUSTOM_PROVIDER_BASE_URL_ENV, "https://example.test/v1")
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, "custom-key")

    config = _config(tmp_path, NOUS_MODEL)

    assert config["provider"]["nous"]["options"] == {
        "baseURL": "https://example.test/v1",
        "apiKey": "custom-key",
    }


# -- W1.1 (extended): indexed multi-provider OpenCode regression pin --------
#
# The single-provider regression pin is covered by the suite above
# (``test_custom_provider_is_registered_from_env`` etc.). This block extends
# the contract to the operator-locked multi-provider scope: a deployment may
# carry several OpenAI-compatible providers simultaneously, addressed by
# ``MERGECRAFT_CUSTOM_PROVIDER_{API_KEY,BASE_URL}_<N>`` env-var pairs, with
# provider ids derived from the index ``provider_<N>``.
#
# Today the shared helper returns a single optional record, so these tests
# are xfailed; once W3 lifts the helper to a multi-provider shape, the
# markers come off.
#
# Operator-locked convention (W1 design decision, recorded in the wave plan
# and the test-plan doc):
#   - Indexed pair: ``MERGECRAFT_CUSTOM_PROVIDER_API_KEY_<N>`` +
#     ``MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_<N>`` for N >= 1.
#   - Provider id: ``"provider_" + str(N)`` (deterministic, suffix-derived).
#   - Precedence: indexed wins; singleton ``MERGECRAFT_CUSTOM_PROVIDER_*``
#     (no suffix) is a back-compat alias for a single ``default`` provider
#     id, and is IGNORED when any indexed pair is set.


INDEXED_API_KEY_FMT = "MERGECRAFT_CUSTOM_PROVIDER_API_KEY_{n}"
INDEXED_BASE_URL_FMT = "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_{n}"


def test_opencode_emits_provider_blocks_for_each_indexed_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two indexed pairs set → both ``provider_1`` and ``provider_2`` blocks emitted."""
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), "https://provider-1.example.test/v1")
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), "key-1")
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=2), "https://provider-2.example.test/v1")
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=2), "key-2")

    config = _config(tmp_path, "provider_1/some-model")

    provider = config.get("provider")
    assert isinstance(provider, dict)
    assert "provider_1" in provider
    assert "provider_2" in provider
    assert config["provider"]["provider_1"]["options"]["apiKey"] == "key-1"
    assert config["provider"]["provider_2"]["options"]["apiKey"] == "key-2"
    assert "provider_1" in config["enabled_providers"]
    assert "provider_2" in config["enabled_providers"]


def test_opencode_emits_blocks_for_non_contiguous_indices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gaps in the index sequence are preserved: ``_1`` + ``_3`` set,
    ``_2`` absent → providers 1 and 3 present, 2 absent. No renumbering.
    """
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), "https://provider-1.example.test/v1")
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), "key-1")
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=3), "https://provider-3.example.test/v1")
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=3), "key-3")

    config = _config(tmp_path, "provider_1/some-model")

    provider = config.get("provider")
    assert isinstance(provider, dict)
    assert "provider_1" in provider
    assert "provider_3" in provider
    assert "provider_2" not in provider


def test_opencode_partial_indexed_pair_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only ``_1`` API key set (no base URL) → provider 1 absent."""
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), "key-1")
    # Deliberately NOT setting MERGECRAFT_CUSTOM_PROVIDER_BASE_URL_1.

    config = _config(tmp_path, "provider_1/some-model")

    provider = config.get("provider")
    if isinstance(provider, dict):
        assert "provider_1" not in provider


def test_opencode_singleton_alone_emits_default_provider_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Back-compat alias: only the singleton pair is set → a single
    ``default`` provider block is emitted.
    """
    monkeypatch.setenv(CUSTOM_PROVIDER_BASE_URL_ENV, "https://default.example.test/v1")
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, "default-key")

    config = _config(tmp_path, "default/some-model")

    provider = config.get("provider")
    assert isinstance(provider, dict)
    assert "default" in provider
    assert config["provider"]["default"]["options"]["apiKey"] == "default-key"


def test_opencode_indexed_wins_singleton_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Indexed + singleton → only indexed blocks present; singleton does
    NOT contribute an extra ``default`` entry.
    """
    monkeypatch.setenv(CUSTOM_PROVIDER_BASE_URL_ENV, "https://default.example.test/v1")
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, "default-key")
    monkeypatch.setenv(INDEXED_BASE_URL_FMT.format(n=1), "https://provider-1.example.test/v1")
    monkeypatch.setenv(INDEXED_API_KEY_FMT.format(n=1), "key-1")

    config = _config(tmp_path, "provider_1/some-model")

    provider = config.get("provider")
    assert isinstance(provider, dict)
    assert "provider_1" in provider
    assert "default" not in provider
