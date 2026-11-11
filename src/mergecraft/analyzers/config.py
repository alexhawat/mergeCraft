"""Analyzer-specific config helpers (C2 credential verification policy)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from mergecraft.config.layered import load_layered_config_dict

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

TrustTier = Literal["trusted", "untrusted"]

_TRUFFLEHOG_NAMED_FIXTURE_SUPPRESSIONS: dict[str, str] = {
    "tests/analyzers/fixtures/repo/config/planted-secret.env": (
        "Intentional planted-secret fixture for detector wiring"
    ),
    "tests/security/test_credentials.py": (
        "Credential-shaped fixtures used by the credentials test suite"
    ),
    "tests/scripts/test_native_output_to_sarif.py": (
        "Embeds SARIF secret-shaped samples for the native-to-SARIF converter"
    ),
    "tests/analyzers/support.py": ("Planted AWS secret constant shared by the analyzer fixtures"),
    "tests/ci/test_self_review_sarif_extension_w5.py": (
        "Planted secret constant exercising the self-review SARIF extension"
    ),
    "tests/mcp/test_reviewer_resilience_containment.py": (
        "Token-shaped containment fixture for reviewer resilience coverage"
    ),
    "tests/tracing/test_http_spans.py": (
        "API-key sample asserted by the HTTP span redaction tests"
    ),
}
# Finding-level allowlist (#1008): one detector in one file, keyed on
# (repo-relative path, trufflehog DetectorName). Unlike the path-level table
# above, the file stays scanned by every other detector. Keep it in step with
# ``TRUFFLEHOG_ALLOWED_FINDINGS`` in ``scripts/ci_extended_sarif.py`` (a test
# pins the two equal) so the review and the CI emitter allow the same pairs.
_TRUFFLEHOG_ALLOWED_FINDINGS: dict[tuple[str, str], str] = {
    ("tests/tracing/test_redact_url.py", "URI"): (
        "Deliberately fake basic-auth canary used to test URL-userinfo redaction; only the URI detector should match this fixture."
    ),
}
_TRUFFLEHOG_VENV_MARKERS = frozenset({".venv", ".venv-dev", "venv", "site-packages"})


def raw_analyzers_block(repo_root: Path) -> dict[str, Any]:
    """Return the raw ``analyzers`` mapping from repo config, if any."""
    loaded = load_layered_config_dict(root=repo_root)
    analyzers = loaded.get("analyzers")
    return analyzers if isinstance(analyzers, dict) else {}


def trufflehog_verify_enabled(
    *,
    repo_root: Path,
    tier: TrustTier,
) -> bool:
    """Return whether TruffleHog live verification may run (C2 / D7).

    Verification is off by default and impossible on untrusted PRs (fork /
    pull_request_target). Trusted repos must opt in via
    ``analyzers.trufflehog.verify: true``.
    """
    if tier != "trusted":
        return False
    trufflehog = raw_analyzers_block(repo_root).get("trufflehog")
    if isinstance(trufflehog, dict):
        return bool(trufflehog.get("verify"))
    return False


def trufflehog_named_fixture_suppressions() -> Mapping[str, str]:
    """Return path → reason for intentional secret fixtures (not a tests/ glob)."""
    return dict(_TRUFFLEHOG_NAMED_FIXTURE_SUPPRESSIONS)


def trufflehog_allowed_findings() -> Mapping[tuple[str, str], str]:
    """Return (path, detector) → reason for single-detector exemptions (#1008)."""
    return dict(_TRUFFLEHOG_ALLOWED_FINDINGS)


def _normalize_trufflehog_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_trufflehog_path_suppressed(
    path: str,
    *,
    detector: str | None = None,
    repo_root: Path | None = None,
) -> bool:
    """Return True when a trufflehog hit at ``path`` is not reported.

    Suppressed: a named fixture (every detector), a virtualenv tree, or — when
    ``detector`` is given — an exact (path, detector) pair on the finding-level
    allowlist, so the same file is still reported for any other detector.
    Never a blanket ``tests/`` skip.
    """
    from mergecraft.analyzers.parsers._common import resolve_repo_relative_path

    if repo_root is not None:
        normalized = _normalize_trufflehog_path(
            resolve_repo_relative_path(path, repo_root=repo_root)
        )
    else:
        normalized = _normalize_trufflehog_path(path)
    suppressions = trufflehog_named_fixture_suppressions()
    if normalized in suppressions:
        return True
    if detector is not None and (normalized, detector) in _TRUFFLEHOG_ALLOWED_FINDINGS:
        return True
    parts = [part for part in normalized.split("/") if part]
    return bool(_TRUFFLEHOG_VENV_MARKERS.intersection(parts))


__all__ = [
    "is_trufflehog_path_suppressed",
    "raw_analyzers_block",
    "trufflehog_allowed_findings",
    "trufflehog_named_fixture_suppressions",
    "trufflehog_verify_enabled",
]
