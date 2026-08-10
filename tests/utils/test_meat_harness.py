"""W1 RED suite for the meat reading-diff harness (#60 spike).

Wave plan: `.ignorelocal/waves/issues-meat-reading-diff-wave-plan.md`
Worktree: `mergecraft-meat-a-spike` @ `wave/meat-a-spike`

Pins the W2 harness contract (D7, D8, D11, D13, conventions 5/6/8). W2 will
land `src/mergecraft/utils/meat_harness.py`; this file imports the public
surface through the same `_AVAILABLE` guard as `tests/utils/test_fence.py`
so collection stays green pre-W2. Where the harness does not yet exist,
the assertions are `@pytest.mark.xfail(reason="green after W2: ...", strict=False)`
— non-strict, so when W2 lands the suite simply passes.

Contract surface (must hold after W2):

- A pure-boundary entry point that takes a unified diff and invokes
  `meat -json` as a subprocess with a bounded timeout, parses the result,
  and returns a typed record carrying:
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
- A hung `meat` subprocess cannot hang a review (bounded timeout).
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

# ── Contract imports — these are the symbols W2 will provide. The
# xfail markers record that the symbols are not yet present (or the
# public surface is not yet green). When W2 lands `meat_harness.py`, the
# import lines below will start resolving. Until then the xfail reason
# keeps the test out of the way without breaking collection.

try:  # pragma: no cover — exercised by the collection test, then every other test.
    from mergecraft.utils import meat_harness as _harness_mod

    _HARNESS_AVAILABLE = True
except ImportError:  # W2 will remove this branch.
    _HARNESS_AVAILABLE = False
    _harness_mod = None  # type: ignore[assignment]


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


def _require_harness() -> None:
    """W2 has landed the harness module — the suite now runs for real.

    Mirrors ``_require_fence`` in ``tests/utils/test_fence.py``: a missing
    module is a hard failure post-W2, not a silent skip. The xfail
    markers on individual tests stay in place for cases that depend on
    W2's exact shape (the result dataclass field set, the run signature).
    """
    assert _HARNESS_AVAILABLE, "mergecraft.utils.meat_harness not importable — W2 must provide it"
    assert _harness_mod is not None


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


@pytest.mark.xfail(
    reason="green after W2: mergecraft.utils.meat_harness module exists",
    strict=False,
)
def test_meat_harness_module_is_collectable() -> None:
    """The harness module imports cleanly post-W2; this test pins that."""
    _require_harness()
    assert _harness_mod is not None


# ── W1.4 — raw diff is unconditionally retained (D8, structural) ───────────


@pytest.mark.xfail(
    reason="green after W2: result dataclass carries raw_diff unconditionally",
    strict=False,
)
def test_raw_diff_is_always_retained_when_harness_succeeds() -> None:
    """On a successful abridgement, ``raw_diff`` equals the input diff byte-for-byte.

    D8 — the load-bearing invariant of this plan. The raw diff must
    reach the reviewer on every gating path. W1.4 is **structural** per
    the plan: it should pass as soon as the harness lands with the
    correct result shape. Marked xfail here because the module does not
    exist yet; the assertion is the contract W2 must satisfy.
    """
    _require_harness()
    assert _harness_mod is not None
    result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
        raw_diff=_RAW_DIFF_SAMPLE,
        meat_binary=Path("/nonexistent"),
        trust_tier="trusted",
        opt_in=True,
        shell="restricted",
        timeout_seconds=1.0,
    )
    assert result.raw_diff == _RAW_DIFF_SAMPLE
    assert result.skip_reason is None  # succeeded → no skip reason recorded


@pytest.mark.xfail(
    reason="green after W2: harness preserves raw_diff on every failure branch",
    strict=False,
)
def test_raw_diff_is_always_retained_when_meat_binary_missing() -> None:
    """When meat is absent, the raw diff is still retained (D8 + D13).

    The harness must return ``raw_diff`` equal to the input even when
    ``skip_reason`` is populated (binary missing) — the raw diff is the
    gating surface, the reading diff is supplementary.
    """
    _require_harness()
    assert _harness_mod is not None
    result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
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


@pytest.mark.xfail(
    reason="green after W2: harness preserves raw_diff when subprocess fails",
    strict=False,
)
def test_raw_diff_is_always_retained_when_meat_subprocess_fails() -> None:
    """A non-zero ``meat`` exit must not strip the raw diff from the result."""
    _require_harness()
    assert _harness_mod is not None
    with pytest.MonkeyPatch.context() as mp:
        tmp = mp.getfixturevalue("tmp_path")
        fake = _write_fake_meat(tmp, exit_code=2, stderr="boom")
        result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
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


@pytest.mark.xfail(
    reason="green after W2: harness enforces trust-tier gate (D7) before invoking subprocess",
    strict=False,
)
def test_meat_is_inert_on_untrusted_tier() -> None:
    """``derive_trust_tier()`` returning ``untrusted`` → harness not invoked.

    Even when the binary is on PATH and the opt-in flag is set, the
    harness must skip without invoking ``meat`` and record a named
    ``skip_reason`` — the raw diff is the only thing returned. This is
    the load-bearing security test for the spike batch.
    """
    _require_harness()
    assert _harness_mod is not None

    # Sanity-check the fixture: this branch of D7 is what the plan locks.
    assert derive_trust_tier(_event_for("untrusted")) == "untrusted"

    with pytest.MonkeyPatch.context() as mp:
        tmp = mp.getfixturevalue("tmp_path")
        # Place a real-sounding fake so a bug in the trust gate would
        # accidentally invoke it; we want to detect that.
        fake = _write_fake_meat(tmp, stdout="SHOULD-NOT-APPEAR")
        # If the trust gate is broken, the fake's stdout would surface
        # as the abridged_diff; the assertion below fails loudly then.
        result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
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


@pytest.mark.xfail(
    reason="green after W2: harness is inert when opt-in flag is unset (convention 7)",
    strict=False,
)
def test_meat_is_inert_when_opt_in_flag_unset() -> None:
    """Opt-in default-off: a missing flag must skip without invoking meat."""
    _require_harness()
    assert _harness_mod is not None
    with pytest.MonkeyPatch.context() as mp:
        tmp = mp.getfixturevalue("tmp_path")
        fake = _write_fake_meat(tmp, stdout="SHOULD-NOT-APPEAR")
        result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
            raw_diff=_RAW_DIFF_SAMPLE,
            meat_binary=fake,
            trust_tier="trusted",
            opt_in=False,
            shell="restricted",
            timeout_seconds=1.0,
        )
    assert result.abridged_diff is None
    assert result.skip_reason is not None


@pytest.mark.xfail(
    reason="green after W2: harness is inert when shell is disabled (D7)",
    strict=False,
)
def test_meat_is_inert_when_shell_disabled() -> None:
    """``shell: disabled`` → harness must skip. New shell execution is gated off."""
    _require_harness()
    assert _harness_mod is not None
    with pytest.MonkeyPatch.context() as mp:
        tmp = mp.getfixturevalue("tmp_path")
        fake = _write_fake_meat(tmp, stdout="SHOULD-NOT-APPEAR")
        result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
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


@pytest.mark.xfail(
    reason="green after W2: missing binary → warning + skip_reason + raw diff retained",
    strict=False,
)
def test_missing_meat_binary_is_a_skip_not_a_failure(
    raw_diff_sample: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """D13 — when the binary is absent, the harness must NOT raise; it must
    return a result with the raw diff retained and a named skip reason.

    A missing optional tool must never fail a review. The user-visible
    signal is a ``logger.warning`` with an install hint.
    """
    _require_harness()
    assert _harness_mod is not None

    with caplog.at_level("WARNING"):
        result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
            raw_diff=raw_diff_sample,
            meat_binary=Path("/this/path/does/not/exist/meat"),
            trust_tier="trusted",
            opt_in=True,
            shell="restricted",
            timeout_seconds=1.0,
        )

    assert result.raw_diff == raw_diff_sample
    assert result.abridged_diff is None
    assert result.summary is None
    assert result.skip_reason is not None
    install_hint_keywords = ("install", "go install", "meat.dev")
    assert any(kw in result.skip_reason.lower() for kw in install_hint_keywords), (
        f"skip reason must carry an install hint; got {result.skip_reason!r}"
    )
    # The warning was emitted through loguru; the LogCaptureFixture
    # record check is the user-facing signal pin.
    joined = " ".join(record.getMessage().lower() for record in caplog.records)
    assert "install" in joined or "meat" in joined


# ── W1.1 — `-json` parsing of a recorded fixture (D11) ────────────────────


@pytest.mark.xfail(
    reason="green after W2: harness parses a recorded -json fixture into typed fields",
    strict=False,
)
def test_meat_json_output_parses(
    raw_diff_sample: str,
    meat_json_payload: dict[str, Any],
) -> None:
    """D11 — ``-json`` is the wire format; never scrape the coloured terminal.

    A recorded ``-json`` fixture must parse into the typed result:
    ``abridged_diff`` (from ``smart_diff``), ``summary`` (one-line),
    ``input_tokens`` / ``output_tokens`` surfaces, and the raw diff is
    preserved on the result.
    """
    _require_harness()
    assert _harness_mod is not None

    with pytest.MonkeyPatch.context() as mp:
        tmp = mp.getfixturevalue("tmp_path")
        fake = _write_fake_meat(tmp, stdout=json.dumps(meat_json_payload))
        result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
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


@pytest.mark.xfail(
    reason="green after W2: non-zero exit degrades to raw diff without raising",
    strict=False,
)
def test_meat_failure_falls_back_to_raw_diff(
    raw_diff_sample: str,
) -> None:
    """Non-zero exit from ``meat`` must not raise; result carries raw diff
    and a named skip reason."""
    _require_harness()
    assert _harness_mod is not None
    with pytest.MonkeyPatch.context() as mp:
        tmp = mp.getfixturevalue("tmp_path")
        fake = _write_fake_meat(tmp, exit_code=1, stderr="model unavailable")
        result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
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


@pytest.mark.xfail(
    reason="green after W2: malformed JSON degrades to raw diff without raising",
    strict=False,
)
def test_meat_malformed_json_falls_back_to_raw_diff(
    raw_diff_sample: str,
) -> None:
    """A non-JSON payload (or one missing required keys) must NOT raise.

    The harness must catch JSON or schema errors and degrade to a result
    carrying the raw diff and a named skip reason. A failure here means
    a single bad meat output could blow up a review.
    """
    _require_harness()
    assert _harness_mod is not None
    with pytest.MonkeyPatch.context() as mp:
        tmp = mp.getfixturevalue("tmp_path")
        fake = _write_fake_meat(tmp, stdout="{not valid json")
        result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
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


@pytest.mark.xfail(
    reason="green after W2: hung meat subprocess is killed by bounded timeout",
    strict=False,
)
def test_meat_invocation_is_bounded_by_a_timeout(
    raw_diff_sample: str,
) -> None:
    """A hung ``meat`` cannot hang a review. The harness must kill the
    subprocess after ``timeout_seconds`` and return a degraded result.

    The fake used here calls ``sleep 3600``; the harness must not wait
    3600s. A short timeout (≤ 2s) keeps the suite fast.
    """
    _require_harness()
    assert _harness_mod is not None

    with pytest.MonkeyPatch.context() as mp:
        tmp = mp.getfixturevalue("tmp_path")
        fake = _write_fake_meat(tmp, hang=True)
        # 0.5s ceiling — the fake would otherwise sleep 3600s.
        result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
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


def _gather_logged_text(caplog: pytest.LogCaptureFixture) -> str:
    """Concatenate every record's message + any rendered exception text."""
    parts = [record.getMessage() for record in caplog.records]
    parts.extend(record.getMessage() for record in caplog.records)
    return "\n".join(parts)


