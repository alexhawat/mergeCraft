#!/usr/bin/env python3
"""Static contract for W4 live integration (D9 / Makefile delegation)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = REPO_ROOT / "Makefile"
RUNNER = REPO_ROOT / "scripts" / "run_live_integration.py"

if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from mergecraft.integrations.live_providers import PROVIDER_SECRET_ENV  # noqa: E402


def _load_runner_module():
    spec = importlib.util.spec_from_file_location("run_live_integration", RUNNER)
    if spec is None or spec.loader is None:
        msg = "unable to load run_live_integration.py"
        raise RuntimeError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _makefile_target_body(name: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8")
    marker = f"{name}:"
    start = text.find(marker)
    if start < 0:
        msg = f"Makefile missing {name} target"
        raise ValueError(msg)
    rest = text[start + len(marker) :]
    end = len(rest)
    for line in rest.splitlines(keepends=True):
        if line.startswith(("\t", " ")):
            continue
        if line.strip() and not line.startswith("#"):
            end = rest.index(line)
            break
    return text[start : start + len(marker) + end]


def check_live_integration_contract() -> int:
    failures: list[str] = []
    runner = _load_runner_module()
    makefile_integration = _makefile_target_body("test-integration")
    makefile_live = _makefile_target_body("test-integration-live")

    if "integration and not live" not in makefile_integration:
        failures.append("test-integration must use -m 'integration and not live' (PR scope)")
    if "test_otlp_collector_e2e.py" not in makefile_integration:
        failures.append("test-integration must ignore tests/tracing/test_otlp_collector_e2e.py")
    if "run_live_integration.py" not in makefile_live:
        failures.append("test-integration-live must delegate to run_live_integration.py")
    if "exit 1" not in makefile_live and "MERGECRAFT_ALLOW_MISSING_LIVE_CREDS" not in makefile_live:
        failures.append("test-integration-live must fail loudly on missing credentials (D9)")
    if "MERGECRAFT_LIVE_PYTEST_MARKER=live" not in makefile_live:
        failures.append("test-integration-live must export MERGECRAFT_LIVE_PYTEST_MARKER=live")
    if "live_selector" not in makefile_live or '-m "live"' not in makefile_live:
        failures.append("test-integration-live must expose live_selector for CI contract tests")
    if getattr(runner, "LIVE_PYTEST_MARKER", None) != "live":
        failures.append("run_live_integration.LIVE_PYTEST_MARKER must be 'live'")
    if not callable(getattr(runner, "main", None)):
        failures.append("run_live_integration.py must expose main()")
    if "github" not in PROVIDER_SECRET_ENV:
        failures.append("PROVIDER_SECRET_ENV must include github → GITHUB_TOKEN")
    if PROVIDER_SECRET_ENV.get("github") != "GITHUB_TOKEN":
        failures.append("PROVIDER_SECRET_ENV must map github → GITHUB_TOKEN")

    if failures:
        print("live integration contract FAILED:", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print("live integration contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(check_live_integration_contract())
