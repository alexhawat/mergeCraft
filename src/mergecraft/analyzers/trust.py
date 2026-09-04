"""Trust-tier derivation and analyzer environment policy (D7)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime by ReviewSource / build_review_source
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.utils.secrets import filter_env, is_sensitive_env_name
from mergecraft.utils.source_resolve import is_registered_git_worktree, resolve_git_common_dir

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import AnalyzerManifest, TrustTier
    from mergecraft.mcp.context import ToolContext

AnalyzersMode = Literal["off", "auto", "full", "untrusted-only"]

ReviewSourceKind = Literal["local_cwd", "local_path", "local_worktree", "cloned_remote"]

#: Every value the ``analyzers:`` Action input accepts.
ANALYZERS_MODES: frozenset[str] = frozenset({"off", "auto", "full", "untrusted-only"})

#: Where an unrecognised ``analyzers:`` value lands. Convention 5 — an ambiguous
#: input resolves to the *more restrictive* outcome, never the wider one. It is
#: deliberately not ``off``: a typo should narrow coverage, not delete it.
UNKNOWN_MODE_FALLBACK: AnalyzersMode = "untrusted-only"

#: Runtimes whose argv comes verbatim from a mergeCraft-shipped manifest and is
#: therefore safe to run when the working tree is PR-authored (#35, D5).
#: ``repo-native`` is excluded because it resolves against repo-provided
#: binaries and repo-provided config — see :func:`allow_repo_provided_binaries`.
SHELL_DISABLED_ELIGIBLE_RUNTIMES: frozenset[str] = frozenset({"managed", "container"})

#: Analyzers that declare ``runtime: repo-native`` but need no repo-provided
#: tooling at all: ``resolve_analyzer()`` special-cases them before the
#: repo-binary preference is ever consulted, and ``run_adapter()`` executes them
#: in-process — no subprocess, no argv, nothing the PR authored is run.
#:
#: The runtime axis exists to answer "could PR content steer what executes?".
#: For these the answer is no, so withholding them buys no safety and costs a
#: hardened consumer real coverage (#38). ``agentsec`` is mergeCraft's own
#: agent-security policy engine and is exactly the signal a ``pull_request_target``
#: consumer wants most; it reads PR-authored manifests as *data*, which every
#: other part of a review already does.
#:
#: Kept as a narrow, named exception rather than a new ``RuntimeMode`` value,
#: because convention 6 / D6 forbid widening the taxonomy. A drift guard in
#: ``tests/analyzers/test_trust_aware_analyzer_mode.py`` asserts each id here
#: really does resolve without repo-provided tooling.
IN_PROCESS_ANALYZER_IDS: frozenset[str] = frozenset({"agentsec", "antislop"})

IN_PROCESS_VERSION_NOTES: dict[str, str] = {
    "agentsec": "ran mergeCraft native agent-security policy engine",
    "antislop": "ran mergeCraft native anti-slop policy engine",
}

IN_PROCESS_CONFIG_NOTE = "native YAML rules"


@dataclass(frozen=True, slots=True)
class ManifestTierDecision:
    skipped: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReviewSource:
    """Provenance descriptor for a CLI-supplied review source (TS1 / D2)."""

    kind: ReviewSourceKind
    path: Path
    invocation_root: Path


def build_review_source(
    *,
    cwd: Path,
    invocation_root: Path,
    cloned: bool = False,
) -> ReviewSource:
    """Construct a :class:`ReviewSource` from a review cwd and invocation root.

    D10 / #294: when *cwd* is a linked git worktree of the same repo as
    *invocation_root* (same ``git rev-parse --git-common-dir``), the kind is
    ``"local_worktree"`` and :func:`derive_source_trust_tier` maps it to
    ``"trusted"``.  Clones (``cloned=True``), unrelated repos, and non-git
    paths fall back to ``"cloned_remote"`` / ``"local_path"`` as before.
    """
    resolved_cwd = cwd.resolve()
    resolved_root = invocation_root.resolve()
    if cloned:
        return ReviewSource(
            kind="cloned_remote",
            path=resolved_cwd,
            invocation_root=resolved_root,
        )
    if resolved_cwd == resolved_root:
        return ReviewSource(
            kind="local_cwd",
            path=resolved_cwd,
            invocation_root=resolved_root,
        )
    # D10 / #294: detect a linked worktree of the same repo.
    cwd_common = resolve_git_common_dir(resolved_cwd)
    root_common = resolve_git_common_dir(resolved_root)
    if (
        cwd_common is not None
        and root_common is not None
        and cwd_common == root_common
        and is_registered_git_worktree(resolved_cwd)
    ):
        return ReviewSource(
            kind="local_worktree",
            path=resolved_cwd,
            invocation_root=resolved_root,
        )
    return ReviewSource(
        kind="local_path",
        path=resolved_cwd,
        invocation_root=resolved_root,
    )


def derive_source_trust_tier(
    source: object | None,
    *,
    trust_override: TrustTier | None = None,
) -> TrustTier:
    """Derive trust tier for a CLI-supplied review source from provenance (TS1 / D2).

    Unlike :func:`derive_trust_tier`, this never inspects GitHub event payloads.
    An explicit ``trust_override`` (``--trust`` on the CLI, D3) wins and is
    logged at warning. Unknown source shapes fail closed to ``untrusted``.
    """
    if trust_override is not None:
        logger.warning(
            "operator trust override applied: tier={!r} (--trust; explicit only, never from repo config)",
            trust_override,
        )
        return trust_override

    if not isinstance(source, ReviewSource):
        return "untrusted"

    if source.kind == "cloned_remote":
        return "untrusted"

    # D10 / #294: linked worktrees of the same repo are trusted without --trust.
    if source.kind == "local_worktree":
        return "trusted"

    try:
        source.path.resolve().relative_to(source.invocation_root.resolve())
    except ValueError:
        return "untrusted"

    return "trusted"


def _event_name() -> str:
    return os.environ.get("GITHUB_EVENT_NAME", "")


def derive_trust_tier(
    event: dict[str, Any] | None = None,
    *,
    shell: str = "restricted",
    offline: bool = False,
    event_name: str | None = None,
) -> TrustTier:
    """Derive trust tier from the native GitHub event shape (W0.4 probe).

    ``event_name`` overrides the ambient ``GITHUB_EVENT_NAME``. A caller that
    already knows which event it is reasoning about must pass it, so the tier
    and any event-name-dependent decision beside it cannot disagree: resolving
    one from an argument and the other from the environment produced a
    ``trusted`` posture for a ``pull_request_target`` run whenever the two
    differed. ``None`` keeps the ambient lookup for callers inside a real run.
    """
    _ = shell
    if offline:
        return "trusted"
    if not event:
        return "untrusted"

    resolved_event_name = _event_name() if event_name is None else event_name
    if resolved_event_name == "workflow_dispatch":
        return "trusted"
    if resolved_event_name == "pull_request_target":
        return "untrusted"

    if resolved_event_name == "pull_request":
        pull_request = event.get("pull_request")
        if isinstance(pull_request, dict):
            head = pull_request.get("head")
            if isinstance(head, dict):
                repo = head.get("repo")
                if isinstance(repo, dict) and repo.get("fork") is False:
                    return "trusted"
        return "untrusted"

    if resolved_event_name == "issue_comment":
        # ``resolve_native_event`` already authorises comment-driven runs by
        # author association (OWNER / MEMBER / COLLABORATOR).  Mirror that
        # gate here so a maintainer's ``issue_comment`` earns the trusted tier
        # (setup_script, secrets, approve tool) rather than falling through
        # to the fail-closed ``untrusted`` default.
        comment = event.get("comment")
        if isinstance(comment, dict):
            association = comment.get("author_association", "")
            if isinstance(association, str) and association in {"OWNER", "MEMBER", "COLLABORATOR"}:
                return "trusted"
        return "untrusted"

    # Fail closed (#144): an unrecognised event shape is more restricted, never
    # more permissive. Convention 5 / D7 — matches ``UNKNOWN_MODE_FALLBACK``
    # above. Comment / schedule / workflow_call / workflow_run / merge_group /
    # push / release / empty ``GITHUB_EVENT_NAME`` all land here and resolve to
    # ``untrusted``. The events with explicit branches — ``workflow_dispatch``
    # (trusted), ``pull_request_target`` (untrusted), and same-repo
    # ``pull_request`` (trusted via the gated branch above) — never fall
    # through to this default.
    return "untrusted"


def build_analyzer_env(
    *,
    tier: TrustTier,
    repo_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build analyzer subprocess env; untrusted tier strips secrets (D7)."""
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
    manifest: AnalyzerManifest,
    tier_or_ctx: TrustTier | ToolContext | None = None,
    *,
    tier: TrustTier | None = None,
    cause: str = "fork PR / pull_request_target",
) -> ManifestTierDecision:
    """Skip trusted-only manifests on untrusted runs (D7).

    ``cause`` names *why* the run is being evaluated at this tier so the reason
    string stays true when the tier was chosen by the operator rather than
    derived from the event — ``analyzers: untrusted-only`` on a same-repo PR
    is a real untrusted selection, but it is not a fork (D9, #38).

    The second positional argument may be a :class:`~mergecraft.mcp.context.ToolContext`
    — execution trust is read from ``ctx.trust_tier``.
    """
    from mergecraft.mcp.context import ToolContext

    resolved_tier: TrustTier
    if isinstance(tier_or_ctx, ToolContext):
        resolved_tier = tier_or_ctx.trust_tier
    elif tier_or_ctx is not None:
        resolved_tier = tier_or_ctx
    elif tier is not None:
        resolved_tier = tier
    else:
        msg = "evaluate_manifest_for_tier requires tier or ToolContext"
        raise TypeError(msg)

    if resolved_tier == "untrusted" and manifest.trust == "trusted":
        reason = f"skipped {manifest.id}: requires trusted tier ({cause})"
        logger.info("{}", reason)
        return ManifestTierDecision(skipped=True, reason=reason)
    return ManifestTierDecision(skipped=False)


