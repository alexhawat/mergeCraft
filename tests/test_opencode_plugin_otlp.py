"""Runtime checks for the OpenCode plugin's OTLP/Logfire helpers.

Runs `integrations/opencode/plugins/mergecraft/otlp.ts` under Node and asserts
the exported span payload is valid OpenTelemetry: 32-hex trace id, 16-hex span
id, both non-zero. Skips when Node is unavailable or cannot execute TypeScript.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
OTLP_TS = REPO_ROOT / "integrations" / "opencode" / "plugins" / "mergecraft" / "otlp.ts"
MANIFEST = REPO_ROOT / "integrations" / "opencode" / "plugins" / "mergecraft" / "package.json"

_SCRIPT = """
const m = await import(__MODULE__);
const traceId = m.randomHex(16);
const spanId = m.randomHex(8);
const payload = m.buildOtlpPayload({
  name: "mergecraft.review.native",
  attributes: { "mergecraft.engine": "native", "mergecraft.duration_ms": 12 },
  traceId,
  spanId,
  nowMs: 1700000000000,
  project: "proj",
});
console.log(JSON.stringify({
  traceId,
  spanId,
  targetUs: m.logfireTarget({ LOGFIRE_TOKEN: "x" }),
  targetEu: m.logfireTarget({
    MERGECRAFT_LOGFIRE_TOKEN: "y",
    MERGECRAFT_TRACING_REGION: "EU",
    MERGECRAFT_TRACING_PROJECT: "proj",
  }),
  targetNone: m.logfireTarget({}),
  payload,
}));
"""


def _run_node() -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    script = _SCRIPT.replace("__MODULE__", repr(OTLP_TS.as_uri()))
    attempts = (
        [node, "--input-type=module", "-e", script],
        [node, "--experimental-strip-types", "--input-type=module", "-e", script],
    )
    last: subprocess.CompletedProcess[str] | None = None
    for argv in attempts:
        last = subprocess.run(argv, capture_output=True, text=True, check=False, cwd=REPO_ROOT)
        if last.returncode == 0:
            return json.loads(last.stdout.strip().splitlines()[-1])
    pytest.skip(f"node cannot execute TypeScript: {(last.stderr if last else '')[:200]}")
    raise AssertionError("unreachable")


def test_otlp_ids_are_non_zero_hex() -> None:
    result = _run_node()
    trace_id = str(result["traceId"])
    span_id = str(result["spanId"])
    assert len(trace_id) == 32
    assert len(span_id) == 16
    assert set(trace_id) != {"0"}
    assert set(span_id) != {"0"}


def test_otlp_payload_shape_and_attributes() -> None:
    result = _run_node()
    payload = result["payload"]
    assert isinstance(payload, dict)
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["traceId"] == result["traceId"]
    assert span["spanId"] == result["spanId"]
    assert span["name"] == "mergecraft.review.native"
    assert span["startTimeUnixNano"] == "1700000000000000000"
    assert span["attributes"][0] == {"key": "mergecraft.engine", "value": {"stringValue": "native"}}
    assert span["attributes"][1] == {"key": "mergecraft.duration_ms", "value": {"intValue": "12"}}


def test_plugin_manifest_targets_v2_contract() -> None:
    """The plugin is V2-only; the manifest must not advertise V1 compatibility."""
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dependency = data["dependencies"]["@opencode/plugin"]
    peer = data["peerDependencies"]["opencode"]
    assert dependency != "latest"
    assert dependency.startswith(("^2", ">=2"))
    assert peer.startswith(">=2")
    assert "1.18" not in peer


def test_logfire_target_region_and_absence() -> None:
    result = _run_node()
    assert result["targetUs"]["url"] == "https://logfire-us.pydantic.dev/v1/traces"
    assert result["targetUs"]["token"] == "x"
    assert result["targetEu"]["url"] == "https://logfire-eu.pydantic.dev/v1/traces"
    assert result["targetEu"]["project"] == "proj"
    assert result["targetNone"] is None
