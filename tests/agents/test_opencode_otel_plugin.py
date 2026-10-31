"""Per-run wiring of the OpenCode V2 OTel plugin (``agents/opencode_otel.py``).

The plugin is opt-in (``MERGECRAFT_OPENCODE_OTEL_PLUGIN``), exports to the active
OTLP sink's endpoint under the active ``mergecraft.agent.run`` span, and takes its
``captureContent`` from mergeCraft's content policy — including the untrusted cap.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from mergecraft.agents import opencode_otel
from mergecraft.agents.opencode_otel import (
    OTEL_PLUGIN_ENV,
    OtelPluginWiring,
    apply_otel_plugin,
    opencode_otel_plugin_wiring,
)
from mergecraft.tracing import MultiSink, OTLPSink, Tracer
from mergecraft.tracing.content import ContentCapture
from mergecraft.tracing.sinks import RedactingSink

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"


PLUGIN = ""


_SUPPORTED = "captureContent?: ContentCapture"
_UNSUPPORTED = "logsEnabled?: boolean"


def _plugin_dir(root: Path, *, supports_capture: bool) -> str:
    """A source-entry plugin checkout (``exports: ./src/index.ts``), as the plugin ships."""
    (root / "src").mkdir(parents=True)
    option = _SUPPORTED if supports_capture else _UNSUPPORTED
    (root / "src" / "config.ts").write_text(f"export type OtelPluginOptions = {{ {option} }}\n")
    (root / "src" / "index.ts").write_text("export { plugin } from './plugin'\n")
    (root / "package.json").write_text(json.dumps({"exports": {".": "./src/index.ts"}}))
    return str(root)


def _built_plugin_dir(root: Path, *, built_supports_capture: bool) -> str:
    """A checkout whose runtime entry is ``dist/``, with up-to-date ``src/`` beside it."""
    _plugin_dir(root, supports_capture=True)
    (root / "dist").mkdir()
    option = _SUPPORTED if built_supports_capture else _UNSUPPORTED
    (root / "dist" / "config.js").write_text(f"// {option}\n")
    (root / "dist" / "index.js").write_text("export { plugin } from './plugin.js'\n")
    (root / "package.json").write_text(
        json.dumps({"exports": {".": {"import": "./dist/index.js", "types": "./dist/index.d.ts"}}})
    )
    return str(root)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    global PLUGIN
    PLUGIN = _plugin_dir(tmp_path / "plugin", supports_capture=True)
    for name in (
        OTEL_PLUGIN_ENV,
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "MERGECRAFT_TRACING_CONTENT",
        "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT",
    ):
        monkeypatch.delenv(name, raising=False)
    # No repo config here: the content policy resolves from defaults.
    monkeypatch.chdir(tmp_path)


def _tracer(sink: Any) -> Tracer:
    return Tracer(sink=sink, session_id="s", run_id="r", trace_id=TRACE_ID)


def _otel_sink(headers: dict[str, str] | None = None) -> OTLPSink:
    # ``provider=object()`` short-circuits provider setup: no network, no global state.
    return OTLPSink(
        endpoint="https://otlp.example.test/v1/traces",
        headers=headers,
        service_name="mergecraft-otel",
        provider=object(),
    )


def _wiring_under_span(sink: Any, trust_tier: str | None = "trusted") -> tuple[Any, Any]:
    tracer = _tracer(RedactingSink(MultiSink([sink])))
    with tracer.start_span("mergecraft.agent.run") as span:
        return opencode_otel_plugin_wiring(trust_tier), span


def test_not_enabled_without_the_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    wiring, _ = _wiring_under_span(_otel_sink())
    assert wiring is None


def test_not_enabled_without_an_active_span(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    assert opencode_otel_plugin_wiring("trusted") is None


def test_not_enabled_without_an_otlp_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    from mergecraft.tracing import MemorySink

    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    wiring, _ = _wiring_under_span(MemorySink())
    assert wiring is None


def test_entry_targets_the_sink_under_the_agent_span(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS", "dd-api-key=secret-123,dd-otlp-source=llmobs"
    )

    wiring, span = _wiring_under_span(_otel_sink())

    assert wiring is not None
    assert wiring.entry["package"] == PLUGIN
    options = wiring.entry["options"]
    assert options["endpoint"] == "https://otlp.example.test"
    assert options["protocol"] == "http/protobuf"
    assert options["resourceAttributes"] == "service.name=mergecraft-otel"
    assert options["traceparent"] == f"00-{TRACE_ID}-{span.span_id[:16]}-01"
    assert options["logsEnabled"] is False
    assert options["capturePromptInLogs"] is False
    assert options["disabledMetrics"] == ["all"]


def test_header_values_ride_env_refs_not_the_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """A secret header must never be written into the on-disk opencode.json."""
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS", "dd-api-key=secret-123,dd-otlp-source=llmobs"
    )

    wiring, _ = _wiring_under_span(_otel_sink())

    assert wiring is not None
    assert "secret-123" not in json.dumps(wiring.entry)
    assert wiring.entry["options"]["otlpHeaders"] == (
        "dd-api-key={env:MERGECRAFT_OPENCODE_OTLP_HEADER_0},"
        "dd-otlp-source={env:MERGECRAFT_OPENCODE_OTLP_HEADER_1}"
    )
    assert wiring.env == {
        "MERGECRAFT_OPENCODE_OTLP_HEADER_0": "secret-123",
        "MERGECRAFT_OPENCODE_OTLP_HEADER_1": "llmobs",
    }


def test_sink_headers_win_over_the_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Logfire-style sink carries its own Authorization header."""
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "dd-api-key=ignored")

    wiring, _ = _wiring_under_span(_otel_sink({"authorization": "Bearer lf-token"}))

    assert wiring is not None
    assert wiring.env["MERGECRAFT_OPENCODE_OTLP_HEADER_0"] == "Bearer lf-token"


