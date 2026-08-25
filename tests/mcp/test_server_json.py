"""MP1.4 — generated ``server.json`` contracts."""

from __future__ import annotations

import json
import subprocess
from typing import Any

from tests.ci.workflow_support import REPO_ROOT
from tests.docs.support import ci_steps, load_script_module

_SCHEMA_PATH = REPO_ROOT / "tests" / "fixtures" / "mcp" / "server.schema.2025-12-11.json"
_SERVER_JSON = REPO_ROOT / "server.json"
_RUNTIME_TOOL_SAMPLES = ("push_branch", "checkout_pr")


def _load_schema() -> dict[str, Any]:
    assert _SCHEMA_PATH.is_file(), f"missing vendored schema {_SCHEMA_PATH.relative_to(REPO_ROOT)}"
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_server_json(data: dict[str, Any]) -> None:
    import jsonschema

    jsonschema.validate(instance=data, schema=_load_schema())


def test_server_json_exists_and_matches_schema() -> None:
    assert _SERVER_JSON.is_file(), "repo-root server.json missing (MP4)"
    data = json.loads(_SERVER_JSON.read_text(encoding="utf-8"))
    _validate_server_json(data)


def test_server_json_name_is_io_github_alexhawat_mergecraft() -> None:
    data = json.loads(_SERVER_JSON.read_text(encoding="utf-8"))
    assert data.get("name") == "io.github.alexhawat/mergecraft"


def test_server_json_package_is_pypi_merge_craft_stdio_public() -> None:
    data = json.loads(_SERVER_JSON.read_text(encoding="utf-8"))
    packages = data.get("packages")
    assert isinstance(packages, list), data
    assert packages, data
    pkg = packages[0]
    assert pkg.get("registryType") == "pypi"
    assert pkg.get("identifier") == "merge-craft"
    transport = pkg.get("transport") or {}
    assert transport.get("type") == "stdio"
    command = transport.get("command") or transport.get("args")
    command_text = json.dumps(command)
    assert "mergecraft" in command_text
    assert "public" in command_text
    assert "stdio" in command_text


def test_server_json_does_not_advertise_runtime_tool_names() -> None:
    data = json.loads(_SERVER_JSON.read_text(encoding="utf-8"))
    blob = json.dumps(data)
    for name in _RUNTIME_TOOL_SAMPLES:
        assert name not in blob


def test_make_mcp_server_json_check_in_ci_steps() -> None:
    assert "mcp-server-json-check" in ci_steps()


def test_generator_check_detects_drift() -> None:
    gen = load_script_module("scripts/gen_mcp_server_json.py")
    assert hasattr(gen, "main") or hasattr(gen, "run_check"), gen
    assert _SERVER_JSON.is_file(), "server.json must exist before drift check"
    original = _SERVER_JSON.read_text(encoding="utf-8")
    mutated = original.replace("merge-craft", "merge-craft-drift", 1)
    _SERVER_JSON.write_text(mutated, encoding="utf-8")
    try:
        completed = subprocess.run(
            ["make", "mcp-server-json-check"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode != 0, completed.stdout + completed.stderr
    finally:
        _SERVER_JSON.write_text(original, encoding="utf-8")
