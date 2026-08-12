"""Gate, redact and encode analyzer findings for code-scanning upload (#39).

``export_sarif()`` has existed since the catalog landed, reachable only from
``mergecraft analyzers export --sarif`` — an offline CLI command. Nothing an
Action run enters ever produced a SARIF document, so a consumer whose LLM
narrative was thin, or whose findings overflowed the inline noise budget, had
no mechanical surface to read. This module is everything that has to be true
*before* those findings may leave the process; ``utils/code_scanning.py`` does
the actual POST.

Three properties are load-bearing, in this order (D13, convention 8):

1. **Opt-in.** :func:`resolve_sarif_upload_enabled` defaults to off and treats
   an unrecognised flag value as off. A code-scanning alert is permanent and
   externally visible, so an ambiguous input must never publish one.
2. **Trust-gated.** :func:`select_uploadable_findings` replays the pipeline's
   own tier -> shell -> mode skip chain over each finding's manifest. It is the
   *same* predicates the pipeline calls, not a fourth selection path — a
   divergent copy would drift into publishing findings the run's tier never
   admitted.
3. **Redacted.** :func:`redact_findings_for_upload` runs before serialization,
   not after, so no intermediate the exporter touches ever holds the secret.

Scope is deliberately narrow: only ``source="analyzer"`` findings are
uploadable. ``ci``-sourced findings carry truncated pipeline log excerpts in
``evidence`` (Batch C, ``ci/evidence.py``), and D13 says never upload log
excerpts wholesale; ``agent``-sourced findings are narrative, which is what the
review body is for.

Exports:
    UPLOADABLE_SOURCE: The one ``Finding.source`` this surface publishes.
    build_upload_document: Export findings to SARIF and validate before upload.
    encode_sarif_payload: gzip + base64 a document for the REST field.
    redact_findings_for_upload: Redact every text field a finding can carry.
    resolve_sarif_upload_enabled: Resolve the opt-in flag, failing closed.
    select_uploadable_findings: Apply the trust gate to a finding list.
"""

from __future__ import annotations