def test_env_headers_are_decoded_like_the_python_exporter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plugin forwards headers verbatim, so a percent-escape must be decoded first.

    Otherwise mergeCraft's spans authenticate and every plugin export fails.
    """
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    monkeypatch.setenv(
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        "Authorization=Bearer%20synthetic-token%2Bwith%2Fchars%3D",
    )

    wiring, _ = _wiring_under_span(_otel_sink())

    assert wiring is not None
    assert wiring.entry["options"]["otlpHeaders"] == (
        "authorization={env:MERGECRAFT_OPENCODE_OTLP_HEADER_0}"
    )
    assert wiring.env["MERGECRAFT_OPENCODE_OTLP_HEADER_0"] == "Bearer synthetic-token+with/chars="


@pytest.mark.parametrize("header", ["X-Scope=a%2Cb", "X-Quote=a%22b", "X-Line=a%0Ab"])
def test_a_header_that_cannot_be_forwarded_intact_disables_the_plugin(
    monkeypatch: pytest.MonkeyPatch, header: str
) -> None:
    """``,`` splits the plugin's header list and ``"``/newline break the JSON config."""
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", header)

    wiring, _ = _wiring_under_span(_otel_sink())

    assert wiring is None


def test_forwarded_credentials_are_registered_with_the_plugin_redactor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An opaque key forwarded under a renamed env var is invisible to the plugin's
    secret-name scan, so each value — and a ``Scheme`` value's bare credential — goes
    to ``redactValues``, by env reference so it never reaches the config on disk.
    """
    opaque = "0123456789abcdef0123456789abcdef"
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)

    wiring, _ = _wiring_under_span(
        _otel_sink({"dd-api-key": opaque, "authorization": "Bearer lf-token-value"})
    )

    assert wiring is not None
    assert wiring.entry["options"]["redactValues"] == [
        "{env:MERGECRAFT_OPENCODE_OTLP_HEADER_0}",
        "{env:MERGECRAFT_OPENCODE_OTLP_HEADER_1}",
        "{env:MERGECRAFT_OPENCODE_OTLP_HEADER_1_CREDENTIAL}",
    ]
    assert wiring.env["MERGECRAFT_OPENCODE_OTLP_HEADER_0"] == opaque
    assert wiring.env["MERGECRAFT_OPENCODE_OTLP_HEADER_1_CREDENTIAL"] == "lf-token-value"
    serialized = json.dumps(wiring.entry)
    assert opaque not in serialized
    assert "lf-token-value" not in serialized


@pytest.mark.parametrize(
    ("level", "plugin_mode"),
    [
        (ContentCapture.OFF, "off"),
        (ContentCapture.METADATA, "metadata"),
        (ContentCapture.REDACTED, "full"),
        (ContentCapture.FULL, "full"),
    ],
)
def test_capture_content_follows_the_policy(
    monkeypatch: pytest.MonkeyPatch, level: ContentCapture, plugin_mode: str
) -> None:
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    seen: list[str | None] = []
    monkeypatch.setattr(
        opencode_otel, "resolve_capture_policy", lambda tier: seen.append(tier) or level
    )

    wiring, _ = _wiring_under_span(_otel_sink(), trust_tier="untrusted")

    assert wiring is not None
    assert wiring.entry["options"]["captureContent"] == plugin_mode
    assert seen == ["untrusted"]


def test_untrusted_run_is_capped_to_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """D7, end to end: even ``content: full`` ships no bodies from an untrusted run."""
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    monkeypatch.setenv("MERGECRAFT_TRACING_CONTENT", "full")

    untrusted, _ = _wiring_under_span(_otel_sink(), trust_tier="untrusted")
    unknown, _ = _wiring_under_span(_otel_sink(), trust_tier=None)
    trusted, _ = _wiring_under_span(_otel_sink(), trust_tier="trusted")

    assert untrusted is not None
    assert unknown is not None
    assert trusted is not None
    assert untrusted.entry["options"]["captureContent"] == "metadata"
    assert unknown.entry["options"]["captureContent"] == "metadata"
    assert trusted.entry["options"]["captureContent"] == "full"


def test_apply_replaces_an_entry_for_the_same_package() -> None:
    config = json.dumps(
        {
            "agent": {"build": {}},
            "plugins": [
                {"package": PLUGIN, "options": {"endpoint": "https://global.example"}},
                {"package": "/opt/plugins/other"},
            ],
        }
    )
    wiring = OtelPluginWiring(entry={"package": PLUGIN, "options": {"endpoint": "https://run"}})

    merged = json.loads(apply_otel_plugin(config, wiring))

    assert merged["agent"] == {"build": {}}
    assert merged["plugins"] == [
        {"package": "/opt/plugins/other"},
        {"package": PLUGIN, "options": {"endpoint": "https://run"}},
    ]


# ── the OpenCode driver ───────────────────────────────────────────────────────


@pytest.fixture
def driver(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the OpenCode CLI so ``_run`` records what it would launch."""
    import shutil

    from mergecraft.agents import opencode as oc
    from mergecraft.agents.shared import AgentResult

    monkeypatch.setattr(oc, "_OPENCODE_MAJOR_CACHE", {})
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/bin/opencode")
    seen: dict[str, Any] = {}

    async def _v2(*, cli: str, ctx: Any, env: dict[str, str], model: str | None) -> AgentResult:
        seen["env"] = env
        return AgentResult(success=True, output="ok")

    def _boot(**kwargs: Any) -> Any:
        raise RuntimeError("1.x boot stub")

    monkeypatch.setattr(oc, "_run_v2", _v2)
    monkeypatch.setattr(oc, "_boot_opencode_server", _boot)
    monkeypatch.setattr(oc, "_boot_opencode_server_with_retries", _boot, raising=False)
    seen["oc"] = oc
    return seen


