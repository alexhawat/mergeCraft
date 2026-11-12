"""RH5 — redaction pins for recorder."""

from __future__ import annotations

import json

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.redaction_sentinel import REDACTION_SENTINEL
from tests.support.provider_harness import DUMMY_API_KEY
from tests.support.provider_harness import recorder as recorder_module


def test_redacts_provider_api_keys() -> None:
    assert DUMMY_API_KEY not in redact_secrets(DUMMY_API_KEY)
    assert REDACTION_SENTINEL in redact_secrets(DUMMY_API_KEY)


def test_redacts_github_tokens_and_secret_like_values() -> None:
    raw = "ghp_" + "x" * 36
    redacted = redact_secrets(raw)
    assert raw not in redacted
    assert REDACTION_SENTINEL in redacted


def test_redacts_sensitive_request_fields_before_fixture_write() -> None:
    from tests.support.provider_harness import redaction as redaction_module

    token = "ghp_" + "x" * 36
    payload = {
        "headers": {"authorization": f"Bearer {token}", "accept": "application/json"},
        "messages": [{"role": "user", "content": f"token is {token}"}],
        "model": "demo-model",
    }

    cleaned = redaction_module.sanitize_value(payload)

    assert token not in json.dumps(cleaned)
    assert isinstance(cleaned, dict)
    assert cleaned["model"] == "demo-model"
    assert REDACTION_SENTINEL in json.dumps(cleaned)


def test_recording_requires_explicit_local_opt_in(monkeypatch) -> None:
    monkeypatch.delenv("MERGECRAFT_PROVIDER_HARNESS_RECORD", raising=False)
    assert recorder_module.recording_enabled() is False
