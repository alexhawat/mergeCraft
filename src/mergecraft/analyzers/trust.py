"""Trust-tier derivation and analyzer environment policy (D7)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.utils.secrets import filter_env, is_sensitive_env_name

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import AnalyzerManifest, TrustTier
    from mergecraft.mcp.context import ToolContext

AnalyzersMode = Literal["off", "auto", "full"]

#: Runtimes whose argv comes verbatim from a mergeCraft-shipped manifest and is
#: therefore safe to run when the working tree is PR-authored (#35, D5).
#: ``repo-native`` is excluded because it resolves against repo-provided
#: binaries and repo-provided config — see :func:`allow_repo_provided_binaries`.
SHELL_DISABLED_ELIGIBLE_RUNTIMES: frozenset[str] = frozenset({"managed", "container"})


@dataclass(frozen=True, slots=True)
class ManifestTierDecision:
    skipped: bool
    reason: str | None = None


def _event_name() -> str:
    return os.environ.get("GITHUB_EVENT_NAME", "")


def derive_trust_tier(
    event: dict[str, Any] | None = None,
    *,
    shell: str = "restricted",
    offline: bool = False,
) -> TrustTier:
    """Derive trust tier from the native GitHub event shape (W0.4 probe)."""
    _ = shell
    if offline:
        return "trusted"
    if not event:
        return "untrusted"

    event_name = _event_name()
    if event_name == "workflow_dispatch":
        return "trusted"
    if event_name == "pull_request_target":
        return "untrusted"

    pull_request = event.get("pull_request")
    if isinstance(pull_request, dict):
        head = pull_request.get("head")
        if isinstance(head, dict):
            repo = head.get("repo")
            if isinstance(repo, dict) and repo.get("fork") is True:
                return "untrusted"
        return "trusted"

    return "trusted"


def build_analyzer_env(
    *,
    event: dict[str, Any] | None,
    tier: TrustTier,
    repo_env: dict[str, str] | None = None,
    network_allowlist: list[str] | None = None,
) -> dict[str, str]:
    """Build analyzer subprocess env; untrusted tier strips secrets (D7)."""
    _ = event, network_allowlist
    base = dict(repo_env or os.environ)
    if tier == "trusted":
        return filter_env(base)

    scrubbed: dict[str, str] = {}
    for key, value in base.items():
        if is_sensitive_env_name(key):
            continue
        if key in {"GITHUB_TOKEN", "GH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}:
            continue
        scrubbed[key] = value
    return filter_env(scrubbed)


def evaluate_manifest_for_tier(
    *,
    manifest: AnalyzerManifest,
    tier: TrustTier,
) -> ManifestTierDecision:
    """Skip trusted-only manifests on untrusted runs (D7)."""
    if tier == "untrusted" and manifest.trust == "trusted":
        reason = f"skipped {manifest.id}: requires trusted tier (fork PR / pull_request_target)"
        logger.info("{}", reason)
        return ManifestTierDecision(skipped=True, reason=reason)
    return ManifestTierDecision(skipped=False)


def evaluate_manifest_for_shell(
    *,
    manifest: AnalyzerManifest,
    shell: str,
) -> ManifestTierDecision:
    """Select manifests eligible to run when the shell is disabled (#35, D5).

    ``shell: disabled`` says "do not execute anything this PR could have
    written". That rules out ``runtime: repo-native`` manifests, whose whole
    contract is to run the *repo's* pinned tool against the *repo's* config.
    It does not rule out ``managed`` / ``container`` manifests, whose argv is
    copied verbatim out of a manifest mergeCraft ships — which is the coverage
    hardened consumers were losing.

    Off the ``disabled`` path this predicate is inert, so the tier axis
    (:func:`evaluate_manifest_for_tier`) keeps deciding alone.

    Returns the same :class:`ManifestTierDecision` shape the tier predicate
    returns, so skips render through one code path with a named reason (D9).
    """
    if shell != "disabled":
        return ManifestTierDecision(skipped=False)
    if manifest.runtime in SHELL_DISABLED_ELIGIBLE_RUNTIMES:
        return ManifestTierDecision(skipped=False)
    reason = (
        f"skipped {manifest.id}: runtime {manifest.runtime!r} needs repo-provided tooling, "
        "withheld under shell: disabled"
    )
    logger.info("{}", reason)
    return ManifestTierDecision(skipped=True, reason=reason)


def allow_repo_provided_binaries(*, shell: str) -> bool:
    """Whether a repo-provided binary may stand in for a pinned one (#35, D5).

    ``resolve_analyzer()`` prefers ``<repo>/.venv/bin/<tool>``,
    ``<repo>/node_modules/.bin/<tool>`` and friends over mergeCraft's pinned
    managed binary for *every* manifest, regardless of declared ``runtime``.
    That preference is what makes an otherwise-safe ``managed`` analyzer
    steerable by PR content, so under ``shell: disabled`` it is refused and
    only the pinned binary may run — D5's "constructs no PR-authored command".
    """
    return shell != "disabled"


def allow_repo_command_overrides(tier: TrustTier) -> bool:
    """Untrusted runs never execute PR-authored command construction (D7)."""
    return tier == "trusted"


def resolve_analyzers_mode(raw: str | None) -> AnalyzersMode:
    value = (raw or "auto").strip().lower()
    if value in {"off", "auto", "full"}:
        return value  # type: ignore[return-value]
    return "auto"


def analyzers_enabled(ctx: ToolContext) -> bool:
    """Whether the analyzer MCP surface may register for this run.

    Until #35 this also returned ``False`` for every real PR event whenever
    ``shell: disabled``, which withheld mergeCraft's own pinned catalog
    alongside the repo-declared ``staticChecks`` it was meant to withhold — so
    a repo that hardened correctly got no mechanical coverage at all.

    The two questions are now answered separately. Registration is no longer
    keyed on the shell; per-manifest eligibility under ``shell: disabled`` is
    :func:`evaluate_manifest_for_shell`, and ``run_static_checks`` keeps its
    own unconditional withhold via ``ctx.static_checks_enabled`` (D7).
    """
    if ctx.analyzers_mode == "off":
        return False
    return bool(ctx.analyzers_settings_enabled)


__all__ = [
    "SHELL_DISABLED_ELIGIBLE_RUNTIMES",
    "AnalyzersMode",
    "ManifestTierDecision",
    "allow_repo_command_overrides",
    "allow_repo_provided_binaries",
    "analyzers_enabled",
    "build_analyzer_env",
    "derive_trust_tier",
    "evaluate_manifest_for_shell",
    "evaluate_manifest_for_tier",
    "resolve_analyzers_mode",
]
