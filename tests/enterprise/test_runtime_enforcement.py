"""Enterprise controls applied through settings, sinks, and routing (#381)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mergecraft.config.settings import (
    RepoSettings,
    apply_trust_tier_to_repo_settings,
    load_repo_settings,
)
from mergecraft.enterprise.controls import EnterpriseSettings
from mergecraft.enterprise.runtime import (
    bind_enterprise_after_trust,
    bind_enterprise_from_settings,
)
from mergecraft.tracing.sinks import JSONLFileSink, NullSink, sink_factory


def test_telemetry_off_skips_remote_sinks() -> None:
    """Opt-out/off telemetry must not construct Logfire/OTLP exporters."""
    bind_enterprise_from_settings(EnterpriseSettings(telemetry="off"))
    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire"}],
            }
        }
    )
    sink = sink_factory(settings.tracing)
    assert isinstance(sink, NullSink)
    from mergecraft.tracing.exporters import has_active_tracer_provider

    assert not has_active_tracer_provider()


def test_residency_policy_blocks_routed_us_model() -> None:
    """A bound EU-only allow-list refuses catalog models in us-east-1."""
    from mergecraft.agents.provider_health import route_model

    bind_enterprise_from_settings(EnterpriseSettings(allowed_regions=("eu-west-1",)))
    with pytest.raises(PermissionError, match="residency"):
        route_model(specialist="security", risk="high")


def test_apply_enterprise_proxy_sets_http_and_clears_stale_no_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP(S) proxy export includes HTTP_PROXY and drops an empty NO_PROXY."""
    monkeypatch.setenv("NO_PROXY", "stale.example")
    from mergecraft.enterprise.proxy import ProxyConfig, apply_enterprise_proxy

    apply_enterprise_proxy(ProxyConfig(https_proxy="http://proxy.example:8080", no_proxy=""))
    assert os.environ.get("HTTPS_PROXY") == "http://proxy.example:8080"
    assert os.environ.get("HTTP_PROXY") == "http://proxy.example:8080"
    assert "NO_PROXY" not in os.environ


def test_bind_custom_ca_exports_ssl_cert_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured CA PEM is validated and exported as SSL_CERT_FILE."""
    from tests.enterprise.test_certificates import _write_self_signed_ca

    for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name, raising=False)
    pem = tmp_path / "ca.pem"
    _write_self_signed_ca(pem)
    bind_enterprise_from_settings(EnterpriseSettings(ca_file=str(pem)))
    assert os.environ.get("SSL_CERT_FILE") == str(pem)


def test_enterprise_retention_overrides_jsonl_sink(tmp_path: Path) -> None:
    """Bound retention days land on the JSONL sink used by tracing export."""
    bind_enterprise_from_settings(EnterpriseSettings(retention_days=7))
    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "retentionDays": 30,
                "sinks": [{"type": "jsonl_file", "path": str(tmp_path)}],
            }
        }
    )
    wrapper = sink_factory(settings.tracing)
    inner = wrapper.inner.sinks[0]
    assert isinstance(inner, JSONLFileSink)
    assert inner.retention_days == 7


def test_repo_settings_enterprise_block_round_trips() -> None:
    """YAML ``enterprise:`` keys bind through RepoSettings."""
    settings = RepoSettings.model_validate(
        {"enterprise": {"telemetry": "opt-out", "allowedRegions": ["eu-west-1"]}}
    )
    bind_enterprise_from_settings(settings)
    from mergecraft.enterprise.runtime import remote_export_allowed

    assert remote_export_allowed() is False


def test_load_repo_settings_does_not_export_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parsing untrusted config must not mutate the process network environment."""
    for name in ("HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        monkeypatch.delenv(name, raising=False)
    config_dir = tmp_path / ".mergecraft"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "enterprise:\n  httpsProxy: http://attacker.example:8080\n  caFile: /tmp/evil.pem\n",
        encoding="utf-8",
    )
    raw = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert raw.enterprise.https_proxy == "http://attacker.example:8080"
    assert "HTTPS_PROXY" not in os.environ
    assert "HTTP_PROXY" not in os.environ

    filtered, drops = apply_trust_tier_to_repo_settings(raw, "untrusted", source_label="fork PR")
    bind_enterprise_after_trust(filtered, "untrusted")
    assert "enterprise.network" in drops
    assert filtered.enterprise.https_proxy == ""
    assert filtered.enterprise.ca_file is None
    assert "HTTPS_PROXY" not in os.environ
    assert "HTTP_PROXY" not in os.environ
    assert "SSL_CERT_FILE" not in os.environ


