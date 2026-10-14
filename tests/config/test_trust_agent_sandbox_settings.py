"""TrustSettings agentSandbox schema (wave 15, green after W2; hardened in CF2).

Contracts pinned here:

- The four documented tiers (``never``, ``merged-only``, ``dispatch``,
  ``same-repo``) validate and are normalized with strip/lower.
- Any other value — including the plausible-looking ``off`` / ``false``
  spellings, an empty string, a number, or a YAML boolean — is a configuration
  error, not a silent fall-back to ``dispatch`` (fail closed, never coerced).
  The error names the four accepted tiers so the operator can fix it.
- ``load_repo_settings`` surfaces the same failure for a config file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import TrustSettings, load_repo_settings

_FOUR_TIERS = ("never", "merged-only", "dispatch", "same-repo")


@pytest.mark.parametrize("tier", ["never", "merged-only", "dispatch", "same-repo"])
def test_trust_settings_accepts_agent_sandbox(tier: str) -> None:
    settings = TrustSettings.model_validate({"selfReview": "off", "agentSandbox": tier})
    assert settings.agent_sandbox == tier  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" Never ", "never"),
        ("NEVER", "never"),
        ("  Same-Repo  ", "same-repo"),
        ("MERGED-ONLY", "merged-only"),
        ("Dispatch", "dispatch"),
    ],
)
def test_valid_agent_sandbox_still_normalizes(raw: str, expected: str) -> None:
    """Valid tiers keep the strip/lower normalization they had before the fix."""
    settings = TrustSettings.model_validate({"selfReview": "off", "agentSandbox": raw})
    assert settings.agent_sandbox == expected  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param("off", id="off"),
        pytest.param("false", id="false-string"),
        pytest.param(False, id="false-yaml-bool"),
        pytest.param(True, id="true-yaml-bool"),
        pytest.param("nevr", id="typo"),
        pytest.param("", id="empty"),
        pytest.param("1", id="one-string"),
        pytest.param(1, id="one-int"),
        pytest.param(None, id="none"),
        pytest.param("enabled", id="enabled"),
        pytest.param("same_repo", id="underscored"),
    ],
)
def test_invalid_agent_sandbox_fails_validation(raw: object) -> None:
    """An invalid tier is refused — never coerced to ``dispatch`` (CF-D1)."""
    with pytest.raises(ValidationError) as exc_info:
        TrustSettings.model_validate({"selfReview": "off", "agentSandbox": raw})
    text = str(exc_info.value).lower()
    for tier in _FOUR_TIERS:
        assert tier in text, f"error does not name tier {tier!r}: {exc_info.value}"


def test_trust_settings_rejects_unknown_trust_key() -> None:
    with pytest.raises(ValidationError, match=r"agentSandbox|extra|forbid|unknown"):
        TrustSettings.model_validate({"selfReview": "off", "agentSandboxTypo": "dispatch"})


def test_trust_settings_still_rejects_extra_top_level_keys() -> None:
    """Regression — extra=forbid on TrustSettings is unchanged."""
    with pytest.raises(ValidationError):
        TrustSettings.model_validate({"selfReview": "off", "notARealKey": True})


def test_load_repo_settings_rejects_invalid_agent_sandbox(tmp_path: Path) -> None:
    """A committed ``agentSandbox: off`` aborts loading instead of becoming dispatch."""
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("trust:\n  agentSandbox: off\n", encoding="utf-8")
    with pytest.raises((ValidationError, ValueError)) as exc_info:
        load_repo_settings(root=tmp_path, load_learnings_files=False)
    text = str(exc_info.value).lower()
    for tier in _FOUR_TIERS:
        assert tier in text, f"error does not name tier {tier!r}: {exc_info.value}"
