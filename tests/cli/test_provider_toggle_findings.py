"""Blocking findings from the mergeCraft review of #521, and their invariants.

Three ways ``provider disable`` could print success while leaving the provider
usable, or act on a repository the operator never named.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_every_registered_provider_has_its_credentials_covered() -> None:
    """No provider may be disabled while one of its credentials survives.

    Parametric over the whole registry rather than a sample: the defect was a
    hand-kept copy drifting from ``PROVIDERS`` on six providers, which no
    fixed list of examples would have caught as the registry grows.
    """
    from mergecraft.cli.provider_toggle import _flat_secret_names
    from mergecraft.models import PROVIDERS

    missing: dict[str, set[str]] = {}
    for label, provider in PROVIDERS.items():
        declared = set(provider.env_vars or ()) | set(provider.managed_credentials or ())
        covered = set(_flat_secret_names(label))
        if declared - covered:
            missing[label] = declared - covered

    assert not missing, f"providers whose credentials survive disable: {missing}"


def test_a_provider_outside_the_registry_is_still_covered() -> None:
    """``cursor`` has no ``PROVIDERS`` row; it must not silently clear nothing."""
    from mergecraft.cli.provider_toggle import _flat_secret_names

    assert _flat_secret_names("cursor") == ("CURSOR_API_KEY",)


def test_an_unknown_provider_clears_nothing() -> None:
    from mergecraft.cli.provider_toggle import _flat_secret_names

    assert _flat_secret_names("not-a-provider") == ()


def test_repo_slug_ignores_an_insteadof_rewrite(tmp_path: Path) -> None:
    """A hostile checkout must not redirect the repository ``gh`` acts on.

    ``resolve_repo_slug`` picks the repository ``gh secret delete`` targets, so
    an ``insteadOf`` rule that rewrites the origin URL would point a
    destructive command at a repository the operator never named. ``git remote
    get-url`` applies those rewrites; reading the stored config key does not.
    """
    from mergecraft.cli.provider_toggle import resolve_repo_slug

    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    run("init")
    run("remote", "add", "origin", "https://github.com/real-owner/real-repo.git")
    run(
        "config",
        "url.https://github.com/attacker/pwned.git.insteadOf",
        "https://github.com/real-owner/real-repo.git",
    )

    # Guard the guard: the rewrite must actually be active in this fixture,
    # or the assertion below would pass against a checkout that proves nothing.
    rewritten = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert "attacker/pwned" in rewritten, rewritten

    assert resolve_repo_slug(repo) == "real-owner/real-repo"


def test_absent_secret_counts_as_deleted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The post-condition is "the secret is not set" — an absent one satisfies it."""
    from mergecraft.cli.tracing_logfire_cmd import _delete_gh_secret

    def fake_run(argv: list[str], **_: Any) -> Any:
        if argv[2] == "delete":
            return subprocess.CompletedProcess(argv, 1, "", "HTTP 404: Not Found")
        return subprocess.CompletedProcess(argv, 0, "OTHER_SECRET\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _delete_gh_secret(name="OPENAI_API_KEY", repo_slug="o/r") is True


def test_unreachable_repository_is_not_reported_as_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repo-level 404 also says "not found"; it must not read as success.

    This is the dangerous direction: the operator is told the provider is
    disabled while every credential is still live.
    """
    from mergecraft.cli.tracing_logfire_cmd import _delete_gh_secret

    def fake_run(argv: list[str], **_: Any) -> Any:
        # Both the delete and the verifying list fail — the repository cannot
        # be seen at all, so nothing can be claimed about the secret.
        return subprocess.CompletedProcess(argv, 1, "", "HTTP 404: Not Found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _delete_gh_secret(name="OPENAI_API_KEY", repo_slug="o/r") is False


def test_a_secret_that_survives_the_delete_is_not_reported_as_deleted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The listing is the evidence: the secret is still there, so report failure."""
    from mergecraft.cli.tracing_logfire_cmd import _delete_gh_secret

    def fake_run(argv: list[str], **_: Any) -> Any:
        if argv[2] == "delete":
            return subprocess.CompletedProcess(argv, 1, "", "HTTP 404: Not Found")
        return subprocess.CompletedProcess(argv, 0, "OPENAI_API_KEY\nOTHER\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _delete_gh_secret(name="OPENAI_API_KEY", repo_slug="o/r") is False


def test_a_successful_delete_needs_no_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard the guard: exit 0 must not depend on a second round trip."""
    from mergecraft.cli.tracing_logfire_cmd import _delete_gh_secret

    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: Any) -> Any:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _delete_gh_secret(name="OPENAI_API_KEY", repo_slug="o/r") is True
    assert len(calls) == 1, calls
