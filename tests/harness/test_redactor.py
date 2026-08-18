"""RH5 — redaction pins for recorder."""

from __future__ import annotations

import inspect

from mergecraft.analyzers.redact import redact_secrets
from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness import recorder as recorder_module


def test_redacts_provider_api_keys() -> None:
    assert DUMMY_API_KEY not in redact_secrets(DUMMY_API_KEY)
    assert "[REDACTED]" in redact_secrets(DUMMY_API_KEY)


def test_redacts_github_tokens_and_secret_like_values() -> None:
    raw = "ghp_" + "x" * 36
    redacted = redact_secrets(raw)
    assert raw not in redacted
    assert "[REDACTED]" in redacted


def test_redacts_sensitive_request_fields_before_fixture_write() -> None:
    source = inspect.getsource(recorder_module._sanitize)
    assert "redact_secrets" in source or "redact_attrs" in inspect.getsource(
        recorder_module.write_record
    )


def test_recording_requires_explicit_local_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("MERGECRAFT_PROVIDER_HARNESS_RECORD", raising=False)
    assert recorder_module.recording_enabled() is False


def test_recording_never_commits_or_pushes() -> None:
    source = inspect.getsource(recorder_module)
    assert "git" not in source
    assert "subprocess" not in source
