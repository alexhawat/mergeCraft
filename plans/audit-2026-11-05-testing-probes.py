"""Read-only reproduction of T1/T2 in the 2026-11-05 testing audit.

Run with Python's standard library; no pytest, installs, subprocesses or providers.
Mutation source writes are replaced by an in-memory object. Assertions pin the
observed defects; after they are fixed, these audit probes should stop passing.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def mutation_probe() -> None:
    module = load_module("audit_mutation", "scripts/mutate_decision_modules.py")

    class MemoryPath:
        def read_text(self, **kwargs):
            return "def eligible(value):\n    return value == 1\n"

        def write_text(self, value, **kwargs):
            return len(value)

    module.resolve_module_path = lambda *args, **kwargs: MemoryPath()
    module._module_test_dirs = lambda: {"fixture.py": ("tests/fixture",)}
    for exit_code in (2, 3, 4, 5):
        module._run_pytest = lambda *args, exit_code=exit_code, **kwargs: (
            exit_code,
            "pytest did not complete any tests",
        )
        result = module._mutate_module(
            "fixture.py",
            sandbox_root=Path("/unused"),
            python=Path("/unused"),
            max_mutants=1,
            seed=1,
            verbose=0,
        )
        assert (result.killed, result.errors, result.survived) == (1, 0, 0)
        print(
            f"T1: pytest exit {exit_code} incorrectly counted as "
            f"killed={result.killed}, errors={result.errors}"
        )


def action_e2e_probe() -> None:
    module = load_module("audit_e2e", "docker/e2e/assert_e2e_outputs.py")

    class FakePath:
        def is_file(self):
            return True

    args = argparse.Namespace(
        github_output=FakePath(),
        check_runs_dir=FakePath(),
        expect_outcome="passed",
        require_check_runs=True,
    )
    original_parse_args = argparse.ArgumentParser.parse_args
    module.argparse.ArgumentParser.parse_args = lambda self: args
    module._parse_github_output = lambda path: {
        "result": "E2E review complete: no findings."
    }
    module._load_check_runs = lambda path: [
        {
            "body": {
                "name": "mergecraft",
                "head_sha": "WRONG-COMMIT",
                "status": "completed",
                "conclusion": "failure",
                "output": {"title": "Failure", "summary": "No review accepted"},
            }
        }
    ]
    try:
        exit_code = module.main()
    finally:
        argparse.ArgumentParser.parse_args = original_parse_args
    assert exit_code == 0
    print("T2: wrong commit and failure conclusion incorrectly accepted (exit 0)")


if __name__ == "__main__":
    mutation_probe()
    action_e2e_probe()
