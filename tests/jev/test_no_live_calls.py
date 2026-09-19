"""D14 — the Jev suite never opts into live TypeSafe calls."""

from __future__ import annotations

import ast
from pathlib import Path

from tests.jev.support import JEV_ROOT, TRANSPORT_DIR, load_transport_payload

_FORBIDDEN_MARKERS = frozenset({"live", "integration"})
_SECRET_NEEDLES = ("TYPESAFE_API_KEY", "sk-", "api_key=")


def _iter_test_modules() -> list[Path]:
    return sorted(JEV_ROOT.glob("test_*.py"))


def test_no_jev_test_is_marked_live_or_integration() -> None:
    for path in _iter_test_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                name = _decorator_name(decorator)
                assert name not in _FORBIDDEN_MARKERS, f"{path.name}::{node.name}"


def test_transport_fixtures_contain_no_credentials() -> None:
    for path in sorted(TRANSPORT_DIR.glob("*.json")):
        raw = path.read_text(encoding="utf-8")
        lowered = raw.lower()
        for needle in _SECRET_NEEDLES:
            assert needle.lower() not in lowered, f"{path.name} contains {needle}"
        payload = load_transport_payload(path.name)
        assert "api_key" not in payload
        assert payload.get("http", {}).get("status")


def test_suite_does_not_read_typesafe_api_key_at_import() -> None:
    import tests.jev.support as support

    assert "TYPESAFE_API_KEY" not in support.TEST_API_KEY
    assert support.TEST_API_KEY == "mc-test-jev-key"


def _decorator_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return ""
