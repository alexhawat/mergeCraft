#!/usr/bin/env python3
"""Verify OTLP e2e harness test slices match the tracing test module."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS = REPO_ROOT / "scripts" / "run_otlp_collector_e2e.py"
TEST_MODULE = REPO_ROOT / "tests" / "tracing" / "test_otlp_collector_e2e.py"


def _test_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


def _tuple_names(path: Path, const: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == const
            and isinstance(node.value, ast.Tuple)
        ):
            names: set[str] = set()
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    names.add(elt.value)
            return names
    msg = f"{path.name} missing {const} tuple"
    raise ValueError(msg)


def _integration_test_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Attribute)
                and dec.attr == "integration"
                and isinstance(dec.value, ast.Attribute)
                and dec.value.attr == "mark"
                and isinstance(dec.value.value, ast.Name)
                and dec.value.value.id == "pytest"
            ):
                names.add(node.name)
                break
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr == "mark"
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "pytest"
                and dec.args
            ):
                first = dec.args[0]
                if isinstance(first, ast.Attribute) and first.attr == "integration":
                    names.add(node.name)
                    break
    return names


def check_otlp_e2e_slices() -> int:
    module_tests = _test_names(TEST_MODULE)
    integration_tests = _integration_test_names(TEST_MODULE)
    pre = _tuple_names(HARNESS, "OTLP_PRE_SEED_TESTS")
    post = _tuple_names(HARNESS, "OTLP_POST_SEED_TESTS")
    harness_tests = pre | post
    failures: list[str] = []
    for name in harness_tests:
        if name not in module_tests:
            failures.append(f"{name} missing from {TEST_MODULE.name}")
    for name in integration_tests:
        if name not in harness_tests:
            failures.append(
                f"{name} is @pytest.mark.integration but not in OTLP_PRE/POST_SEED_TESTS"
            )
    if failures:
        print("OTLP e2e slice contract FAILED:", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"OTLP e2e slice contract OK ({len(pre)} pre, {len(post)} post)")
    return 0


if __name__ == "__main__":
    raise SystemExit(check_otlp_e2e_slices())
