"""``trust.sandboxTrustedAuthors`` schema — fix/verdict-integrity-and-publication Task A."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import TrustSettings


def test_sandbox_trusted_authors_defaults_to_empty_list() -> None:
    """Absent key must resolve to ``[]`` — the no-op default."""
    settings = TrustSettings.model_validate({"selfReview": "off", "agentSandbox": "dispatch"})
    assert settings.sandbox_trusted_authors == []


def test_sandbox_trusted_authors_accepts_email_list() -> None:
    settings = TrustSettings.model_validate(
        {
            "selfReview": "off",
            "agentSandbox": "same-repo",
            "sandboxTrustedAuthors": ["Alex@Example.com", "bot@example.com"],
        }
    )
    assert settings.sandbox_trusted_authors == ["alex@example.com", "bot@example.com"]


def test_sandbox_trusted_authors_normalizes_case_and_whitespace() -> None:
    settings = TrustSettings.model_validate(
        {"sandboxTrustedAuthors": ["  MIXED-Case@Example.COM  "]}
    )
    assert settings.sandbox_trusted_authors == ["mixed-case@example.com"]


def test_sandbox_trusted_authors_drops_blank_entries() -> None:
    settings = TrustSettings.model_validate({"sandboxTrustedAuthors": ["a@example.com", "  "]})
    assert settings.sandbox_trusted_authors == ["a@example.com"]


def test_sandbox_trusted_authors_rejects_non_string_entries() -> None:
    with pytest.raises(ValidationError):
        TrustSettings.model_validate({"sandboxTrustedAuthors": ["a@example.com", 123]})


def test_sandbox_trusted_authors_rejects_non_list_value() -> None:
    with pytest.raises(ValidationError):
        TrustSettings.model_validate({"sandboxTrustedAuthors": "a@example.com"})


def test_sandbox_trusted_authors_populate_by_name_still_works() -> None:
    """``populate_by_name=True`` — the snake_case field name is also accepted."""
    settings = TrustSettings.model_validate({"sandbox_trusted_authors": ["a@example.com"]})
    assert settings.sandbox_trusted_authors == ["a@example.com"]


def test_trust_settings_still_rejects_unknown_top_level_keys() -> None:
    """Regression — adding the new field must not loosen ``extra=\"forbid\"``."""
    with pytest.raises(ValidationError):
        TrustSettings.model_validate({"sandboxTrustedAuthorsTypo": ["a@example.com"]})
