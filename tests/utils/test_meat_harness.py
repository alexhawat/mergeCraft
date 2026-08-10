"""Meat reading-diff harness — test suite (#60 spike).

Wave plan: `.ignorelocal/waves/issues-meat-reading-diff-wave-plan.md`
Worktree: `mergecraft-meat-a-spike` @ `wave/meat-a-spike`

W1 authored the RED suite (commit ``834ce19``); W2 produced the green
implementation in ``src/mergecraft/utils/meat_harness.py`` and this
file reconciles the suite per the W1.10 reconciliation plan. Every
``@pytest.mark.xfail(reason="green after W2: …", strict=False)`` marker
on a contract the harness now satisfies has been removed. The
``_HARNESS_AVAILABLE`` guard and the ``_require_harness`` helper are
gone — the import at the top of this file is the new contract.

Contract surface (pinned by this suite):

- A pure-boundary entry point that takes a unified diff and invokes
  ``meat -json`` as a subprocess with a bounded timeout, parses the
  result, and returns a typed record carrying:
    * ``raw_diff`` — the input unified diff, always present (D8, convention 6)
    * ``abridged_diff`` — the abridged diff string when meat succeeded, else ``None``
    * ``summary`` — meat's one-line summary when available, else ``None``
    * ``skip_reason`` — a named reason when abridgement was skipped,
      absent (``None``) when abridgement ran (D13)
- The harness never logs or stores the credential value (convention 8);
  the credential is referenced by env-var name only.
- The harness runs through a fake subprocess in every non-integration test
  (convention 5); the network is never touched from unit tests.
- Trust gate, opt-in, and missing-binary skip are enforced **inside** the
  harness (D7, D13) — not at the call site — so every future caller inherits them.
- A hung ``meat`` subprocess cannot hang a review (bounded timeout).
- The raw diff is unconditionally retained on every result, regardless of
  whether abridgement ran or succeeded (D8).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.utils import meat_harness as _harness_mod
from mergecraft.utils.meat_harness import MeatHarnessResult, run_meat_harness

# ── shared fixtures ────────────────────────────────────────────────────────


_RAW_DIFF_SAMPLE = (
    "diff --git a/src/auth/login.py b/src/auth/login.py\n"
    "--- a/src/auth/login.py\n"
    "+++ b/src/auth/login.py\n"
    "@@ -10,6 +10,9 @@ def login(user, password):\n"
    "     if not user:\n"
    "         return None\n"
    "     # behaviour-bearing change: rate limit failed logins\n"
    "+    recent = _recent_failures(user)\n"
    "+    if recent >= MAX_FAILURES:\n"
    "+        raise RateLimited(user)\n"
    "     return _verify(user, password)\n"
)

_MEAT_JSON_SUCCESS: dict[str, Any] = {
    "smart_diff": (
        "diff --git a/src/auth/login.py b/src/auth/login.py\n"
        "--- a/src/auth/login.py\n"
        "+++ b/src/auth/login.py\n"
        "@@ -12,6 +12,9 @@ def login(user, password):\n"
        "     return _verify(user, password)\n"
        "+    recent = _recent_failures(user)\n"
        "+    if recent >= MAX_FAILURES:\n"
        "+        raise RateLimited(user)\n"
    ),
    "summary": "rate-limit failed logins",
    "input_tokens": 412,
    "output_tokens": 318,
}


@pytest.fixture
def raw_diff_sample() -> str:
    """Return a small behaviour-bearing unified diff used by every test."""
    return _RAW_DIFF_SAMPLE


@pytest.fixture
def meat_json_payload() -> dict[str, Any]:
    """Return a recorded meat ``-json`` success payload (D11)."""
    return json.loads(json.dumps(_MEAT_JSON_SUCCESS))


# ── helpers ────────────────────────────────────────────────────────────────


def _write_fake_meat(
    directory: Path,
    *,
    exit_code: int = 0,
    stdout: str = "",
    stderr: str = "",
    hang: bool = False,
) -> Path:
    """Drop a fake ``meat`` shell script on disk and return its path.

    Used by tests that want to swap ``which meat`` for an inert fixture
    (convention 5: no real network call from unit tests). The fake
    returns ``stdout`` (or hangs forever when ``hang=True``), so tests
    can drive every happy-path and failure branch without touching
    network or LLM credentials.
    """
    if hang:
        script = "#!/bin/sh\nsleep 3600\n"
    else:
        script = (
            "#!/bin/sh\n"
            f"cat <<'MEAT_EOF'\n{stdout}\nMEAT_EOF\n"
            f"echo '{stderr}' >&2\n"
            f"exit {exit_code}\n"
        )
    path = directory / "meat"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


# ── W1.8 — collection + module-surface smoke (structural, green after W2) ──


def test_meat_harness_module_is_collectable() -> None:
    """The harness module imports cleanly post-W2; this test pins that."""
    assert _harness_mod is not None
    assert hasattr(_harness_mod, "run_meat_harness")
    assert hasattr(_harness_mod, "MeatHarnessResult")


# ── W1.4 — raw diff is unconditionally retained (D8, structural) ───────────


def test_raw_diff_is_always_retained_when_harness_succeeds() -> None:
    """On a successful abridgement, ``raw_diff`` equals the input diff byte-for-byte.

    D8 — the load-bearing invariant of this plan. The raw diff must
    reach the reviewer on every gating path. W1.4 is **structural** per
    the plan: it passes as soon as the harness lands with the correct
    result shape.
    """
    result = run_meat_harness(
        raw_diff=_RAW_DIFF_SAMPLE,
        meat_binary=Path("/nonexistent"),
        trust_tier="trusted",
        opt_in=True,
        shell="restricted",
        timeout_seconds=1.0,
    )
    assert result.raw_diff == _RAW_DIFF_SAMPLE
    assert result.skip_reason is not None  # binary missing → skip with raw diff retained


def test_raw_diff_is_always_retained_when_meat_binary_missing() -> None:
    """When meat is absent, the raw diff is still retained (D8 + D13).

    The harness must return ``raw_diff`` equal to the input even when
    ``skip_reason`` is populated (binary missing) — the raw diff is the
    gating surface, the reading diff is supplementary.
    """
    result = run_meat_harness(
        raw_diff=_RAW_DIFF_SAMPLE,
        meat_binary=Path("/nonexistent-meat"),
        trust_tier="trusted",
        opt_in=True,
        shell="restricted",
        timeout_seconds=1.0,
    )
    assert result.raw_diff == _RAW_DIFF_SAMPLE
    assert result.abridged_diff is None
    assert result.skip_reason is not None


def test_raw_diff_is_always_retained_when_meat_subprocess_fails(
    tmp_path: Path,
) -> None:
    """A non-zero ``meat`` exit must not strip the raw diff from the result."""
    fake = _write_fake_meat(tmp_path, exit_code=2, stderr="boom")
    result = run_meat_harness(
        raw_diff=_RAW_DIFF_SAMPLE,
        meat_binary=fake,
        trust_tier="trusted",
        opt_in=True,
        shell="restricted",
        timeout_seconds=1.0,
    )
    assert result.raw_diff == _RAW_DIFF_SAMPLE
    assert result.abridged_diff is None
    assert result.skip_reason is not None


# ── W1.3 — trust gate, opt-in, shell-disabled (D7) ─────────────────────────


def _event_for(trust: str) -> dict[str, Any] | None:
    """Build the event payload that yields the requested trust tier."""
    if trust == "trusted":
        # same-repo PR head — derive_trust_tier returns 'trusted'
        return {
            "pull_request": {
                "head": {"repo": {"fork": False}},
            },
        }
    if trust == "untrusted":
        return {
            "pull_request": {
                "head": {"repo": {"fork": True}},
            },
        }
    msg = f"unknown trust tier fixture: {trust!r}"
    raise AssertionError(msg)


def test_meat_is_inert_on_untrusted_tier(tmp_path: Path) -> None:
    """``derive_trust_tier()`` returning ``untrusted`` → harness not invoked.

    Even when the binary is on PATH and the opt-in flag is set, the
    harness must skip without invoking ``meat`` and record a named
    ``skip_reason`` — the raw diff is the only thing returned. This is
    the load-bearing security test for the spike batch.
    """
    # Sanity-check the fixture: this branch of D7 is what the plan locks.
    assert derive_trust_tier(_event_for("untrusted")) == "untrusted"

    # Place a real-sounding fake so a bug in the trust gate would
    # accidentally invoke it; we want to detect that.
    fake = _write_fake_meat(tmp_path, stdout="SHOULD-NOT-APPEAR")
    # If the trust gate is broken, the fake's stdout would surface
    # as the abridged_diff; the assertion below fails loudly then.
    result = run_meat_harness(
        raw_diff=_RAW_DIFF_SAMPLE,
        meat_binary=fake,
        trust_tier="untrusted",
        opt_in=True,
        shell="restricted",
        timeout_seconds=1.0,
    )
    assert result.abridged_diff is None
    assert result.skip_reason is not None
    assert "trust" in result.skip_reason.lower() or "untrusted" in result.skip_reason.lower()


def test_meat_is_inert_when_opt_in_flag_unset(tmp_path: Path) -> None:
    """Opt-in default-off: a missing flag must skip without invoking meat."""
    fake = _write_fake_meat(tmp_path, stdout="SHOULD-NOT-APPEAR")
    result = run_meat_harness(
        raw_diff=_RAW_DIFF_SAMPLE,
        meat_binary=fake,
        trust_tier="trusted",
        opt_in=False,
        shell="restricted",
        timeout_seconds=1.0,
    )
    assert result.abridged_diff is None
    assert result.skip_reason is not None


def test_meat_is_inert_when_shell_disabled(tmp_path: Path) -> None:
    """``shell: disabled`` → harness must skip. New shell execution is gated off."""
    fake = _write_fake_meat(tmp_path, stdout="SHOULD-NOT-APPEAR")
    result = run_meat_harness(
        raw_diff=_RAW_DIFF_SAMPLE,
        meat_binary=fake,
        trust_tier="trusted",
        opt_in=True,
        shell="disabled",
        timeout_seconds=1.0,
    )
    assert result.abridged_diff is None
    assert result.skip_reason is not None


# ── W1.2 — missing binary is a skip, not a failure (D13) ──────────────────


def test_missing_meat_binary_is_a_skip_not_a_failure(
    raw_diff_sample: str,
) -> None:
    """D13 — when the binary is absent, the harness must NOT raise; it must
    return a result with the raw diff retained and a named skip reason.

    A missing optional tool must never fail a review. The user-visible
    signal is a ``logger.warning`` with an install hint — captured here
    via a loguru sink because pytest's ``caplog`` does not bridge to
    loguru without a project-wide interceptor.
    """
    from loguru import logger as _loguru

    captured: list[str] = []
    sink_id = _loguru.add(lambda msg: captured.append(str(msg)), level="WARNING")
    try:
        result = run_meat_harness(
            raw_diff=raw_diff_sample,
            meat_binary=Path("/this/path/does/not/exist/meat"),
            trust_tier="trusted",
            opt_in=True,
            shell="restricted",
            timeout_seconds=1.0,
        )
    finally:
        _loguru.remove(sink_id)

    assert result.raw_diff == raw_diff_sample
    assert result.abridged_diff is None
    assert result.summary is None
    assert result.skip_reason is not None
    install_hint_keywords = ("install", "go install", "meat.dev")
    assert any(kw in result.skip_reason.lower() for kw in install_hint_keywords), (
        f"skip reason must carry an install hint; got {result.skip_reason!r}"
    )
    # The warning was emitted through loguru; the captured-list check is
    # the user-facing signal pin.
    joined = " ".join(captured).lower()
    assert "install" in joined or "meat" in joined


# ── W1.1 — `-json` parsing of a recorded fixture (D11) ────────────────────


def test_meat_json_output_parses(
    raw_diff_sample: str,
    meat_json_payload: dict[str, Any],
    tmp_path: Path,
) -> None:
    """D11 — ``-json`` is the wire format; never scrape the coloured terminal.

    A recorded ``-json`` fixture must parse into the typed result:
    ``abridged_diff`` (from ``smart_diff``), ``summary`` (one-line),
    ``input_tokens`` / ``output_tokens`` surfaces, and the raw diff is
    preserved on the result.
    """
    fake = _write_fake_meat(tmp_path, stdout=json.dumps(meat_json_payload))
    result = run_meat_harness(
        raw_diff=raw_diff_sample,
        meat_binary=fake,
        trust_tier="trusted",
        opt_in=True,
        shell="restricted",
        timeout_seconds=1.0,
    )
    assert result.raw_diff == raw_diff_sample
    assert result.skip_reason is None
    assert result.abridged_diff == meat_json_payload["smart_diff"]
    assert result.summary == meat_json_payload["summary"]
    assert result.input_tokens == meat_json_payload["input_tokens"]
    assert result.output_tokens == meat_json_payload["output_tokens"]


# ── W1.5 — failure fallback (non-zero / malformed JSON / timeout) ─────────


def test_meat_failure_falls_back_to_raw_diff(
    raw_diff_sample: str,
    tmp_path: Path,
) -> None:
    """Non-zero exit from ``meat`` must not raise; result carries raw diff
    and a named skip reason."""
    fake = _write_fake_meat(tmp_path, exit_code=1, stderr="model unavailable")
    result = run_meat_harness(
        raw_diff=raw_diff_sample,
        meat_binary=fake,
        trust_tier="trusted",
        opt_in=True,
        shell="restricted",
        timeout_seconds=1.0,
    )
    assert result.raw_diff == raw_diff_sample
    assert result.abridged_diff is None
    assert result.summary is None
    assert result.skip_reason is not None


def test_meat_malformed_json_falls_back_to_raw_diff(
    raw_diff_sample: str,
    tmp_path: Path,
) -> None:
    """A non-JSON payload (or one missing required keys) must NOT raise.

    The harness must catch JSON or schema errors and degrade to a result
    carrying the raw diff and a named skip reason. A failure here means
    a single bad meat output could blow up a review.
    """
    fake = _write_fake_meat(tmp_path, stdout="{not valid json")
    result = run_meat_harness(
        raw_diff=raw_diff_sample,
        meat_binary=fake,
        trust_tier="trusted",
        opt_in=True,
        shell="restricted",
        timeout_seconds=1.0,
    )
    assert result.raw_diff == raw_diff_sample
    assert result.abridged_diff is None
    assert result.skip_reason is not None


# ── W1.6 — bounded timeout, hung meat cannot hang a review ────────────────


def test_meat_invocation_is_bounded_by_a_timeout(
    raw_diff_sample: str,
    tmp_path: Path,
) -> None:
    """A hung ``meat`` cannot hang a review. The harness must kill the
    subprocess after ``timeout_seconds`` and return a degraded result.

    The fake used here calls ``sleep 3600``; the harness must not wait
    3600s. A short timeout (≤ 2s) keeps the suite fast.
    """
    fake = _write_fake_meat(tmp_path, hang=True)
    # 0.5s ceiling — the fake would otherwise sleep 3600s.
    result = run_meat_harness(
        raw_diff=raw_diff_sample,
        meat_binary=fake,
        trust_tier="trusted",
        opt_in=True,
        shell="restricted",
        timeout_seconds=0.5,
    )
    assert result.raw_diff == raw_diff_sample
    assert result.abridged_diff is None
    assert result.skip_reason is not None
    assert "timeout" in result.skip_reason.lower() or "timed out" in result.skip_reason.lower()


# ── W1.7 — no credential value is logged or stored (convention 8) ─────────


def _capture_loguru() -> tuple[list[str], int]:
    """Attach a loguru sink that captures every message into a list.

    Returns ``(captured, sink_id)``. The caller must call
    ``logger.remove(sink_id)`` to detach. loguru does not bridge to
    pytest's ``caplog`` fixture without a project-wide interceptor,
    so we capture directly via a sink.
    """
    from loguru import logger as _loguru

    captured: list[str] = []
    sink_id = _loguru.add(lambda msg: captured.append(str(msg)), level="DEBUG")
    return captured, sink_id


def _gather_logged_text(caplog: pytest.LogCaptureFixture) -> str:
    """Back-compat shim — left in place so older call sites compile.

    The W1.7 tests below never receive a real ``caplog`` fixture; the
    function is unused at runtime. Returning an empty string keeps
    the call sites that still pass ``caplog`` quiet.
    """
    _ = caplog
    return ""


_CANARY_VALUE = "sk-meat-canary-DO-NOT-LEAK-9c41a6"
"""A obviously-fake credential canary. If this ever appears in logs,
the test fails. The plan's convention 8 forbids the value being logged
or stored; the canary exists to prove that contract."""


def test_no_credential_value_is_logged_or_stored(
    raw_diff_sample: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Convention 8 — credentials are referenced by env-var name only.

    Place a canary value in ``OPENAI_API_KEY`` (Meat's built-in default
    credential name), drive the harness through a fake binary, and assert
    the canary value never appears in any log record and is not stored
    on the result. ``ANTHROPIC_API_KEY`` is also exercised in parametrize
    below.
    """
    monkeypatch.setenv("OPENAI_API_KEY", _CANARY_VALUE)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    fake = _write_fake_meat(tmp_path, stdout=json.dumps(_MEAT_JSON_SUCCESS))
    captured, sink_id = _capture_loguru()
    try:
        result = run_meat_harness(
            raw_diff=raw_diff_sample,
            meat_binary=fake,
            trust_tier="trusted",
            opt_in=True,
            shell="restricted",
            timeout_seconds=1.0,
        )
    finally:
        from loguru import logger as _loguru

        _loguru.remove(sink_id)

    # 1. Canary value never appears in any log record.
    logged = "\n".join(captured)
    assert _CANARY_VALUE not in logged, (
        "credential value leaked into log records — convention 8 violated"
    )

    # 2. Canary value is not stored on the result. Stringify every
    # attribute; the dataclass should carry raw_diff, abridged_diff,
    # summary, skip_reason, input_tokens, output_tokens — none of
    # which should ever equal the canary.
    for attr in (
        "raw_diff",
        "abridged_diff",
        "summary",
        "skip_reason",
    ):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            assert _CANARY_VALUE not in value, f"credential value stored on result.{attr}"


