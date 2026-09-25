"""Run reproduce / verify against an injected browser driver.

This module never imports a browser automation library. Tests inject
``FakeBrowserDriver``; the CLI uses ``--allow-stub`` or
``mergecraft.browser.launch_browser_driver``.

Criterion and repro scoring go through ``mergecraft.verify.jev_seam`` when a
``jev_client`` is supplied: Jev judges each criterion and the repro claim, and
this module maps the categorical verdicts onto report statuses in Python. With
no client the module keeps its local text heuristic, which is what unit tests
drive.

Exports:
    collect_skip_reasons: Trust, shell, and enabled:false skip list.
    run_verify_behavior: Trusted-tier gate, process lifecycle, report write.
    write_skipped_report: Named skip report when the run could not start.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.verify.artifacts import redact_screenshot
from mergecraft.verify.jev_seam import judge_criteria, judge_repro_claim
from mergecraft.verify.models import (
    BlockedDetails,
    CriterionResult,
    CriterionStatus,
    DriverKind,
    InteractionAction,
    ReportArtifacts,
    ReportStatus,
    VerificationInput,
    VerificationReport,
    VerificationStep,
)

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings
    from mergecraft.jev.client import AsyncJevClient
    from mergecraft.verify.driver import BrowserDriver

_MAX_LOG_CHARS = 4000
_STARTUP_SETTLE_S = 0.15
_NAVIGATE_RETRY_S = 0.25
_NAVIGATE_READY_S = 15.0
_REAP_WAIT_S = 3.0
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_TYPE_ACTION_TARGET = "<focused element>"
#: Negation cues matched on the raw lowercased criterion *before* tokenising, so
#: ``no`` (dropped by the length filter) and ``not`` (a stopword) still count.
_NEGATION_CUE_RE = re.compile(r"\b(?:no|not|never|none|nothing|without|cannot)\b|n't")


class ActionStepFailure(Exception):
    """Partial action steps were recorded before an interaction failed."""

    def __init__(self, steps: list[VerificationStep], cause: BaseException) -> None:
        self.steps = steps
        super().__init__(str(cause))
        self.__cause__ = cause


_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "to",
        "of",
        "in",
        "on",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "then",
        "when",
        "does",
        "must",
        "should",
        "will",
        "not",
        "are",
        "was",
        "is",
        "be",
        "it",
        "as",
        "at",
        "by",
    }
)


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _redact_truncate(text: str) -> str:
    redacted = redact_secrets(text)
    if len(redacted) <= _MAX_LOG_CHARS:
        return redacted
    return redacted[:_MAX_LOG_CHARS] + "\n…truncated\n"


def _effective_shell(shell: str | None, settings: RepoSettings | None) -> str | None:
    if shell is not None:
        return shell
    if settings is not None:
        return settings.shell
    return None


def _empty_artifacts() -> ReportArtifacts:
    return ReportArtifacts(screenshots=[], logs=[], video=None, trace=None, network_summary=None)


def _build_report(
    spec: VerificationInput,
    *,
    status: ReportStatus,
    steps: list[VerificationStep] | None = None,
    criteria: list[CriterionResult] | None = None,
    observed: str = "",
    expected: str = "",
    observed_mismatches: list[str] | None = None,
    skipped_or_unverified: list[str] | None = None,
    artifacts: ReportArtifacts | None = None,
    console_errors: list[str] | None = None,
    application_logs: list[str] | None = None,
    suggested_next_fix: str = "",
    blocked: BlockedDetails | None = None,
    driver: DriverKind | None = None,
    credential_names: list[str] | None = None,
) -> VerificationReport:
    return VerificationReport(
        schema_version="1.0.0",
        mode=spec.mode,
        target=spec.issue_or_pr or spec.base_url,
        target_url=spec.base_url,
        status=status,
        steps=steps or [],
        acceptance_criteria=criteria or [],
        observed=_redact_truncate(observed),
        expected=_redact_truncate(expected),
        observed_mismatches=[_redact_truncate(item) for item in (observed_mismatches or [])],
        skipped_or_unverified=list(skipped_or_unverified or []),
        artifacts=artifacts or _empty_artifacts(),
        console_errors=[_redact_truncate(item) for item in (console_errors or [])],
        application_logs=[_redact_truncate(item) for item in (application_logs or [])],
        suggested_next_fix=_redact_truncate(suggested_next_fix),
        blocked=blocked,
        timestamp=_now(),
        credential_names=list(credential_names or []),
        driver=driver,
    )


def _write_artifacts(dest: Path, report: VerificationReport, log_text: str) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    report_path = dest / "report.json"
    report_path.write_text(redact_secrets(report.model_dump_json()), encoding="utf-8")
    if log_text:
        log_path = dest / "console.log"
        log_path.write_text(_redact_truncate(log_text), encoding="utf-8")


async def _start_app(command: str) -> asyncio.subprocess.Process:
    argv = shlex.split(command)
    logger.debug("verify-behavior starting app argv_len={}", len(argv))
    return await asyncio.create_subprocess_exec(
        *argv,
        start_new_session=True,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def _reap(proc: asyncio.subprocess.Process | None) -> None:
    if proc is None or proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=_REAP_WAIT_S)
    except TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        await proc.wait()


def _missing_env_credentials(spec: VerificationInput) -> list[str]:
    if spec.auth.strategy != "env":
        return []
    return [name for name in spec.credential_env_names if not os.environ.get(name)]


def _screenshots_allowed(spec: VerificationInput) -> bool:
    """Return whether a post-run screenshot may be persisted.

    Pixel redaction is not implemented yet. YAML ``auth.strategy`` is not a
    reliable boundary — a ``mock`` spec can still run against an authenticated
    CDP session or fill credentials via actions — so screenshots stay off until
    ``redact_screenshot`` can rewrite pixels in place.
    """
    _ = spec
    return False


def collect_skip_reasons(
    *,
    event: dict[str, Any] | None = None,
    event_name: str | None = None,
    shell: str | None = None,
    settings: RepoSettings | None = None,
    offline: bool = False,
) -> list[str]:
    """Return skip reasons that must run before a browser or start-command.

    Args:
        event (dict[str, Any] | None): GitHub event payload.
        event_name (str | None): Event name for ``derive_trust_tier``.
        shell (str | None): Effective ``shell`` permission.
        settings (RepoSettings | None): Repo config; ``enabled: false`` skips.
        offline (bool): Local operator machine; skip the Actions trust gate.

    Returns:
        list[str]: Empty when the run may proceed.

    Examples:
        >>> collect_skip_reasons(offline=True)
        []
    """
    skipped: list[str] = []
    if not offline:
        tier = derive_trust_tier(event, event_name=event_name)
        if tier == "untrusted":
            skipped.append("untrusted: behaviour verification is trusted-tier only")
    effective_shell = _effective_shell(shell, settings)
    if effective_shell == "disabled":
        skipped.append("shell disabled: behaviour verification does not run when shell is disabled")
    if settings is not None and settings.verify_behavior.enabled is False:
        skipped.append("verify_behavior.enabled is false")
    return skipped


def _significant_tokens(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    ]


def _page_matches_expected(expected: str, page: str) -> bool:
    tokens = _significant_tokens(expected)
    if not tokens:
        return bool(page.strip())
    lowered = page.lower()
    return all(token in lowered for token in tokens)


def _has_negation_cue(text: str) -> bool:
    """Return whether ``text`` carries a negation cue.

    Matched on the raw lowercased text before tokenising, so ``no`` (dropped by
    the length filter) and ``not`` (a stopword) still count. Token absence is not
    evidence of truth: the local heuristic must not pass a negated criterion it
    cannot judge.
    """
    return _NEGATION_CUE_RE.search(text.lower()) is not None


def _is_transient_nav_error(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError | OSError):
        return True
    text = str(exc).lower()
    needles = (
        "econnrefused",
        "connection refused",
        "err_connection_refused",
        "net::err_connection_refused",
    )
    return any(needle in text for needle in needles)


async def _navigate_until_ready(driver: BrowserDriver, url: str, *, wait: bool) -> None:
    if not wait:
        await driver.navigate(url)
        return
    deadline = time.monotonic() + _NAVIGATE_READY_S
    while True:
        try:
            await driver.navigate(url)
            return
        except ConnectionRefusedError as exc:
            if time.monotonic() >= deadline:
                raise
            logger.debug("verify-behavior waiting for app after {}", type(exc).__name__)
            await asyncio.sleep(_NAVIGATE_RETRY_S)
        except ConnectionError:
            raise
        except (OSError, TimeoutError) as exc:
            if time.monotonic() >= deadline:
                raise
            logger.debug("verify-behavior waiting for app after {}", type(exc).__name__)
            await asyncio.sleep(_NAVIGATE_RETRY_S)
        except Exception as exc:
            if not _is_transient_nav_error(exc) or time.monotonic() >= deadline:
                raise
            logger.debug("verify-behavior waiting for app after {}", type(exc).__name__)
            await asyncio.sleep(_NAVIGATE_RETRY_S)


async def _apply_actions(
    driver: BrowserDriver, actions: list[InteractionAction]
) -> list[VerificationStep]:
    recorded: list[VerificationStep] = []
    for item in actions:
        target = _TYPE_ACTION_TARGET if item.action == "type" else item.selector
        try:
            if item.action == "click":
                await driver.click(item.selector)
            elif item.action == "fill":
                await driver.fill(item.selector, item.text)
            else:
                await driver.type_text(item.text)
        except (ConnectionError, OSError, TimeoutError, RuntimeError) as exc:
            recorded.append(
                VerificationStep(action=item.action, target=target, result=f"error: {exc}")
            )
            raise ActionStepFailure(recorded, exc) from exc
        recorded.append(VerificationStep(action=item.action, target=target, result="ok"))
    return recorded


def _criterion_status(
    text: str, page: str, evidence: list[str]
) -> tuple[CriterionResult, str | None]:
    """Score one criterion locally, and name a negated one it cannot judge.

    Returns:
        tuple[CriterionResult, str | None]: The per-criterion result and, when a
        negation cue makes the criterion un-judgeable, the named reason to
        record on ``skipped_or_unverified``.
    """
    lowered = page.lower()
    criterion = text.lower()
    status: CriterionStatus
    reason: str | None = None
    if not page.strip():
        status = "unverified"
    elif "still visible" in criterion:
        status = "fail" if "still visible" in lowered else "pass"
    elif "mismatch" in criterion:
        status = "fail" if "mismatch" in lowered else "pass"
    elif _has_negation_cue(text):
        # Fail closed (P-6): the heuristic must not pass a negation it cannot
        # judge, and it names why (P-8).
        status = "unverified"
        reason = _negation_unverified_reason("criterion", text)
    elif _page_matches_expected(text, page):
        status = "pass"
    else:
        status = "fail"
    result = CriterionResult(
        id=text[:48] or "criterion",
        text=text,
        status=status,
        evidence=list(evidence),
    )
    return result, reason


async def _score_criteria(
    spec: VerificationInput,
    page: str,
    jev_client: AsyncJevClient | None,
    evidence: list[str],
) -> tuple[list[CriterionResult], list[str]]:
    """Score each criterion via the Jev seam, or locally when no client is bound.

    Returns:
        tuple[list[CriterionResult], list[str]]: Per-criterion results and the
        named skip reasons for criteria that were not judged — Jev
        ``unverified`` verdicts, or a local negation cue. Callers own the
        pass/fail/partial aggregation.
    """
    results: list[CriterionResult] = []
    unverified: list[str] = []
    if jev_client is None:
        for text in spec.acceptance_criteria:
            result, reason = _criterion_status(text, page, evidence)
            results.append(result)
            if reason is not None:
                unverified.append(reason)
        return results, unverified
    judgments = await judge_criteria(spec.acceptance_criteria, page_text=page, client=jev_client)
    for judgment in judgments:
        if judgment.verdict == "unverified":
            unverified.append(_unverified_reason("criterion", judgment.criterion, judgment.reason))
        results.append(
            CriterionResult(
                id=judgment.criterion[:48] or "criterion",
                text=judgment.criterion,
                status=judgment.verdict,
                evidence=list(evidence),
            )
        )
    return results, unverified


def _unverified_reason(kind: str, subject: str, reason: str) -> str:
    """Name a judgment that did not happen so it never reads as 'found nothing'."""
    return f"{kind} unverified: {subject} ({reason or 'unavailable'})"


def _negation_unverified_reason(kind: str, subject: str) -> str:
    """Name a negated criterion the local heuristic must not judge as a pass."""
    return _unverified_reason(
        kind,
        subject,
        "negation cue: local heuristic cannot verify a negated criterion",
    )


def write_skipped_report(spec: VerificationInput, *, reason: str) -> VerificationReport:
    """Write a report that names why the run did not happen. Never a pass.

    Args:
        spec (VerificationInput): The requested run.
        reason (str): Named skip reason recorded on ``skipped_or_unverified``.

    Returns:
        VerificationReport: ``skipped`` for verify, ``partial`` for reproduce —
        never ``pass`` / ``reproduced``. Written to ``spec.artifacts_dir`` when set.

    Examples:
        >>> import inspect
        >>> inspect.isfunction(write_skipped_report)
        True
    """
    status: ReportStatus = "skipped" if spec.mode == "verify" else "partial"
    report = _build_report(spec, status=status, skipped_or_unverified=[reason])
    if spec.artifacts_dir:
        _write_artifacts(Path(spec.artifacts_dir), report, "")
    return report


async def run_verify_behavior(
    spec: VerificationInput,
    *,
    driver: BrowserDriver | None = None,
    driver_kind: DriverKind | None = None,
    jev_client: AsyncJevClient | None = None,
    event: dict[str, Any] | None = None,
    event_name: str | None = None,
    shell: str | None = None,
    settings: RepoSettings | None = None,
    offline: bool = False,
) -> VerificationReport:
    """Reproduce or verify behaviour. Trusted-tier only; always reaps the app.

    Args:
        spec (VerificationInput): Union input from issues 61, 62, and 63.
        driver (BrowserDriver | None, optional): Injected protocol. Tests pass
            a fake; the CLI binds browser-use or ``--allow-stub``.
        driver_kind (DriverKind | None, optional): Which driver produced the run
            (``"cdp"`` or ``"stub"``), stamped on the report. ``None`` when not
            recorded — a library caller that injected a driver, or a run that
            produced no report.
        jev_client (AsyncJevClient | None, optional): Pinned Jev client. When
            supplied, criteria and the repro claim are scored by the seam; when
            omitted, the local text heuristic is used.
        event (dict[str, Any] | None, optional): GitHub event payload.
        event_name (str | None, optional): Event name for ``derive_trust_tier``.
        shell (str | None, optional): Effective ``shell`` permission.
        settings (RepoSettings | None, optional): Repo config. ``enabled: false``
            skips the run; ``enabled: true`` cannot override an untrusted tier.
        offline (bool, optional): Local/trusted CLI. Not skipped for trust.

    Returns:
        VerificationReport: Versioned report. ``blocked.missing`` names gaps.

    Examples:
        >>> import inspect
        >>> inspect.iscoroutinefunction(run_verify_behavior)
        True
    """
    skipped = collect_skip_reasons(
        event=event,
        event_name=event_name,
        shell=shell,
        settings=settings,
        offline=offline,
    )
    if skipped:
        logger.info("verify-behavior skipped reasons={}", skipped)
        report = _build_report(
            spec, status="skipped", skipped_or_unverified=skipped, driver=driver_kind
        )
        untrusted_skip = any(item.startswith("untrusted:") for item in skipped)
        if spec.artifacts_dir and not untrusted_skip:
            _write_artifacts(Path(spec.artifacts_dir), report, "")
        return report

    missing_creds = _missing_env_credentials(spec)
    if missing_creds:
        report = _build_report(
            spec,
            status="blocked",
            blocked=BlockedDetails(missing=missing_creds),
            skipped_or_unverified=[],
            driver=driver_kind,
        )
        if spec.artifacts_dir:
            _write_artifacts(Path(spec.artifacts_dir), report, "")
        return report

    credential_names = list(spec.credential_env_names)
    proc: asyncio.subprocess.Process | None = None
    log_text = ""
    screenshots: list[str] = []
    logs: list[str] = []
    try:
        if spec.startup_command.strip():
            proc = await _start_app(spec.startup_command)
            await asyncio.sleep(_STARTUP_SETTLE_S)

        if driver is None:
            report = _build_report(
                spec,
                status="blocked",
                blocked=BlockedDetails(missing=["browser driver"]),
                credential_names=credential_names,
                driver=driver_kind,
            )
            if spec.artifacts_dir:
                _write_artifacts(Path(spec.artifacts_dir), report, "")
            return report

        try:
            await _navigate_until_ready(
                driver,
                spec.base_url,
                wait=bool(spec.startup_command.strip()),
            )
        except (ConnectionError, OSError, TimeoutError) as exc:
            logger.info("verify-behavior blocked unreachable url={}", spec.base_url)
            named = spec.base_url or str(exc)
            report = _build_report(
                spec,
                status="blocked",
                steps=[
                    VerificationStep(action="navigate", target=spec.base_url, result="unreachable")
                ],
                blocked=BlockedDetails(missing=[named]),
                credential_names=credential_names,
                driver=driver_kind,
            )
            if spec.artifacts_dir:
                _write_artifacts(Path(spec.artifacts_dir), report, "")
            return report

        try:
            action_steps = await _apply_actions(driver, spec.actions)
        except ActionStepFailure as exc:
            failed = exc.steps[-1]
            label = f"{failed.action}:{failed.target}"
            logger.info(
                "verify-behavior blocked action={} target={}",
                failed.action,
                failed.target,
            )
            steps = [
                VerificationStep(action="navigate", target=spec.base_url, result="loaded"),
                *exc.steps,
            ]
            report = _build_report(
                spec,
                status="blocked",
                steps=steps,
                blocked=BlockedDetails(missing=[label]),
                credential_names=credential_names,
                driver=driver_kind,
            )
            if spec.artifacts_dir:
                _write_artifacts(Path(spec.artifacts_dir), report, "")
            return report

        page = await driver.extract_text()
        if spec.artifacts_dir and _screenshots_allowed(spec):
            dest_dir = Path(spec.artifacts_dir)
            shot_dest = dest_dir / "screenshot.png"
            shot = await driver.screenshot(shot_dest)
            shot = redact_screenshot(shot)
            screenshots.append(str(shot))

        rows = await driver.console_messages()
        log_parts = [_redact_truncate(str(row.get("text", ""))) for row in rows]
        log_text = "\n".join(log_parts)
        console_errors = [part for part in log_parts if part]
        if spec.artifacts_dir and log_text:
            log_path = Path(spec.artifacts_dir) / "console.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(_redact_truncate(log_text), encoding="utf-8")
            logs.append(str(log_path))

        steps = [
            VerificationStep(action="navigate", target=spec.base_url, result="loaded"),
            *action_steps,
        ]
        artifacts = ReportArtifacts(
            screenshots=screenshots,
            logs=logs,
            video=None,
            trace=None,
            network_summary=None,
        )
        criteria, skipped_criteria = await _score_criteria(spec, page, jev_client, screenshots)

        if spec.mode == "reproduce":
            expected = spec.repro_notes or (
                spec.acceptance_criteria[0] if spec.acceptance_criteria else "expected behaviour"
            )
            observed = page or "no page text"
            status: ReportStatus
            if jev_client is None:
                if _has_negation_cue(expected):
                    # Fail closed (P-6): a negated expectation is never a
                    # reproduction on the opposite page.
                    status = "partial"
                    skipped_criteria.append(_negation_unverified_reason("repro", expected))
                else:
                    status = (
                        "reproduced" if _page_matches_expected(expected, page) else "not_reproduced"
                    )
            else:
                repro = await judge_repro_claim(expected, page_text=page, client=jev_client)
                if repro.verdict == "unverified":
                    status = "partial"
                    skipped_criteria.append(_unverified_reason("repro", expected, repro.reason))
                else:
                    status = repro.verdict
            report = _build_report(
                spec,
                status=status,
                steps=steps,
                criteria=criteria,
                observed=observed,
                expected=expected,
                skipped_or_unverified=skipped_criteria,
                artifacts=artifacts,
                console_errors=console_errors,
                credential_names=credential_names,
                driver=driver_kind,
            )
        else:
            if not criteria:
                verify_status: ReportStatus = "partial"
                skipped_criteria.append("no acceptance criteria")
            else:
                statuses = {item.status for item in criteria}
                if statuses == {"pass"}:
                    verify_status = "pass"
                elif statuses == {"fail"}:
                    verify_status = "fail"
                else:
                    verify_status = "partial"
            report = _build_report(
                spec,
                status=verify_status,
                steps=steps,
                criteria=criteria,
                observed=page,
                expected="; ".join(spec.acceptance_criteria),
                skipped_or_unverified=skipped_criteria,
                artifacts=artifacts,
                console_errors=console_errors,
                credential_names=credential_names,
                driver=driver_kind,
            )
        if spec.artifacts_dir:
            _write_artifacts(Path(spec.artifacts_dir), report, log_text)
        return report
    finally:
        await _reap(proc)