def _needs_repo_provided_tooling(manifest: AnalyzerManifest) -> bool:
    """Whether running this manifest means running something the repo supplies."""
    if manifest.id in IN_PROCESS_ANALYZER_IDS:
        return False
    return manifest.runtime not in SHELL_DISABLED_ELIGIBLE_RUNTIMES


def _withhold_for_repo_tooling(manifest: AnalyzerManifest, *, because: str) -> ManifestTierDecision:
    """The one skip row the runtime axis produces, whichever gate asked for it."""
    reason = (
        f"skipped {manifest.id}: runtime {manifest.runtime!r} needs repo-provided tooling, "
        f"withheld under {because}"
    )
    logger.info("{}", reason)
    return ManifestTierDecision(skipped=True, reason=reason)


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
    if not _needs_repo_provided_tooling(manifest):
        return ManifestTierDecision(skipped=False)
    return _withhold_for_repo_tooling(manifest, because="shell: disabled")


def evaluate_manifest_for_mode(
    *,
    manifest: AnalyzerManifest,
    mode: AnalyzersMode,
) -> ManifestTierDecision:
    """Apply the ``analyzers:`` mode's own runtime gate (#38, D8).

    ``untrusted-only`` means what #38 asks for: run only analyzers safe without
    secrets, without network, and without PR-authored command construction. The
    tier half of that is :func:`evaluate_manifest_for_tier` driven by
    :func:`resolve_selection_tier`; this is the runtime half, and it is what
    makes the mode more than a relabelling — it withholds repo-native manifests
    even when the shell is merely ``restricted``, which the tier axis alone
    does not do.

    Inert for every other mode, and returns the same
    :class:`ManifestTierDecision` the other two predicates return (D9).
    """
    if mode != "untrusted-only":
        return ManifestTierDecision(skipped=False)
    if not _needs_repo_provided_tooling(manifest):
        return ManifestTierDecision(skipped=False)
    return _withhold_for_repo_tooling(manifest, because="analyzers: untrusted-only")


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
    """Resolve the ``analyzers:`` Action input to a mode.

    An *absent* input is not ambiguous — it is the documented ``auto`` default.
    An input that is present but unrecognised is ambiguous, and convention 5
    resolves ambiguity to the more restrictive outcome: it lands on
    ``untrusted-only`` rather than silently buying the wider ``auto``
    selection, and it says so at ``warning`` level. Before #38 every typo
    resolved to ``auto`` with no diagnostic, which under ``pull_request_target``
    is exactly the permissive reading this issue exists to close.
    """
    value = (raw or "").strip().lower()
    if not value:
        return "auto"
    if value in ANALYZERS_MODES:
        return value  # type: ignore[return-value]  # — value verified against ANALYZERS_MODES above
    logger.warning(
        "unrecognised analyzers input {!r}; falling back to the more restrictive {!r} "
        "(valid values: {})",
        raw,
        UNKNOWN_MODE_FALLBACK,
        ", ".join(sorted(ANALYZERS_MODES)),
    )
    return UNKNOWN_MODE_FALLBACK


