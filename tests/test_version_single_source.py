"""``mergecraft.__version__`` must track the distribution version.

The number was restated as a literal in ``mergecraft/__init__.py`` and drifted:
``pyproject.toml`` moved to ``0.1.0a1`` while the literal stayed at ``0.1.0``,
so ``mergecraft --version`` under-reported the release. It also keys the offline
result cache and is stamped on telemetry and eval reproducibility pins, so the
two disagreeing quietly mixes artefacts across builds.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import mergecraft

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _declared_version() -> str:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    version = data["project"]["version"]
    assert isinstance(version, str)
    return version


def test_version_matches_pyproject() -> None:
    assert mergecraft.__version__ == _declared_version()


def test_version_is_resolved_not_a_placeholder() -> None:
    """A missing distribution must not pass as a real version."""
    assert mergecraft.__version__ != "0.0.0+unknown", (
        "no installed `merge-craft` distribution — run `make install` "
        "(a placeholder version would poison cache keys and telemetry)"
    )


def test_real_version_passes_the_payload_compatibility_gate() -> None:
    """The shipped version must survive `validate_compatibility` (#430 review).

    `validate_compatibility` parsed both sides as strict SemVer, so a PEP 440
    pre-release like `0.1.0a1` raised. Every `~mergecraft` JSON payload calls it
    with the package version, so this was a runtime regression on any
    pre-release build, not just a test failure.
    """
    from mergecraft.utils.payload import validate_compatibility

    validate_compatibility(mergecraft.__version__, mergecraft.__version__)


def test_pep440_prerelease_is_compatible_with_its_release() -> None:
    """`0.1.0a1` and `0.1.0` agree on major/minor, which is what the policy compares."""
    from mergecraft.utils.payload import validate_compatibility

    validate_compatibility("0.1.0", "0.1.0a1")
    validate_compatibility("0.1.0-a1", "0.1.0a1")


def test_unparseable_action_version_names_the_action() -> None:
    """A bad action version must not be reported as a bad payload version."""
    import pytest

    from mergecraft.utils.payload import validate_compatibility

    with pytest.raises(ValueError, match="Action version"):
        validate_compatibility("0.1.0", "not-a-version")


def test_resolve_prompt_input_accepts_a_payload_at_the_real_version() -> None:
    """End-to-end: a JSON payload stamped with the shipped version resolves."""
    import json

    from mergecraft.utils.payload import JsonPayload, validate_compatibility

    raw = json.dumps(
        {"~mergecraft": True, "version": mergecraft.__version__, "prompt": "review this"}
    )
    payload = JsonPayload.model_validate_json(raw)
    validate_compatibility(payload.version, mergecraft.__version__)
    assert payload.prompt == "review this"
