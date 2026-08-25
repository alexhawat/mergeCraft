"""MCP JSON-RPC helpers — version resolution and error envelopes."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mergecraft.mcp.rpc_types import PARSE_ERROR, json_rpc_parse_error
from mergecraft.utils.version import package_version


@pytest.fixture(autouse=True)
def _clear_package_version_cache() -> None:
    package_version.cache_clear()


if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_package_version_prefers_installed_distribution(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "importlib.metadata.version",
        lambda _name: "9.9.9+wheel",
    )
    assert package_version() == "9.9.9+wheel"


def test_package_version_without_pyproject(monkeypatch: MonkeyPatch) -> None:
    def _missing(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr("importlib.metadata.version", _missing)
    monkeypatch.setattr("mergecraft.__version__", "1.0.0+test", raising=False)

    class _FakePath:
        def resolve(self) -> _FakePath:
            return self

        @property
        def parents(self) -> list[_FakePath]:
            return [self, self, self, self]

        def __truediv__(self, _name: str) -> _FakePath:
            return self

        def is_file(self) -> bool:
            return False

        def read_text(self, *, encoding: str) -> str:
            raise AssertionError("pyproject.toml must not be read on wheel installs")

    monkeypatch.setattr("pathlib.Path", _FakePath)
    assert package_version() == "1.0.0+test"


def test_json_rpc_parse_error_envelope_split() -> None:
    """HTTP omits ``id``; stdio sets ``id`` to ``None`` — both share code/message."""
    http = json_rpc_parse_error(include_id=False)
    stdio = json_rpc_parse_error(include_id=True, req_id=None)
    assert "id" not in http
    assert stdio["id"] is None
    assert (
        http["error"]
        == stdio["error"]
        == {
            "code": PARSE_ERROR.code,
            "message": PARSE_ERROR.message,
        }
    )


def test_public_http_tool_failure_returns_jsonrpc_envelope(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    from dataclasses import replace

    from tests.mcp.public_mcp_support import (
        MCP_PUBLIC_ENDPOINT,
        build_public_http_client,
        rpc_json,
    )

    import mergecraft.mcp.public as public_mod

    original_build = public_mod.build_public_tools

    def _build_with_raising_capabilities(ctx: object) -> list[object]:
        tools = original_build(ctx)
        patched: list[object] = []
        for spec in tools:
            if spec.name != "get_capabilities":
                patched.append(spec)
                continue

            async def _raise(_params: dict[str, object]) -> None:
                raise RuntimeError("tool exploded")

            patched.append(replace(spec, execute=_raise))
        return patched

    monkeypatch.setattr(
        "mergecraft.cli.mcp_serve.build_public_tools",
        _build_with_raising_capabilities,
    )
    client, ctx = build_public_http_client(tmp_path, monkeypatch)
    status, body = rpc_json(
        client,
        MCP_PUBLIC_ENDPOINT,
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/call",
            "params": {"name": "get_capabilities", "arguments": {}},
        },
        auth_token=ctx.mcp_auth_token,
    )
    assert status == 200, body
    error = body.get("error")
    assert isinstance(error, dict), body
    assert error.get("code") == -32603, body
    assert "tool exploded" in str(error.get("message", ""))