async def test_driver_loads_the_plugin_on_2x(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, driver: dict[str, Any]
) -> None:
    from tests.agents.conftest import make_agent_run_context

    oc = driver["oc"]
    monkeypatch.setattr(oc, "_opencode_major_version", lambda _cli: 2)
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "dd-api-key=secret-123")
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    tracer = _tracer(RedactingSink(MultiSink([_otel_sink()])))
    with tracer.start_span("mergecraft.agent.run"):
        result = await oc._run(ctx)

    assert result.success is True
    env = driver["env"]
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    [entry] = [p for p in config["plugins"] if p["package"] == PLUGIN]
    assert entry["options"]["endpoint"] == "https://otlp.example.test"
    assert env["MERGECRAFT_OPENCODE_OTLP_HEADER_0"] == "secret-123"
    on_disk = await asyncio.to_thread(Path(env["OPENCODE_CONFIG"]).read_text, encoding="utf-8")
    assert "secret-123" not in on_disk
    assert PLUGIN in on_disk


async def test_driver_never_loads_the_plugin_on_1x(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, driver: dict[str, Any]
) -> None:
    from tests.agents.conftest import make_agent_run_context

    oc = driver["oc"]
    monkeypatch.setattr(oc, "_opencode_major_version", lambda _cli: 1)
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)
    captured: list[str] = []
    real_apply = oc.apply_otel_plugin
    monkeypatch.setattr(
        oc, "apply_otel_plugin", lambda *a: captured.append("applied") or real_apply(*a)
    )
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    tracer = _tracer(RedactingSink(MultiSink([_otel_sink()])))
    # 1.x falls back from the (stubbed, failing) server to ``opencode run``; the
    # outcome is irrelevant here, only that the plugin was never wired in.
    with tracer.start_span("mergecraft.agent.run"):
        await oc._run(ctx)

    assert captured == []