def resolve_effective_analyzers_mode(*, mode: AnalyzersMode, tier: TrustTier) -> AnalyzersMode:
    """Apply D8: ``auto`` means trust-aware selection on an untrusted run.

    Keyed on the tier :func:`derive_trust_tier` already produced rather than on
    ``GITHUB_EVENT_NAME``, so the event shape is parsed in exactly one place
    (W4.2). That also means fork-head ``pull_request`` runs — untrusted for the
    same reason ``pull_request_target`` is — get the same treatment, which is
    the safer reading of D8 rather than a wider one.
    """
    if mode == "auto" and tier == "untrusted":
        return "untrusted-only"
    return mode


def resolve_selection_tier(*, mode: AnalyzersMode, tier: TrustTier) -> TrustTier:
    """The tier manifest *selection* is evaluated at.

    Only ever equal to or stricter than the derived tier: ``untrusted-only``
    forces an untrusted selection on an otherwise-trusted run, and no mode can
    turn an untrusted run into a trusted selection. In particular ``full`` is a
    request to provision more tooling, never a trust override.

    The *execution* tier is untouched — ``build_analyzer_env()`` and
    ``allow_repo_command_overrides()`` keep reading the derived tier, so this
    can narrow what runs but never widen what a run is allowed to see.
    """
    if tier == "untrusted" or mode == "untrusted-only":
        return "untrusted"
    return tier


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
    "ANALYZERS_MODES",
    "IN_PROCESS_ANALYZER_IDS",
    "SHELL_DISABLED_ELIGIBLE_RUNTIMES",
    "UNKNOWN_MODE_FALLBACK",
    "AnalyzersMode",
    "ManifestTierDecision",
    "ReviewSource",
    "ReviewSourceKind",
    "allow_repo_command_overrides",
    "allow_repo_provided_binaries",
    "analyzers_enabled",
    "build_analyzer_env",
    "build_review_source",
    "derive_source_trust_tier",
    "derive_trust_tier",
    "evaluate_manifest_for_mode",
    "evaluate_manifest_for_shell",
    "evaluate_manifest_for_tier",
    "resolve_analyzers_mode",
    "resolve_effective_analyzers_mode",
    "resolve_selection_tier",
]