import base64
import gzip
import json
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.analyzers.registry import get_manifest
from mergecraft.analyzers.sarif import export_sarif, validate_sarif_document
from mergecraft.analyzers.trust import (
    evaluate_manifest_for_mode,
    evaluate_manifest_for_shell,
    evaluate_manifest_for_tier,
    resolve_effective_analyzers_mode,
    resolve_selection_tier,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from mergecraft.analyzers.finding import Finding
    from mergecraft.analyzers.manifest import TrustTier
    from mergecraft.analyzers.trust import AnalyzersMode

UPLOADABLE_SOURCE: Final[str] = "analyzer"
"""The only ``Finding.source`` this surface publishes (#39, D13)."""

_ENABLED_VALUES: Final[frozenset[str]] = frozenset({"enabled"})
_DISABLED_VALUES: Final[frozenset[str]] = frozenset({"disabled"})


def resolve_sarif_upload_enabled(*, action_input: str | None, repo_setting: bool) -> bool:
    """Resolve the opt-in SARIF upload flag (D13, convention 5).

    An *absent* input is not a decision — it defers to
    ``.mergecraft/config.yaml``'s ``analyzers.sarifUpload``, which itself
    defaults to ``False``. A *present* input is a decision and wins in both
    directions, so an operator can turn the upload off on one workflow without
    editing repo config.

    An input that is present but unrecognised is ambiguous, and ambiguity
    resolves to the more restrictive outcome — off — with a warning. Reading a
    typo as "enabled" would publish findings to a permanent, externally visible
    surface that nobody asked for.
    """
    value = (action_input or "").strip().lower()
    if not value:
        return repo_setting
    if value in _ENABLED_VALUES:
        return True
    if value in _DISABLED_VALUES:
        return False
    logger.warning(
        "unrecognised sarif_upload input {!r}; SARIF upload stays off "
        "(valid values: disabled, enabled)",
        action_input,
    )
    return False


def _selection_admits(
    finding: Finding, *, tier: TrustTier, shell: str, mode: AnalyzersMode
) -> bool:
    """Whether manifest selection admits this finding's analyzer at this run's axes.

    Deliberately re-derived from the manifest rather than trusted from the
    recorded run: the finding rows are stored as plain dicts on ``ToolState``
    and are replaced wholesale on every ``run_analyzers`` call, so a row can
    outlive the selection that produced it. Re-asking the predicates costs
    nothing and closes that window.

    A ``tool`` with no catalog manifest cannot be gated at all, so it is
    refused — an ungatable finding is exactly the one that must not be
    published.
    """
    try:
        manifest = get_manifest(finding.tool)
    except KeyError:
        logger.debug(
            "sarif upload: dropping finding from unknown analyzer {!r}",
            finding.tool,
        )
        return False

    effective = resolve_effective_analyzers_mode(mode=mode, tier=tier)
    selection_tier = resolve_selection_tier(mode=effective, tier=tier)
    return not (
        evaluate_manifest_for_tier(manifest=manifest, tier=selection_tier).skipped
        or evaluate_manifest_for_shell(manifest=manifest, shell=shell).skipped
        or evaluate_manifest_for_mode(manifest=manifest, mode=effective).skipped
    )


def select_uploadable_findings(
    findings: Sequence[Finding],
    *,
    tier: TrustTier,
    shell: str,
    mode: AnalyzersMode,
) -> list[Finding]:
    """Return the findings this run is permitted to publish (D13).

    Two filters, both narrowing:

    * **Source.** #39 scopes the surface to catalog analyzers. ``ci`` findings
      carry log excerpts and ``agent`` findings carry narrative; neither
      belongs in a code-scanning alert.
    * **Selection.** The finding's analyzer must still pass the pipeline's own
      tier -> shell -> mode chain, evaluated with this run's axes.
    """
    selected: list[Finding] = []
    for finding in findings:
        if finding.source != UPLOADABLE_SOURCE:
            continue
        if not _selection_admits(finding, tier=tier, shell=shell, mode=mode):
            continue
        selected.append(finding)
    return selected


def _redact_optional(value: str | None) -> str | None:
    return None if value is None else redact_secrets(value)


def redact_findings_for_upload(findings: Sequence[Finding]) -> list[Finding]:
    """Redact every free-text field a finding carries, before serialization.

    Runs on the typed ``Finding`` set rather than on the encoded blob so no
    intermediate the exporter touches holds the secret — redacting after
    serialization would leave it in the document, in any log line that echoed
    the document, and in whatever the exporter cached.

    ``path`` is deliberately *not* redacted. It is a repo-relative file path
    the analyzer parsers derive against the repo root, not a secret channel,
    and it becomes ``artifactLocation.uri``: a mangled path silently detaches
    the alert from its file, which is a worse outcome than the risk it would
    buy. ``tool`` and ``rule_id`` come from mergeCraft's own manifests, and
    ``fingerprint`` is already computed over redacted material
    (``redact_for_fingerprint``).

    Returns new ``Finding`` instances — the one finding model, never extended
    (D12).
    """
    redacted: list[Finding] = []
    for finding in findings:
        redacted.append(
            finding.model_copy(
                update={
                    "message": redact_secrets(finding.message),
                    "evidence": [redact_secrets(line) for line in finding.evidence],
                    "remediation": _redact_optional(finding.remediation),
                    "autofix": _redact_optional(finding.autofix),
                }
            )
        )
    return redacted


def build_upload_document(findings: Sequence[Finding]) -> dict[str, Any]:
    """Export findings as SARIF 2.1.0 and validate before anything is uploaded.

    Validation is not decoration: GitHub rejects a malformed document with an
    opaque 4xx, and a document that *is* accepted but wrong publishes wrong
    alerts. Raising here keeps a bad document off the wire; the caller turns
    that into a logged refusal rather than a failed run (W8.5).
    """
    document = export_sarif(list(findings))
    validate_sarif_document(document)
    return document


def encode_sarif_payload(document: Mapping[str, Any]) -> str:
    """Encode a SARIF document for the ``sarif`` REST field: gzip, then base64.

    ``mtime=0`` keeps the gzip header byte-identical for identical input, so
    re-running a review on the same commit produces the same payload instead of
    a timestamp-only diff.
    """
    raw = json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return base64.b64encode(gzip.compress(raw, mtime=0)).decode("ascii")


__all__ = [
    "UPLOADABLE_SOURCE",
    "build_upload_document",
    "encode_sarif_payload",
    "redact_findings_for_upload",
    "resolve_sarif_upload_enabled",
    "select_uploadable_findings",
]