def test_plugin_without_capture_content_is_refused_at_every_level(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An older plugin ignores ``captureContent`` (and may not redact) even under ``redacted``."""
    old = _plugin_dir(tmp_path / "old-plugin", supports_capture=False)
    monkeypatch.setenv(OTEL_PLUGIN_ENV, old)

    untrusted, _ = _wiring_under_span(_otel_sink(), trust_tier="untrusted")
    trusted, _ = _wiring_under_span(_otel_sink(), trust_tier="trusted")

    assert untrusted is None
    assert trusted is None


def test_updated_source_with_a_stale_build_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A checkout pulled but not rebuilt: ``src/`` reads ``captureContent``, the
    ``dist/`` OpenCode imports does not and would export bodies. Fail closed."""
    stale = _built_plugin_dir(tmp_path / "stale", built_supports_capture=False)
    monkeypatch.setenv(OTEL_PLUGIN_ENV, stale)

    wiring, _ = _wiring_under_span(_otel_sink(), trust_tier="untrusted")

    assert wiring is None


def test_a_rebuilt_dist_entry_is_accepted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    built = _built_plugin_dir(tmp_path / "built", built_supports_capture=True)
    monkeypatch.setenv(OTEL_PLUGIN_ENV, built)

    wiring, _ = _wiring_under_span(_otel_sink(), trust_tier="untrusted")

    assert wiring is not None
    assert wiring.entry["options"]["captureContent"] == "metadata"


@pytest.mark.parametrize(
    "manifest",
    [
        None,
        {"exports": {".": "./src/missing.ts"}},
        {"exports": {".": "../outside/index.ts"}},
        {"name": "no-entry"},
    ],
)
def test_a_plugin_without_a_resolvable_runtime_entry_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, manifest: dict[str, Any] | None
) -> None:
    """Supporting source proves nothing unless it is the code OpenCode imports."""
    root = Path(_plugin_dir(tmp_path / "plugin-x", supports_capture=True))
    if manifest is None:
        (root / "package.json").unlink()
    else:
        (root / "package.json").write_text(json.dumps(manifest))
    monkeypatch.setenv(OTEL_PLUGIN_ENV, str(root))

    wiring, _ = _wiring_under_span(_otel_sink(), trust_tier="trusted")

    assert wiring is None


def test_a_package_spec_cannot_prove_support(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OTEL_PLUGIN_ENV, "opencode-plugin-otel-v2")

    untrusted, _ = _wiring_under_span(_otel_sink(), trust_tier="untrusted")

    assert untrusted is None


async def test_driver_isolates_the_global_opencode_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, driver: dict[str, Any]
) -> None:
    """A global ``mergecraft`` MCP server or plugin must not join the review run."""
    from tests.agents.conftest import make_agent_run_context

    oc = driver["oc"]
    monkeypatch.setattr(oc, "_opencode_major_version", lambda _cli: 2)
    ctx = make_agent_run_context(tmp_path, resolved_model=None)

    await oc._run(ctx)

    assert driver["env"]["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    config_dir = Path(driver["env"]["OPENCODE_CONFIG_DIR"])
    assert config_dir == Path(ctx.tmpdir) / "opencode-xdg-config"
    entries = await asyncio.to_thread(lambda: list(config_dir.iterdir()))
    assert entries == []


def test_plugin_spans_join_the_review_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """The plugin keys spans by OpenCode session; the review id makes them one session."""
    monkeypatch.setenv(OTEL_PLUGIN_ENV, PLUGIN)

    wiring, _ = _wiring_under_span(_otel_sink())

    assert wiring is not None
    assert wiring.entry["options"]["spanAttributes"] == f"gen_ai.conversation.id={TRACE_ID}"
