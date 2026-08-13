"""W4 — nightly live-provider matrix YAML / Makefile contracts (R-F3).

Live HTTP/CLI requests live in ``tests/integration/``. This module only
parses workflow + Make + pytest config so a missing ``live`` selector or a
silent ``exit 0`` skip cannot hide as an integration skip.
"""

from __future__ import annotations

import re

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


def test_test_integration_live_selects_live_marker() -> None:
    """``make test-integration-live`` must select ``-m live``, not ``-m integration``."""
    makefile = read_text("Makefile")
    match = re.search(
        r"^test-integration-live:.*?(?=\n(?:[a-zA-Z0-9_.-]+:|$))",
        makefile,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "test-integration-live target missing from Makefile"
    body = match.group(0)
    assert re.search(r'-m\s+"live"|-m\s+live|-m\s+"[^"]*\blive\b', body), (
        f"test-integration-live does not select -m live:\n{body}"
    )
    assert '-m "integration"' not in body or "live" in body


def test_missing_credential_fails_on_schedule() -> None:
    """D9 — a rotation outage must not ``exit 0`` with skipped: no live credential."""
    makefile = read_text("Makefile")
    match = re.search(
        r"^test-integration-live:.*?(?=\n(?:[a-zA-Z0-9_.-]+:|$))",
        makefile,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None
    body = match.group(0)
    assert "exit 0" not in body, (
        "test-integration-live still exits 0 when credentials are absent (R-F3 / D9)"
    )
    assert "MERGECRAFT_ALLOW_MISSING_LIVE_CREDS" in body or "exit 1" in body or "exit $$" in body


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