def test_trusted_bind_after_trust_exports_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Trusted tier applies proxy only after trust resolution."""
    for name in ("HTTPS_PROXY", "HTTP_PROXY"):
        monkeypatch.delenv(name, raising=False)
    config_dir = tmp_path / ".mergecraft"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "enterprise:\n  httpsProxy: http://proxy.example:8080\n",
        encoding="utf-8",
    )
    raw = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert os.environ.get("HTTPS_PROXY") is None
    filtered, drops = apply_trust_tier_to_repo_settings(raw, "trusted", source_label="same-repo PR")
    assert not drops
    bind_enterprise_after_trust(filtered, "trusted")
    assert os.environ.get("HTTPS_PROXY") == "http://proxy.example:8080"


def test_residency_blocks_effective_model_chain_and_resolve() -> None:
    """Reviews resolve models via effective_model_chain / resolve_model, not route_model."""
    from mergecraft.utils.agent_resolve import effective_model_chain, resolve_model

    bind_enterprise_from_settings(EnterpriseSettings(allowed_regions=("eu-west-1",)))
    settings = RepoSettings.model_validate({"models": ["anthropic/claude-opus"]})
    with pytest.raises(PermissionError, match=r"allowedRegions|residency"):
        effective_model_chain(settings)
    with pytest.raises(PermissionError, match="residency"):
        resolve_model(slug="anthropic/claude-opus", respect_env_override=False)


def test_disallowed_model_is_never_selected_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """A residency miss must not pick a runnable slug even when credentials exist."""
    from mergecraft.utils import agent_resolve
    from mergecraft.utils.agent_resolve import (
        effective_model_chain,
        pick_runnable_slug_from_chain,
    )

    bind_enterprise_from_settings(EnterpriseSettings(allowed_regions=("eu-west-1",)))
    monkeypatch.setattr(agent_resolve, "has_credentials_for_slug", lambda _slug: True)
    monkeypatch.setattr(agent_resolve, "_agent_binary_available", lambda _slug: True)
    settings = RepoSettings.model_validate({"models": ["anthropic/claude-opus"]})
    with pytest.raises(PermissionError, match=r"allowedRegions|residency"):
        pick_runnable_slug_from_chain(effective_model_chain(settings))


def test_in_region_vertex_model_passes_residency() -> None:
    """Vertex BYOK is catalogued in eu-west-1 so an EU allow-list can run a review."""
    from mergecraft.utils.agent_resolve import effective_model_chain

    bind_enterprise_from_settings(EnterpriseSettings(allowed_regions=("eu-west-1",)))
    settings = RepoSettings.model_validate({"models": ["vertex/byok"]})
    assert effective_model_chain(settings) == ["vertex/byok"]
    from mergecraft.enterprise.runtime import enforce_routed_model_residency

    enforce_routed_model_residency("vertex/byok")


def test_providers_catalog_us_model_passes_us_residency() -> None:
    """Support-matrix PROVIDERS slugs (not only the 4 routing rows) carry us-east-1."""
    from mergecraft.models import lookup_model_data_residency
    from mergecraft.utils.agent_resolve import effective_model_chain

    assert lookup_model_data_residency("openai/gpt") == "us-east-1"
    assert lookup_model_data_residency("openrouter/openai/gpt-5.6-sol") == "us-east-1"
    bind_enterprise_from_settings(EnterpriseSettings(allowed_regions=("us-east-1",)))
    settings = RepoSettings.model_validate({"models": ["openai/gpt"]})
    assert effective_model_chain(settings) == ["openai/gpt"]


def test_undeclared_gateway_residency_fails_closed() -> None:
    """TokenHub / MiniMax / OpenCode have no region and are refused on a US allow-list."""
    from mergecraft.models import lookup_model_data_residency
    from mergecraft.utils.agent_resolve import effective_model_chain

    assert lookup_model_data_residency("tokenhub/hy3") is None
    assert lookup_model_data_residency("minimax/MiniMax-M3") is None
    assert lookup_model_data_residency("deepseek/deepseek-pro") == "cn-north-1"
    bind_enterprise_from_settings(EnterpriseSettings(allowed_regions=("us-east-1",)))
    with pytest.raises(PermissionError, match=r"allowedRegions|residency"):
        effective_model_chain(RepoSettings.model_validate({"models": ["tokenhub/hy3"]}))
    with pytest.raises(PermissionError, match=r"allowedRegions|residency"):
        effective_model_chain(RepoSettings.model_validate({"models": ["deepseek/deepseek-pro"]}))


def test_invalid_telemetry_mode_fails_at_config_load() -> None:
    """A telemetry typo names enterprise.telemetry instead of crashing later."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=r"enterprise\.telemetry"):
        EnterpriseSettings.model_validate({"telemetry": "maybe"})


def test_enterprise_retention_purges_expired_jsonl_on_write(
    tmp_path: Path,
) -> None:
    """enterprise.retentionDays deletes expired JSONL files on the write path."""
    from mergecraft.tracing.event import TraceEvent
    from mergecraft.tracing.sinks import sink_factory

    bind_enterprise_from_settings(EnterpriseSettings(retention_days=1))
    expired = tmp_path / "2020-01-01.jsonl"
    expired.write_text("{}\n", encoding="utf-8")
    expired.touch()
    import os
    import time

    old = time.time() - 3 * 86_400
    os.utime(expired, (old, old))
    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "jsonl_file", "path": str(tmp_path)}],
            }
        }
    )
    sink = sink_factory(settings.tracing)
    sink.write(
        TraceEvent(
            kind="mergecraft.run",
            span_id="span-retention",
            session_id="sess",
            turn_id="turn",
            trace_id="trace",
            tier="trusted",
            ts_start_ns=1,
            ts_end_ns=2,
            status="ok",
        )
    )
    assert not expired.exists()
