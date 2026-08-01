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


def allow_repo_command_overrides(tier: TrustTier) -> bool:
    """Untrusted runs never execute PR-authored command construction (D7)."""
    return tier == "trusted"


def resolve_analyzers_mode(raw: str | None) -> AnalyzersMode:
    value = (raw or "auto").strip().lower()
    if value in {"off", "auto", "full"}:
        return value  # type: ignore[return-value]
    return "auto"


def analyzers_enabled(ctx: ToolContext) -> bool:
    """Whether the analyzer MCP surface may register for this run."""
    if ctx.analyzers_mode == "off":
        return False
    if not ctx.analyzers_settings_enabled:
        return False
    if ctx.payload.shell == "disabled":
        # Offline diff-review: operator-owned tree — analyzers still run (W7.8).
        return ctx.payload.event.trigger == "unknown"
    return True


__all__ = [
    "AnalyzersMode",
    "ManifestTierDecision",
    "allow_repo_command_overrides",
    "analyzers_enabled",
    "build_analyzer_env",
    "derive_trust_tier",
    "evaluate_manifest_for_tier",
    "resolve_analyzers_mode",
]