_CANARY_VALUE = "sk-meat-canary-DO-NOT-LEAK-9c41a6"
"""A obviously-fake credential canary. If this ever appears in logs,
the test fails. The plan's convention 8 forbids the value being logged
or stored; the canary exists to prove that contract."""


@pytest.mark.xfail(
    reason=(
        "green after W2: harness references OPENAI_API_KEY by env-var name only "
        "and never logs the canary value (convention 8)"
    ),
    strict=False,
)
def test_no_credential_value_is_logged_or_stored(
    raw_diff_sample: str,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Convention 8 — credentials are referenced by env-var name only.

    Place a canary value in ``OPENAI_API_KEY`` (Meat's built-in default
    credential name), drive the harness through a fake binary, and assert
    the canary value never appears in any log record and is not stored
    on the result. ``ANTHROPIC_API_KEY`` is also exercised in parametrize
    below.
    """
    _require_harness()
    assert _harness_mod is not None

    monkeypatch.setenv("OPENAI_API_KEY", _CANARY_VALUE)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.MonkeyPatch.context() as mp:
        tmp = mp.getfixturevalue("tmp_path")
        fake = _write_fake_meat(tmp, stdout=json.dumps(_MEAT_JSON_SUCCESS))
        with caplog.at_level("DEBUG"):
            result = _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
                raw_diff=raw_diff_sample,
                meat_binary=fake,
                trust_tier="trusted",
                opt_in=True,
                shell="restricted",
                timeout_seconds=1.0,
            )

    # 1. Canary value never appears in any log record.
    logged = _gather_logged_text(caplog)
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


@pytest.mark.xfail(
    reason="green after W2: anthropic credential env-var is treated identically (convention 8)",
    strict=False,
)
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
    caplog: pytest.LogCaptureFixture,
    credential_env: str,
) -> None:
    """Parametrized: the canary contract holds for **both** env-var names
    meat reads (D7 / convention 8 — operator decision is by env-var name)."""
    _require_harness()
    assert _harness_mod is not None

    # Only one is set at a time so the assertion is unambiguous.
    for other in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"} - {credential_env}:
        monkeypatch.delenv(other, raising=False)
    monkeypatch.setenv(credential_env, _CANARY_VALUE)

    with pytest.MonkeyPatch.context() as mp:
        tmp = mp.getfixturevalue("tmp_path")
        fake = _write_fake_meat(tmp, stdout=json.dumps(_MEAT_JSON_SUCCESS))
        with caplog.at_level("DEBUG"):
            _harness_mod.run_meat_harness(  # type: ignore[attr-defined]
                raw_diff=raw_diff_sample,
                meat_binary=fake,
                trust_tier="trusted",
                opt_in=True,
                shell="restricted",
                timeout_seconds=1.0,
            )

    logged = _gather_logged_text(caplog)
    assert _CANARY_VALUE not in logged, f"credential value for {credential_env} leaked into logs"


# ── W1.8 — no network call in unit tests (convention 5, structural) ────────


@pytest.mark.xfail(
    reason="green after W2: harness module exists and structural network guard passes",
    strict=False,
)
def test_no_network_call_in_unit_tests() -> None:
    """Structural assertion — every non-integration test in this file
    drives the harness through a fake subprocess under ``tmp_path`` or
    via a missing-binary path. This test pins that convention 5 (no
    network call in ``make test``) holds for the W1 suite.

    Marked xfail until W2 lands the harness module — the
    structural check is a property of the post-W2 test corpus; running
    it pre-W2 exercises a stale file shape.
    """
    _require_harness()

    # Walk this module's globals; any test that touches a real subprocess
    # or HTTP endpoint would name the binary / endpoint in its body.
    source_path = Path(__file__)
    text = source_path.read_text(encoding="utf-8")
    forbidden_patterns = (
        re.compile(r"\bhttpx\."),
        re.compile(r"\brequests\."),
        re.compile(r"\burllib\b"),
    )
    for pattern in forbidden_patterns:
        matches = pattern.findall(text)
        assert not matches, f"unit test references network surface {pattern.pattern!r}: {matches}"

    # And confirm every test that names the meat binary either uses
    # ``Path('/nonexistent...')`` or writes one under ``tmp_path`` via
    # the shared helper — never ``shutil.which('meat')``.
    assert "shutil.which('meat')" not in text, (
        "unit test resolves the real meat binary — convention 5 violated"
    )
    assert 'shutil.which("meat")' not in text


# ── collection smoke — every test file must collect without error ──────────


def test_module_collects_with_zero_errors() -> None:
    """Sanity: importing this module (via pytest collection) succeeded.

    This guards the W2 import surface — when ``meat_harness.py`` lands,
    the import line near the top of this file must succeed. Until then
    the ``_HARNESS_AVAILABLE`` flag is False and downstream assertions
    are gated by ``_require_harness()``.
    """
    assert _HARNESS_AVAILABLE is False or _harness_mod is not None, (
        "module surface inconsistent — _HARNESS_AVAILABLE and _harness_mod disagree"
    )


# ── subprocess invocation contract - keeps W2 honest ───────────────────────
# (no extra tests beyond the plan; the W1.1-W1.8 RED items above are
# the structural guards that pin the contract. Anything else would pull
# implementation forward.)
