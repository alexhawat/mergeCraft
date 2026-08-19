"""Opt-in upload of analyzer findings to GitHub code scanning (#39).

Why code scanning rather than check-run annotations (W8.3, one primary surface
chosen deliberately):

* ``export_sarif()`` already produces exactly the artifact code scanning
  consumes. Annotations would need a second serializer with its own severity
  mapping and its own truncation rules, for a surface that largely repeats the
  inline review comments mergeCraft already posts — the "no duplicate spam"
  criterion D14 exists to protect.
* Code-scanning alerts survive the review thread. #39's premise is a consumer
  whose LLM narrative was thin or whose findings overflowed the inline budget;
  an annotation set attached to one check run is a worse home for that than an
  alert list GitHub dedupes by fingerprint across pushes.
* The failure mode is single and legible. Code scanning answers one POST with
  one status: 403 without ``security-events: write``, 404 on a repo without
  Advanced Security. Annotations fail per-check-run and partially — GitHub caps
  them at 50 per request — and a partial failure is much harder to report
  honestly than a refused upload.

Check-run annotations remain the documented optional second surface; nothing
here forecloses them, and ``utils/status_checks.py`` already owns the
check-run creation shape they would reuse.

Nothing in this module may fail a run. SARIF is complementary evidence, never
the gate (W8.5): every failure path logs at ``warning`` and returns ``None``.

Exports:
    CODE_SCANNING_PATH: REST path template for the SARIF upload endpoint.
    report_sarif_upload: Upload this run's analyzer findings, if opted in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.sarif_upload import (
    build_upload_document,
    encode_sarif_payload,
    redact_findings_for_upload,
    select_uploadable_findings,
)

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.mcp.context import ToolContext

CODE_SCANNING_PATH = "/repos/{owner}/{repo}/code-scanning/sarifs"


def _typed_analyzer_findings(ctx: ToolContext) -> list[Finding]:
    """Read the run's stored analyzer findings back into typed ``Finding`` rows.

    ``AnalyzerRunState.findings`` holds the *clustered* set the pipeline placed
    (``pipeline.py`` serializes ``cluster_findings(...)`` output), so reading it
    is what makes the upload the clustered, budgeted set rather than the raw one
    (D14). Nothing is re-clustered here.

    A row that fails validation is dropped with a debug line, matching
    ``utils/status_checks.py``: a malformed analyzer row must not crash the run.
    """
    run_state = getattr(ctx.tool_state, "analyzer_run", None)
    if run_state is None:
        return []
    rows = list(getattr(run_state, "findings", []) or [])
    if not rows:
        return []

    from mergecraft.analyzers.finding import Finding, FindingValidationError

    typed: list[Finding] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            typed.append(Finding.model_validate(row))
        except FindingValidationError as err:
            logger.debug("sarif upload: dropping malformed finding row: {}", err)
    return typed


async def _resolve_pr_head_sha(ctx: ToolContext, pull_number: int) -> str | None:
    try:
        pull = await ctx.scm.get_pull(ctx.repo.owner, ctx.repo.name, pull_number)
    except Exception as err:
        logger.debug("sarif upload: failed to resolve PR #{} head sha: {}", pull_number, err)
        return None
    head_sha = str(pull.get("head", {}).get("sha") or "")
    return head_sha or None


async def report_sarif_upload(ctx: ToolContext) -> str | None:
    """Upload this run's analyzer findings to code scanning when opted in.

    Returns the upload's ``id`` when GitHub accepted it, and ``None`` on every
    other path — disabled, no pull request, nothing uploadable, an invalid
    document, or a rejected POST. Never raises.

    The order of the guards is the contract: the flag is checked before any
    work at all, so a repo that did not opt in makes **no request** rather than
    building a document and discarding the reply (D13).
    """
    if not ctx.sarif_upload_enabled:
        return None

    event = ctx.payload.event
    pull_number = event.issue_number
    if event.is_pr is not True or not isinstance(pull_number, int):
        logger.debug("sarif upload: no pull request on this event — nothing to attach results to")
        return None

    findings = _typed_analyzer_findings(ctx)
    if not findings:
        logger.debug("sarif upload: the run recorded no analyzer findings")
        return None

    selected = select_uploadable_findings(
        findings,
        tier=ctx.trust_tier,
        shell=str(ctx.payload.shell),
        mode=ctx.analyzers_mode,
    )
    if not selected:
        logger.info(
            "» sarif upload: no findings passed the trust gate ({} of {} eligible)",
            0,
            len(findings),
        )
        return None

    redacted = redact_findings_for_upload(selected)
    try:
        document = build_upload_document(redacted)
    except Exception as err:
        logger.warning("sarif upload: refusing to upload an invalid SARIF document: {}", err)
        return None

    head_sha = await _resolve_pr_head_sha(ctx, pull_number)
    if not head_sha:
        return None

    body: dict[str, Any] = {
        "commit_sha": head_sha,
        "ref": f"refs/pull/{pull_number}/head",
        "sarif": encode_sarif_payload(document),
        "tool_name": "mergecraft",
    }
    if ctx.run_id:
        body["checkout_uri"] = (
            f"https://github.com/{ctx.repo.owner}/{ctx.repo.name}/actions/runs/{ctx.run_id}"
        )

    path = CODE_SCANNING_PATH.format(owner=ctx.repo.owner, repo=ctx.repo.name)
    try:
        response = await ctx.scm.post(path, json=body)
    except Exception as err:
        # 403 without `security-events: write` and 404 on a repo without code
        # scanning are the *expected* answers for most consumers. Failing the
        # run on either would turn an opt-in complementary surface into a merge
        # blocker (W8.5).
        logger.warning(
            "sarif upload: code scanning rejected {} finding(s) on {}: {}",
            len(redacted),
            head_sha[:7],
            err,
        )
        return None

    upload_id = str(response.get("id") or "") if isinstance(response, dict) else ""
    logger.info(
        "» uploaded {} analyzer finding(s) to code scanning on {}",
        len(redacted),
        head_sha[:7],
    )
    return upload_id or None


__all__ = ["CODE_SCANNING_PATH", "report_sarif_upload"]
