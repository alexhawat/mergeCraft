"""Frozen parity and fail-closed pins for the content-capture environment.

``resolve_content_capture`` reads ``MERGECRAFT_TRACING_CONTENT`` and
``MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT`` from the environment, then
falls back to the configured level and the safe default, and finally applies
the untrusted-tier cap. Well-formed values keep today's resolution exactly
(frozen below); a malformed content level or export flag is a configuration
error instead of a silent fall-through, because the fall-through can pick a
more permissive value the operator never chose.

The env-var reads move onto the typed tracing model; ``mergecraft.config.env``
is imported inside the failing tests so collection stays clean before it
exists. No ``xfail`` marker is used.
"""

from __future__ import annotations

import pytest

# The full tracing env family is cleared for every case: once the read moves
# onto the typed model, a stray region/flag value could trip an unrelated
# validator and hide the behaviour under test.
_TRACING_ENV_KEYS = [
    "MERGECRAFT_TRACING",
    "MERGECRAFT_TRACING_TO",
    "MERGECRAFT_TRACE_DIR",
    "MERGECRAFT_LOGFIRE_TOKEN",
    "MERGECRAFT_OTEL_ENDPOINT",
    "MERGECRAFT_TRACING_PROJECT",
    "MERGECRAFT_TRACING_REGION",
    "MERGECRAFT_TRACING_CONTENT",
    "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT",
]


@pytest.fixture(autouse=True)
def _clear_tracing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _TRACING_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# (env content, configured, trust tier, expected level) — frozen from the
# current ``resolve_content_capture``.
_CONTENT_PARITY: list[tuple[str | None, str | None, str, str]] = [
    (None, None, "trusted", "redacted"),
    (None, None, "untrusted", "metadata"),
    (None, "metadata", "trusted", "metadata"),
    (None, "metadata", "untrusted", "metadata"),
    (None, "full", "trusted", "full"),
    (None, "full", "untrusted", "metadata"),
    (None, "bogus", "trusted", "redacted"),
    (None, "bogus", "untrusted", "metadata"),
    ("", None, "trusted", "redacted"),
    ("", None, "untrusted", "metadata"),
    ("", "metadata", "trusted", "metadata"),
    ("", "metadata", "untrusted", "metadata"),
    ("", "full", "trusted", "full"),
    ("", "full", "untrusted", "metadata"),
    ("", "bogus", "trusted", "redacted"),
    ("", "bogus", "untrusted", "metadata"),
    ("off", None, "trusted", "off"),
    ("off", None, "untrusted", "off"),
    ("off", "metadata", "trusted", "off"),
    ("off", "metadata", "untrusted", "off"),
    ("off", "full", "trusted", "off"),
    ("off", "full", "untrusted", "off"),
    ("off", "bogus", "trusted", "off"),
    ("off", "bogus", "untrusted", "off"),
    ("metadata", None, "trusted", "metadata"),
    ("metadata", None, "untrusted", "metadata"),
    ("metadata", "metadata", "trusted", "metadata"),
    ("metadata", "metadata", "untrusted", "metadata"),
    ("metadata", "full", "trusted", "metadata"),
    ("metadata", "full", "untrusted", "metadata"),
    ("metadata", "bogus", "trusted", "metadata"),
    ("metadata", "bogus", "untrusted", "metadata"),
    ("redacted", None, "trusted", "redacted"),
    ("redacted", None, "untrusted", "metadata"),
    ("redacted", "metadata", "trusted", "redacted"),
    ("redacted", "metadata", "untrusted", "metadata"),
    ("redacted", "full", "trusted", "redacted"),
    ("redacted", "full", "untrusted", "metadata"),
    ("redacted", "bogus", "trusted", "redacted"),
    ("redacted", "bogus", "untrusted", "metadata"),
    ("full", None, "trusted", "full"),
    ("full", None, "untrusted", "metadata"),
    ("full", "metadata", "trusted", "full"),
    ("full", "metadata", "untrusted", "metadata"),
    ("full", "full", "trusted", "full"),
    ("full", "full", "untrusted", "metadata"),
    ("full", "bogus", "trusted", "full"),
    ("full", "bogus", "untrusted", "metadata"),
]


@pytest.mark.parametrize(
    ("env_content", "configured", "tier", "expected"),
    _CONTENT_PARITY,
    ids=[
        f"env={env_content!r}-cfg={configured!r}-tier={tier}"
        for env_content, configured, tier, _ in _CONTENT_PARITY
    ],
)
def test_content_level_parity(
    env_content: str | None,
    configured: str | None,
    tier: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A well-formed env level resolves exactly as before, cap included."""
    if env_content is not None:
        monkeypatch.setenv("MERGECRAFT_TRACING_CONTENT", env_content)

    from mergecraft.tracing.content import ContentCapture, resolve_content_capture

    assert resolve_content_capture(configured, tier) == ContentCapture(expected)


# (export env flag, export_untrusted argument, expected level) — content is
# always ``full`` and the tier ``untrusted`` so the flag is what moves the cap.
_EXPORT_PARITY: list[tuple[str | None, bool | None, str]] = [
    (None, None, "metadata"),
    (None, True, "full"),
    (None, False, "metadata"),
    ("", None, "metadata"),
    ("", True, "full"),
    ("", False, "metadata"),
    ("true", None, "full"),
    ("true", True, "full"),
    ("true", False, "full"),
    ("false", None, "metadata"),
    ("false", True, "metadata"),
    ("false", False, "metadata"),
]


@pytest.mark.parametrize(
    ("env_flag", "argument", "expected"),
    _EXPORT_PARITY,
    ids=[f"env={env_flag!r}-arg={argument}" for env_flag, argument, _ in _EXPORT_PARITY],
)
def test_export_untrusted_parity(
    env_flag: str | None,
    argument: bool | None,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The env flag, when set, still beats the argument; the cap still applies."""
    monkeypatch.setenv("MERGECRAFT_TRACING_CONTENT", "full")
    if env_flag is not None:
        monkeypatch.setenv("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", env_flag)

    from mergecraft.tracing.content import ContentCapture, resolve_content_capture

    assert resolve_content_capture(None, "untrusted", export_untrusted=argument) == ContentCapture(
        expected
    )


# ── fail-closed: a malformed value is a configuration error ─────────────────


@pytest.mark.parametrize("malformed", ["capture-everything", "FULLY", "body"])
def test_malformed_content_level_fails_closed(
    malformed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown content level raises instead of falling back to the YAML level."""
    canary = f"{malformed}-canary-49a"
    monkeypatch.setenv("MERGECRAFT_TRACING_CONTENT", canary)

    from mergecraft.config.env import EnvSettingsError
    from mergecraft.tracing.content import resolve_content_capture

    with pytest.raises(EnvSettingsError) as excinfo:
        resolve_content_capture(None, "trusted")

    message = str(excinfo.value)
    assert "MERGECRAFT_TRACING_CONTENT" in message
    assert canary not in message


@pytest.mark.parametrize("malformed", ["flase", "ture", "yess"])
def test_malformed_export_flag_fails_closed(
    malformed: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown export flag raises instead of leaving bodies capped silently."""
    canary = f"{malformed}-canary-49a"
    monkeypatch.setenv("MERGECRAFT_TRACING_CONTENT", "full")
    monkeypatch.setenv("MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT", canary)

    from mergecraft.config.env import EnvSettingsError
    from mergecraft.tracing.content import resolve_content_capture

    with pytest.raises(EnvSettingsError) as excinfo:
        resolve_content_capture(None, "untrusted")

    message = str(excinfo.value)
    assert "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT" in message
    assert canary not in message
