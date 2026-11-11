"""THREAT-MODEL.md names a real enforcing function and a real test per control (W2.3-5).

The controls table in ``docs/THREAT-MODEL.md`` lists ``module:function`` references
and test paths. A reference that does not resolve, a function that is never called
from product code, or a test that does not exist is a claim the code does not back.
Functions the document says are *not* controls must stay uncalled, so the document
cannot drift back to presenting them as gates.
"""

from __future__ import annotations

import importlib
import re

from tests.ci.workflow_support import REPO_ROOT

_DOC = REPO_ROOT / "docs" / "THREAT-MODEL.md"
_FUNC = re.compile(r"`(mergecraft(?:\.[a-z_]+)+):([A-Za-z_]+)`")
_TEST = re.compile(r"`(tests/[\w/]+\.py)(?:::(\w+))?`")
_NOT_CONTROLS = (
    "allow_egress",
    "dependency_vulnerability_gate",
    "container_image_vulnerability_gate",
)


def _controls_table() -> str:
    text = _DOC.read_text(encoding="utf-8")
    start = text.index("## What is enforced, and where")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def _product_source() -> dict[str, str]:
    return {
        str(path.relative_to(REPO_ROOT)): path.read_text(encoding="utf-8")
        for path in (REPO_ROOT / "src").rglob("*.py")
    }


def test_enforcing_functions_resolve() -> None:
    refs = _FUNC.findall(_controls_table())
    assert refs, "controls table names no enforcing functions"
    for module_name, func in refs:
        module = importlib.import_module(module_name)
        assert callable(getattr(module, func, None)), f"{module_name}:{func} does not exist"


def test_enforcing_functions_have_a_product_caller() -> None:
    source = _product_source()
    for module_name, func in set(_FUNC.findall(_controls_table())):
        defining = f"src/{module_name.replace('.', '/')}.py"
        callers = [
            path
            for path, text in source.items()
            if path != defining and re.search(rf"\b{re.escape(func)}\b", text)
        ]
        within = len(re.findall(rf"\b{re.escape(func)}\(", source.get(defining, ""))) > 1
        assert callers or within, f"{module_name}:{func} is named as a control but never called"


def test_named_tests_exist() -> None:
    refs = _TEST.findall(_controls_table())
    assert refs, "controls table names no tests"
    for path, name in refs:
        test_file = REPO_ROOT / path
        assert test_file.is_file(), f"{path} does not exist"
        if name:
            assert f"def {name}(" in test_file.read_text(encoding="utf-8"), f"{path}::{name}"


def test_documented_non_controls_stay_uncalled_by_product_code() -> None:
    """If one of these gains a caller, the document must be updated to say so."""
    source = _product_source()
    doc = _DOC.read_text(encoding="utf-8")
    for func in _NOT_CONTROLS:
        assert func in doc, f"THREAT-MODEL.md no longer mentions {func}"
        callers = [
            path
            for path, text in source.items()
            if re.search(rf"\b{func}\(", text) and "def " + func not in text
        ]
        assert not callers, f"{func} is now called from {callers}; update THREAT-MODEL.md"
