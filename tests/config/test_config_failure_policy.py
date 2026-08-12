"""Plan W6.5 — config-failure policy conformance (D4, ``#30``).

D4 splits config surfaces in two:

- **Security/runtime models** (``RepoSettings`` and the nested gates /
  analyzers / tracing blocks): errors fail closed as ``configuration_error``.
- **Optional-feature surfaces**: errors warn + disable that feature.

These tests pin conformance per surface so a surface cannot silently change
classes. The policy doc itself (``CONTRIBUTING.md`` or ``docs/``) is asserted
to exist by the impl wave's own deliverable; the behavioral half lives here.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from mergecraft.config.settings import RepoSettings

# ---------------------------------------------------------------------------
# Hard-fail surfaces (security/runtime) — D4 fail closed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_config",
    [
        {"push": "yolo"},  # not a PushPermission
        {"shell": "everything"},  # not a ShellPermission
    ],
    ids=["bad-push", "bad-shell"],
)
def test_security_surface_enum_errors_fail_closed(bad_config: dict) -> None:
    """D4 baseline — invalid enum values on security fields already raise.

    Pinned plain so a relaxation of the ``Literal`` types turns red today.
    """
    with pytest.raises(ValidationError):
        RepoSettings.model_validate(bad_config)


@pytest.mark.parametrize(
    "bad_config",
    [
        {"gates": {"unknownGate": True}},
        {"analyzers": {"unknownAnalyzerBlock": {}}},
    ],
    ids=["gates-unknown-key", "analyzers-unknown-key"],
)
def test_security_surface_unknown_keys_fail_closed(bad_config: dict) -> None:
    """D4 — unknown keys on nested security blocks must not be ignored."""
    with pytest.raises(ValidationError):
        RepoSettings.model_validate(bad_config)


# ---------------------------------------------------------------------------
# Warn-and-disable surfaces (optional features) — D4: never a hard failure.
# ---------------------------------------------------------------------------


def test_unparseable_config_file_disables_repo_config(tmp_path) -> None:
    """D4 — a syntactically broken config.yaml warns and falls back to defaults.

    Repo-settings *syntax* is the optional-feature surface here: the file may
    not exist or parse; what must fail closed is invalid *security content*
    (covered above).
    """
    from mergecraft.config.settings import default_settings, load_repo_settings

    config_dir = tmp_path / ".mergecraft"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text("push: [not, a, scalar\n", encoding="utf-8")
    settings = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert settings is not None
    assert settings.push == default_settings().push


def test_output_schema_invalid_json_is_rejected() -> None:
    """Baseline — malformed optional-feature input is an error, not a crash."""
    from mergecraft.utils.payload import resolve_output_schema

    with pytest.raises(ValueError, match="invalid output_schema"):
        resolve_output_schema("{not json")


def test_unknown_analyzers_mode_narrows_not_widens() -> None:
    """Convention 5 baseline — ambiguous analyzer input resolves stricter."""
    from mergecraft.analyzers.trust import UNKNOWN_MODE_FALLBACK, resolve_analyzers_mode

    assert resolve_analyzers_mode("turbo-everything") == UNKNOWN_MODE_FALLBACK
    assert resolve_analyzers_mode("") == "auto"
    assert resolve_analyzers_mode(None) == "auto"
