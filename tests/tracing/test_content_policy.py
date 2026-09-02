"""Content-capture policy for model payloads — OB2.1 RED suite.

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB2,
sub-wave OB2.1). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB2 contracts against the OB2.2 target API, which does not exist yet:

- ``mergecraft.tracing.content`` (new): ``ContentCapture`` StrEnum
  (``off``/``metadata``/``redacted``/``full``) with ``emits_body`` /
  ``emits_metadata`` properties; ``resolve_content_capture(configured,
  trust_tier)`` implementing D6 (default ``redacted``) + D7 (an untrusted tier
  is capped at ``metadata`` and this cannot be configured away); and
  ``capture_text(payload, prefix, policy, max_bytes)`` emitting ``<prefix>``,
  ``<prefix>.chars``, ``<prefix>.bytes``, ``<prefix>.sha256`` and
  ``<prefix>.truncated``.
- ``mergecraft.config.settings.TracingSettings``: a ``content`` field whose
  default is ``redacted`` (D6).

Locked decisions under test: **D6** (four levels, default ``redacted``),
**D7** (untrusted cap at ``metadata`` — not overridable by YAML config or env;
the security assertion), **D8** (content hash at every level above ``off`` —
the hash covers the original payload so it detects drift even between two runs
that shipped no body).

The env override var is pinned here as ``MERGECRAFT_TRACING_CONTENT``,
following the existing ``MERGECRAFT_TRACING*`` family in
``mergecraft/cli/tracing_precedence.py``; env beats YAML config (normal
precedence) but never beats the D7 untrusted cap **by itself**. An explicit
second knob (``exportUntrustedContent`` /
``MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT``) is required to ship bodies
on an untrusted run.

The ``content`` module import is lazy (fixture below), which kept collection
clean at RED-suite time. All 13 tests carried non-strict ``xfail`` markers
(``green after OB2.2``) while OB2.2 was unimplemented; the markers were removed
in the post-OB2.2 reconciliation (commit ``178f97c`` made all 13 XPASS), so
every test here is now a clean real pass.

Acceptance (plan §OB2.1, post-reconciliation): 13 collected; 13 passed;
0 xfail/xpass.
"""

from __future__ import annotations

import hashlib
import importlib
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.tracing.cap import TRACE_ATTRS_JSON_MAX_BYTES

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_ENV_VAR = "MERGECRAFT_TRACING_CONTENT"
_EXPORT_ENV_VAR = "MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT"
_PREFIX = "gen_ai.input"


@pytest.fixture
def content_module() -> Any:
    """Lazily import the OB2.2 content-policy module (``tracing/content.py``).

    The module does not exist until the OB2.2 implementation wave lands it.
    Importing inside the fixture (rather than at module top level) keeps test
    collection clean — zero collection errors — while every dependent test
    still fails RED at runtime under its non-strict ``xfail`` marker.
    """
    return importlib.import_module("mergecraft.tracing.content")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def test_off_emits_nothing(content_module: Any) -> None:
    """``off`` emits neither body nor metadata — not even the hash."""
    content = content_module
    policy = content.ContentCapture.OFF

    assert policy == "off"  # StrEnum
    assert not policy.emits_body
    assert not policy.emits_metadata
    result = content.capture_text(payload="prompt body", prefix=_PREFIX, policy=policy)
    assert result == {}


def test_metadata_emits_counts_and_hash_only(content_module: Any) -> None:
    """``metadata`` emits counts + hash but never the body (D6/D8)."""
    content = content_module
    policy = content.ContentCapture.METADATA
    payload = "Review this diff carefully."

    assert policy.emits_metadata
    assert not policy.emits_body
    result = content.capture_text(payload=payload, prefix=_PREFIX, policy=policy)
    assert _PREFIX not in result, "metadata level must not ship the body"
    assert result[f"{_PREFIX}.chars"] == len(payload)
    assert result[f"{_PREFIX}.bytes"] == len(payload.encode())
    assert result[f"{_PREFIX}.sha256"] == _sha256(payload)


def test_redacted_emits_body_through_the_secret_matcher(content_module: Any) -> None:
    """``redacted`` ships the body through ``analyzers.redact.redact_secrets``.

    No second redaction mechanism (global convention 4): the emitted body is
    exactly ``redact_secrets(payload)`` for an under-cap payload. The hash is
    of the ORIGINAL payload (D8 — drift detection must not depend on the
    redactor's output).
    """
    content = content_module
    policy = content.ContentCapture.REDACTED
    payload = "use token ghp_abcdefghijklmnop1234567890ABCDEFGHIJ to call the API"

    assert policy.emits_body
    assert policy.emits_metadata
    result = content.capture_text(payload=payload, prefix=_PREFIX, policy=policy)
    assert result[_PREFIX] == redact_secrets(payload)
    assert "ghp_abcdefghijklmnop" not in result[_PREFIX]
    assert result[f"{_PREFIX}.sha256"] == _sha256(payload)