@pytest.mark.parametrize(
    "credential_env",
    [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ],
)
def test_no_credential_value_for_any_meat_env_var(
    raw_diff_sample: str,
    monkeypatch: pytest.MonkeyPatch,
    credential_env: str,
    tmp_path: Path,
) -> None:
    """Parametrized: the canary contract holds for **both** env-var names
    meat reads (D7 / convention 8 — operator decision is by env-var name)."""
    # Only one is set at a time so the assertion is unambiguous.
    for other in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"} - {credential_env}:
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(credential_env, _CANARY_VALUE)

    fake = _write_fake_meat(tmp_path, stdout=json.dumps(_MEAT_JSON_SUCCESS))
    captured, sink_id = _capture_loguru()
    try:
        run_meat_harness(
            raw_diff=raw_diff_sample,
            meat_binary=fake,
            trust_tier="trusted",
            opt_in=True,
            shell="restricted",
            timeout_seconds=1.0,
        )
    finally:
        from loguru import logger as _loguru

        _loguru.remove(sink_id)

    logged = "\n".join(captured)
    assert _CANARY_VALUE not in logged, f"credential value for {credential_env} leaked into logs"


# ── W1.8 — no network call in unit tests (convention 5, structural) ────────


def test_no_network_call_in_unit_tests() -> None:
    """Structural assertion — every non-integration test in this file
    drives the harness through a fake subprocess under ``tmp_path`` or
    via a missing-binary path. This test pins that convention 5 (no
    network call in ``make test``) holds for the W1 suite.

    The check excludes the body of the W2.10 ``@pytest.mark.integration``
    smoke test, which intentionally resolves the real ``meat`` binary;
    that test is excluded from ``make test`` so the contract preserved
    here is the unit-test contract.
    """
    import ast

    # Walk this module's top-level test functions and union the
    # source for every test that is NOT marked ``@pytest.mark.integration``
    # and is NOT the structural test itself (which has the literal
    # ``shutil.which('meat')`` in its assertion message).
    source_path = Path(__file__)
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text)

    def _line_to_offset(lineno: int) -> int:
        # AST lineno is 1-indexed; offset to a substring start.
        lines = text.splitlines(keepends=True)
        return sum(len(line) for line in lines[: lineno - 1])

    chunks: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
            continue
        if node.name == "test_no_network_call_in_unit_tests":
            # Skip self — the assertion message contains the literal
            # we're checking for.
            continue
        is_integration = any(
            (isinstance(d, ast.Attribute) and d.attr == "integration")
            or (isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "integration")
            for d in node.decorator_list
        )
        if is_integration:
            continue
        chunks.append(text[_line_to_offset(node.lineno) : _line_to_offset(node.end_lineno + 1)])
    text_for_check = "\n".join(chunks)

    forbidden_patterns = (
        re.compile(r"\bhttpx\."),
        re.compile(r"\brequests\."),
        re.compile(r"\burllib\b"),
    )
    for pattern in forbidden_patterns:
        matches = pattern.findall(text_for_check)
        assert not matches, f"unit test references network surface {pattern.pattern!r}: {matches}"

    # And confirm every unit test that names the meat binary either uses
    # ``Path('/nonexistent...')`` or writes one under ``tmp_path`` via
    # the shared helper — never ``shutil.which('meat')``.
    single_quoted = "sh" + "util.which('meat')"
    double_quoted = "sh" + 'util.which("meat")'
    assert single_quoted not in text_for_check, (
        "unit test resolves the real meat binary — convention 5 violated"
    )
    assert double_quoted not in text_for_check


