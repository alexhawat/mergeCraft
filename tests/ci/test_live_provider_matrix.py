"""W4 — nightly live-provider matrix YAML / Makefile contracts (R-F3).

Live HTTP/CLI requests live in ``tests/integration/``. This module pins
workflow + Make + runner contracts so a missing ``live`` marker or a silent
``exit 0`` skip cannot hide as an integration skip. Marker selection is
``run_live_integration.LIVE_PYTEST_MARKER`` — not a Makefile ``live_selector``
decoy.
"""

from __future__ import annotations

import importlib.util
import re
from typing import Any

from mergecraft.integrations.live_providers import (
    DEFAULT_CREDENTIAL_SLUGS,
    PROVIDER_SECRET_ENV,
    missing_live_credentials,
)
from tests.ci.workflow_support import REPO_ROOT, job, load_workflow, read_text

# This guard's own name contains the forbidden substring; skip it by identity.
_AUDIT_GUARD_NAME = "test_no_skips_when_no_secret_test_exists"
_TEST_DEF = re.compile(r"^def (test_\w+)\s*\(", re.MULTILINE)


def test_live_marker_registered_in_pytest_ini() -> None:
    """``live`` is a first-class pytest marker (already registered; must stay)."""
    text = read_text("pyproject.toml")
    section = text.split("[tool.pytest.ini_options]", 1)[1]
    assert re.search(r"^markers\s*=", section, re.MULTILINE)
    assert re.search(r'^\s*"live:', section, re.MULTILINE), (
        "live marker missing from [tool.pytest.ini_options] markers"
    )


def _load_script(name: str) -> Any:
    path = REPO_ROOT / "scripts" / f"{name}.py"
    assert path.is_file(), f"scripts/{name}.py missing"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _live_makefile_body() -> str:
    makefile = read_text("Makefile")
    match = re.search(
        r"^test-integration-live:.*?(?=\n(?:[a-zA-Z0-9_.-]+:|$))",
        makefile,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "test-integration-live target missing from Makefile"
    return match.group(0)


def test_test_integration_live_selects_live_marker() -> None:
    """Live pytest selection is ``LIVE_PYTEST_MARKER`` on the runner, not Make decoy."""
    runner = _load_script("run_live_integration")
    assert runner.LIVE_PYTEST_MARKER == "live"
    body = _live_makefile_body()
    assert "run_live_integration.py" in body, (
        f"test-integration-live must delegate to run_live_integration.py:\n{body}"
    )
    assert "MERGECRAFT_LIVE_PYTEST_MARKER=live" in body
    assert '-m "integration"' not in body or "not live" in body


def test_missing_credential_fails_on_schedule() -> None:
    """D9 — a rotation outage must not ``exit 0`` with skipped: no live credential."""
    body = _live_makefile_body()
    assert "exit 0" not in body, (
        "test-integration-live still exits 0 when credentials are absent (R-F3 / D9)"
    )
    assert "MERGECRAFT_ALLOW_MISSING_LIVE_CREDS" in body or "exit 1" in body or "exit $$" in body
    assert "run_live_integration.py" in body


def test_live_pytest_marker_constant() -> None:
    runner = _load_script("run_live_integration")
    assert runner.LIVE_PYTEST_MARKER == "live"
    assert callable(runner.main)


def test_check_live_integration_contract_passes() -> None:
    module = _load_script("check_live_integration_contract")
    check = module.check_live_integration_contract
    assert callable(check)
    assert check() == 0


def test_default_credential_slugs_and_github_required_set() -> None:
    """Default sweep plus github matrix leg. Deleting github must fail."""
    assert DEFAULT_CREDENTIAL_SLUGS == ("anthropic", "openai", "gemini", "nous")
    for slug in DEFAULT_CREDENTIAL_SLUGS:
        assert slug in PROVIDER_SECRET_ENV
    assert PROVIDER_SECRET_ENV["github"] == "GITHUB_TOKEN"


def test_missing_live_credentials_default_sweep(monkeypatch: Any) -> None:
    for slug in DEFAULT_CREDENTIAL_SLUGS:
        monkeypatch.delenv(PROVIDER_SECRET_ENV[slug], raising=False)
    missing = missing_live_credentials()
    assert missing == [PROVIDER_SECRET_ENV[slug] for slug in DEFAULT_CREDENTIAL_SLUGS]


def test_missing_live_credentials_github_leg(monkeypatch: Any) -> None:
    """Guard-deletion: github must resolve to ``GITHUB_TOKEN``."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert missing_live_credentials("github") == ["GITHUB_TOKEN"]


def test_missing_live_credentials_unknown_provider() -> None:
    assert missing_live_credentials("not-a-provider") == ["unknown provider 'not-a-provider'"]


def test_run_live_integration_fails_loud_without_creds(monkeypatch: Any) -> None:
    runner = _load_script("run_live_integration")
    monkeypatch.delenv("MERGECRAFT_ALLOW_MISSING_LIVE_CREDS", raising=False)
    monkeypatch.setenv("MERGECRAFT_LIVE_PROVIDER", "github")
    monkeypatch.setenv("MERGECRAFT_LIVE_PYTEST_MARKER", runner.LIVE_PYTEST_MARKER)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert runner.main([]) == 1


def test_suite_is_inert_on_pull_request() -> None:
    """Convention 6 — the live job must not run on ``pull_request``."""
    live = job(load_workflow("integration.yml"), "integration-live")
    condition = str(live.get("if", ""))
    assert "pull_request" not in condition, (
        f"integration-live must stay off pull_request: {condition}"
    )
    assert "schedule" in condition
    assert "workflow_dispatch" in condition


def test_live_matrix_fail_fast_false() -> None:
    """D10 — one provider outage must not mask the others."""
    live = job(load_workflow("integration.yml"), "integration-live")
    strategy = live.get("strategy") or {}
    assert strategy.get("fail-fast") is False, f"fail-fast must be false: {strategy}"


def test_each_matrix_leg_gets_only_its_own_provider_secret() -> None:
    """Each matrix leg receives only that provider's secret (D10)."""
    live = job(load_workflow("integration.yml"), "integration-live")
    strategy = live.get("strategy") or {}
    matrix = strategy.get("matrix") or {}
    providers = matrix.get("provider") or matrix.get("include")
    assert providers, f"integration-live has no provider matrix: {strategy}"

    names = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "NOUS_API_KEY"}
    steps = live.get("steps") or []
    env_blobs: list[dict[str, object]] = []
    for step in steps:
        env = step.get("env") if isinstance(step, dict) else None
        if isinstance(env, dict):
            env_blobs.append(env)
    assert env_blobs, "live job has no step env to pin per-leg secrets"
    for env in env_blobs:
        present = names.intersection(str(key) for key in env)
        # Matrix interpolation may pass a single ${{ secrets[matrix.secret] }}.
        joined = " ".join(f"{key}={value}" for key, value in env.items())
        if "matrix." in joined:
            continue
        assert len(present) <= 1, f"leg env exports multiple provider secrets: {present}"


def test_no_skips_when_no_secret_test_exists() -> None:
    """Audit-escape: the suite must not grow a permissive skip-when-no-secret test."""
    root = REPO_ROOT / "tests"
    offenders: list[str] = []
    for path in root.rglob("test_*.py"):
        text = path.read_text(encoding="utf-8")
        for match in _TEST_DEF.finditer(text):
            name = match.group(1)
            if name == _AUDIT_GUARD_NAME:
                continue
            if "skips_when_no_secret" in name or "skip_when_no_secret" in name:
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}::{name}")
    assert not offenders, f"permissive skip-when-no-secret tests: {offenders}"
