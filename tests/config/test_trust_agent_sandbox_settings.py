"""W1.1b — TrustSettings agentSandbox schema (wave 15, green after W2)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import TrustSettings


@pytest.mark.parametrize("tier", ["never", "merged-only", "dispatch", "same-repo"])
def test_trust_settings_accepts_agent_sandbox(tier: str) -> None:
    settings = TrustSettings.model_validate({"selfReview": "off", "agentSandbox": tier})
    assert settings.agent_sandbox == tier  # type: ignore[attr-defined]


def test_trust_settings_rejects_unknown_trust_key() -> None:
    with pytest.raises(ValidationError, match=r"agentSandbox|extra|forbid|unknown"):
        TrustSettings.model_validate({"selfReview": "off", "agentSandboxTypo": "dispatch"})


def test_trust_settings_still_rejects_extra_top_level_keys() -> None:
    """Regression — extra=forbid on TrustSettings is unchanged."""
    with pytest.raises(ValidationError):
        TrustSettings.model_validate({"selfReview": "off", "notARealKey": True})