def test_full_emits_body_capped_only(content_module: Any) -> None:
    """``full`` ships the body verbatim (capped only) — the secret matcher is NOT applied."""
    content = content_module
    policy = content.ContentCapture.FULL
    payload = "debug prompt with embedded token ghp_abcdefghijklmnop1234567890ABCDEFGHIJ"

    assert policy.emits_body
    result = content.capture_text(payload=payload, prefix=_PREFIX, policy=policy)
    assert result[_PREFIX] == payload
    assert result[f"{_PREFIX}.sha256"] == _sha256(payload)


def test_default_is_redacted(monkeypatch: MonkeyPatch, content_module: Any) -> None:
    """D6 — no configured level (and no env override) resolves to ``redacted``."""
    from mergecraft.config.settings import TracingSettings

    content = content_module
    monkeypatch.delenv(_ENV_VAR, raising=False)

    assert content.resolve_content_capture(None, "trusted") == content.ContentCapture.REDACTED
    assert TracingSettings().content == "redacted"


def test_untrusted_tier_is_capped_at_metadata(
    monkeypatch: MonkeyPatch, content_module: Any
) -> None:
    """D7 — an untrusted tier is capped at ``metadata``; the cap never raises a level."""
    content = content_module
    monkeypatch.delenv(_ENV_VAR, raising=False)
    monkeypatch.delenv(_EXPORT_ENV_VAR, raising=False)
    resolve = content.resolve_content_capture

    assert resolve("full", "untrusted") == content.ContentCapture.METADATA
    assert resolve("redacted", "untrusted") == content.ContentCapture.METADATA
    assert resolve("metadata", "untrusted") == content.ContentCapture.METADATA
    assert resolve("off", "untrusted") == content.ContentCapture.OFF, (
        "the cap lowers levels; it must never raise off to metadata"
    )


def test_untrusted_cap_cannot_be_overridden_by_config(
    monkeypatch: MonkeyPatch, content_module: Any
) -> None:
    """D7 — even ``content: full`` in YAML yields ``metadata`` at an untrusted tier."""
    from mergecraft.config.settings import TracingSettings

    content = content_module
    monkeypatch.delenv(_ENV_VAR, raising=False)
    monkeypatch.delenv(_EXPORT_ENV_VAR, raising=False)

    settings = TracingSettings.model_validate({"content": "full"})
    assert settings.content == "full", "the tracing block must accept the content field"
    assert (
        content.resolve_content_capture(settings.content, "untrusted")
        == content.ContentCapture.METADATA
    )


def test_untrusted_cap_cannot_be_overridden_by_env(
    monkeypatch: MonkeyPatch, content_module: Any
) -> None:
    """D7 — ``MERGECRAFT_TRACING_CONTENT=full`` yields ``metadata`` at an untrusted tier."""
    content = content_module
    monkeypatch.setenv(_ENV_VAR, "full")
    monkeypatch.delenv(_EXPORT_ENV_VAR, raising=False)

    assert content.resolve_content_capture(None, "untrusted") == content.ContentCapture.METADATA
    assert content.resolve_content_capture("off", "untrusted") == content.ContentCapture.METADATA


def test_env_beats_config_at_trusted_tier(monkeypatch: MonkeyPatch, content_module: Any) -> None:
    """Normal precedence still applies at a trusted tier: env wins over YAML config."""
    content = content_module
    resolve = content.resolve_content_capture

    monkeypatch.delenv(_ENV_VAR, raising=False)
    assert resolve("metadata", "trusted") == content.ContentCapture.METADATA

    monkeypatch.setenv(_ENV_VAR, "full")
    assert resolve("metadata", "trusted") == content.ContentCapture.FULL


def test_hash_is_emitted_at_every_level_above_off(content_module: Any) -> None:
    """D8 — ``.sha256`` (of the original payload) is present at metadata/redacted/full."""
    content = content_module
    payload = "drift detection payload"
    expected = _sha256(payload)

    for level in (
        content.ContentCapture.METADATA,
        content.ContentCapture.REDACTED,
        content.ContentCapture.FULL,
    ):
        result = content.capture_text(payload=payload, prefix="gen_ai.output", policy=level)
        assert result["gen_ai.output.sha256"] == expected, level

    assert (
        content.capture_text(
            payload=payload, prefix="gen_ai.output", policy=content.ContentCapture.OFF
        )
        == {}
    ), "off emits nothing, hash included"


