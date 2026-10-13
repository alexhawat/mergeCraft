"""``secret_is_present`` had no caller anywhere; the roster-view helpers stay."""

from __future__ import annotations

from pathlib import Path


def test_secret_is_present_is_gone(tmp_path: Path) -> None:
    """The zero-caller helper is deleted; the read-only roster view still resolves credentials."""
    import mergecraft.cli.provider_status as module
    from mergecraft.config.settings import load_repo_settings

    assert "secret_is_present" not in module.__all__
    assert not hasattr(module, "secret_is_present")
    # Surviving surface: the credential probe still returns a described status.
    settings = load_repo_settings(root=tmp_path)
    status = module.credential_status_for_slug(
        "anthropic/claude-sonnet",
        settings=settings,
        cwd=tmp_path,
        wired=False,
    )
    assert isinstance(status, module.CredentialStatus)
    assert status.looked_for