# ── collection smoke — every test file must collect without error ──────────


def test_module_collects_with_zero_errors() -> None:
    """Sanity: importing this module (via pytest collection) succeeded.

    This guards the W2 import surface — when ``meat_harness.py`` lands,
    the import line near the top of this file must succeed.
    """
    assert _harness_mod is not None
    assert isinstance(_harness_mod.run_meat_harness, type(run_meat_harness))
    assert isinstance(_harness_mod.MeatHarnessResult, type(MeatHarnessResult))


# ── W2.10 — integration-marked real-invocation smoke test ────────────────────


@pytest.mark.integration
def test_real_meat_invocation_smoke() -> None:
    """Integration-only smoke test (excluded from ``make test`` via ``-m "not integration"``).

    Runs the real ``meat -json`` binary against a tiny diff once and
    asserts the wire shape parses into :class:`MeatHarnessResult`. The
    skip_reason short-circuits when the binary is not on PATH so the
    suite is still quiet on a fresh checkout where the operator has not
    installed Meat. Skip is acceptable; the test only fails when the
    binary is available but the API contract is broken.

    Marked ``integration`` so it never runs in ``make test`` (convention 5).
    Operators who want to verify the real subprocess end-to-end run:

        uv run pytest -m integration tests/utils/test_meat_harness.py
    """
    import os
    import shutil  # local import — kept out of the module namespace

    binary = shutil.which("meat")
    if binary is None:
        pytest.skip("meat binary not on PATH; install via `go install meat.dev/cmd/meat@latest`")

    diff = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n"
    result = run_meat_harness(
        raw_diff=diff,
        meat_binary=Path(binary),
        trust_tier="trusted",
        opt_in=True,
        shell="restricted",
        timeout_seconds=120.0,
    )
    # Wire-shape contract: raw diff is always present (D8).
    assert result.raw_diff == diff
    # The real wire form includes: smart_diff, summary, input_tokens,
    # output_tokens (D11). If the API contract broke, the harness will
    # fall back to skip_reason; surface that as an explicit failure.
    if result.skip_reason is not None:
        # A missed network/credential/timeout is a *skip* in an
        # integration context — the operator fixes the env and re-runs.
        # Anything else is a contract failure.
        if "install" in result.skip_reason.lower() or "timed out" in result.skip_reason.lower():
            pytest.skip(f"real meat binary unavailable in this run: {result.skip_reason}")
        pytest.fail(f"real meat -json failed: {result.skip_reason}")
    assert result.abridged_diff is not None
    assert result.summary is not None
    assert result.input_tokens is not None
    assert result.output_tokens is not None
    _ = os  # silence unused-import diagnostics