def test_body_is_capped_and_marked_truncated(content_module: Any) -> None:
    """Bodies are capped at ``max_bytes`` and flagged ``.truncated``.

    The default cap is the shared trace-attrs budget
    (``cap.TRACE_ATTRS_JSON_MAX_BYTES``) — no second capping constant.
    """
    content = content_module
    full = content.ContentCapture.FULL

    capped = content.capture_text(payload="x" * 1024, prefix=_PREFIX, policy=full, max_bytes=128)
    assert capped[f"{_PREFIX}.truncated"] is True
    assert len(capped[_PREFIX].encode()) <= 128

    under = content.capture_text(payload="short", prefix=_PREFIX, policy=full, max_bytes=128)
    assert under[f"{_PREFIX}.truncated"] is False

    defaulted = content.capture_text(
        payload="y" * (TRACE_ATTRS_JSON_MAX_BYTES + 512), prefix=_PREFIX, policy=full
    )
    assert defaulted[f"{_PREFIX}.truncated"] is True
    assert len(defaulted[_PREFIX].encode()) <= TRACE_ATTRS_JSON_MAX_BYTES


def test_original_size_is_reported_before_truncation(content_module: Any) -> None:
    """``.chars`` / ``.bytes`` / ``.sha256`` describe the ORIGINAL payload, not the cap."""
    content = content_module
    payload = "x" * 1024

    result = content.capture_text(
        payload=payload, prefix=_PREFIX, policy=content.ContentCapture.FULL, max_bytes=128
    )
    assert result[f"{_PREFIX}.chars"] == 1024
    assert result[f"{_PREFIX}.bytes"] == 1024
    assert result[f"{_PREFIX}.sha256"] == _sha256(payload)
    assert result[f"{_PREFIX}.truncated"] is True
    assert len(result[_PREFIX]) < 1024


def test_invalid_level_falls_back_to_default_not_full(
    monkeypatch: MonkeyPatch, content_module: Any
) -> None:
    """An unrecognised level (config or env) falls back to the default — fail safe, never open."""
    content = content_module
    redacted = content.ContentCapture.REDACTED

    monkeypatch.delenv(_ENV_VAR, raising=False)
    assert content.resolve_content_capture("everything", "trusted") == redacted
    assert content.resolve_content_capture("EVERYTHING", "trusted") != content.ContentCapture.FULL

    monkeypatch.setenv(_ENV_VAR, "bogus")
    assert content.resolve_content_capture(None, "trusted") == redacted


def test_untrusted_export_flag_lifts_cap(monkeypatch: MonkeyPatch, content_module: Any) -> None:
    """``export_untrusted=True`` lets a body-emitting level through on untrusted."""
    content = content_module
    monkeypatch.delenv(_ENV_VAR, raising=False)
    monkeypatch.delenv(_EXPORT_ENV_VAR, raising=False)

    assert (
        content.resolve_content_capture("full", "untrusted", export_untrusted=True)
        == content.ContentCapture.FULL
    )
    assert (
        content.resolve_content_capture("redacted", "untrusted", export_untrusted=True)
        == content.ContentCapture.REDACTED
    )


def test_untrusted_export_env_lifts_cap(monkeypatch: MonkeyPatch, content_module: Any) -> None:
    """``MERGECRAFT_TRACING_EXPORT_UNTRUSTED_CONTENT=true`` lifts D7."""
    content = content_module
    monkeypatch.setenv(_ENV_VAR, "full")
    monkeypatch.setenv(_EXPORT_ENV_VAR, "true")

    assert content.resolve_content_capture(None, "untrusted") == content.ContentCapture.FULL


def test_export_env_false_beats_yaml_true(monkeypatch: MonkeyPatch, content_module: Any) -> None:
    """Env ``false`` keeps the cap even when YAML ``exportUntrustedContent`` is true."""
    content = content_module
    monkeypatch.delenv(_ENV_VAR, raising=False)
    monkeypatch.setenv(_EXPORT_ENV_VAR, "false")

    assert (
        content.resolve_content_capture("full", "untrusted", export_untrusted=True)
        == content.ContentCapture.METADATA
    )


def test_yaml_export_untrusted_content_field() -> None:
    """``TracingSettings`` accepts ``exportUntrustedContent`` and omits the default."""
    from mergecraft.config.settings import TracingSettings

    settings = TracingSettings.model_validate({"exportUntrustedContent": True, "content": "full"})
    assert settings.export_untrusted_content is True
    dumped = settings.model_dump(by_alias=True)
    assert dumped["exportUntrustedContent"] is True
    defaulted = TracingSettings()
    assert defaulted.export_untrusted_content is False
    assert "exportUntrustedContent" not in defaulted.model_dump(by_alias=True)
