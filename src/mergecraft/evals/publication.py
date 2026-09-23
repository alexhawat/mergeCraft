"""Keyless validation and publication of bounded two-provider campaigns."""

import hashlib
import json
import math
import re
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mergecraft.evals.benchmark import SCORER_VERSION, BenchmarkResultSet, DetectionCaseResult
from mergecraft.evals.judge_calibration import (
    JudgeCalibrationReport,
    calibration_report_sha256,
    threshold_results_for_metrics,
)
from mergecraft.evals.scoring import (
    fold_score_reports,
    load_baseline_issues,
    load_reported_findings,
    score_findings,
)

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class CampaignCase(BaseModel):
    """One independently adjudicated patch-bearing case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    patch_path: str
    patch_sha256: str = Field(pattern=_SHA256_PATTERN)
    baseline_path: str
    baseline_sha256: str = Field(pattern=_SHA256_PATTERN)
    closed_world: bool
    label_status: Literal["independently_adjudicated"]

    @model_validator(mode="after")
    def _paths_are_relative(self) -> Self:
        for value in (self.patch_path, self.baseline_path):
            path = Path(value)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("campaign artifact paths must be confined relative paths")
        if not self.case_id.strip():
            raise ValueError("case_id must not be empty")
        return self


class DetectionLabelCasePin(BaseModel):
    """Human-reviewed interpretation of one exact patch/baseline pair."""

    model_config = ConfigDict(extra="forbid")

    patch_sha256: str = Field(pattern=_SHA256_PATTERN)
    baseline_sha256: str = Field(pattern=_SHA256_PATTERN)
    closed_world: bool


class DetectionLabelReceipt(BaseModel):
    """Independent decision that the exact campaign case hashes are eligible."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    corpus_commit: str = Field(pattern=_COMMIT_PATTERN)
    case_hashes: dict[str, DetectionLabelCasePin]
    label_status: Literal["independently_adjudicated"]
    adjudicator_login: str
    adjudicated_at: datetime

    @model_validator(mode="after")
    def _complete_receipt(self) -> Self:
        if not self.case_hashes or not self.adjudicator_login.strip():
            raise ValueError("label receipt requires cases and an adjudicator identity")
        return self


class BenchmarkCampaignManifest(BaseModel):
    """Frozen operator-owned inputs and budget for one no-retry campaign."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    campaign_id: str
    corpus_commit: str = Field(pattern=_COMMIT_PATTERN)
    cases: list[CampaignCase]
    detection_label_receipt_path: str
    detection_label_receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    judge_calibration_receipt_path: str
    judge_calibration_receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    models: list[str]
    model_pins: dict[str, str]
    per_review_timeout_seconds: int = Field(gt=0)
    per_review_token_limit: int = Field(gt=0)
    per_review_cost_budget_usd: float = Field(gt=0.0, allow_inf_nan=False)
    retry_limit: Literal[0]
    expected_case_count: int = Field(gt=0)
    total_campaign_spend_ceiling_usd: float = Field(gt=0.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _validate_campaign(self) -> Self:
        if _SAFE_ID_RE.fullmatch(self.campaign_id) is None:
            raise ValueError("campaign_id must be one safe path component")
        if len(self.models) != 2 or len(set(self.models)) != 2:
            raise ValueError("campaign requires exactly two distinct model slugs")
        providers: list[str] = []
        for model in self.models:
            provider, separator, model_id = model.partition("/")
            if not separator or not provider or not model_id:
                raise ValueError("campaign models must be full provider/model slugs")
            providers.append(provider)
        if len(set(providers)) != 2:
            raise ValueError("campaign models must use two distinct providers")
        if set(self.model_pins) != set(self.models) or any(
            not pin.strip() for pin in self.model_pins.values()
        ):
            raise ValueError("model_pins must provide an immutable identity for each model")
        if any(self.model_pins[model] != model for model in self.models):
            raise ValueError(
                "each requested model slug must directly name its declared immutable pin"
            )
        case_ids = [case.case_id for case in self.cases]
        if not case_ids or len(case_ids) != len(set(case_ids)):
            raise ValueError("campaign cases must be non-empty with unique IDs")
        if self.expected_case_count != len(self.cases):
            raise ValueError("expected_case_count must equal the frozen case count")
        for value in (
            self.detection_label_receipt_path,
            self.judge_calibration_receipt_path,
        ):
            path = Path(value)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("receipt paths must be confined relative paths")
        if self.reserved_spend_usd > self.total_campaign_spend_ceiling_usd:
            raise ValueError("conservative campaign reservation exceeds the spend ceiling")
        return self

    @property
    def reserved_spend_usd(self) -> float:
        """Worst-case reservation for exactly two no-retry provider runs."""
        return len(self.models) * self.expected_case_count * self.per_review_cost_budget_usd


class ArtifactDigest(BaseModel):
    """One raw findings artifact retained by the report."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = Field(pattern=_SHA256_PATTERN)


class InputResultArtifact(BaseModel):
    """One exact result set consumed by publication."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = Field(pattern=_SHA256_PATTERN)


class PublishedProviderMetrics(BaseModel):
    """Recomputed metrics for one provider; providers are never averaged."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    immutable_model_pin: str
    cases_run: int
    cases_failed: int
    failed_case_ids: list[str]
    expected_case_count: int
    total_issues: int
    total_reported: int
    found: int
    recall: float
    recall_interval_95: tuple[float, float] | None
    corpus_confirmed_precision: float
    corpus_confirmed_precision_interval_95: tuple[float, float] | None
    corpus_confirmed_f1: float
    unadjudicated: int
    false_positives: int
    false_positives_per_case: float
    clean_case_fp_rate: float
    closed_world_case_count: int
    strict_precision: float | None
    latency_p50_seconds: float
    latency_p95_seconds: float
    cost_known: bool
    cost_usd: float | None
    configured_per_review_cost_budget_usd: float
    raw_artifacts: list[ArtifactDigest]
    mergecraft_commit: str
    mergecraft_version: str
    rubric_version: str
    corpus_commit: str


class BenchmarkPublicationSummary(BaseModel):
    """Machine-readable output of the keyless publication validator."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = "1.0.0"
    campaign_id: str
    generated_at: datetime
    manifest_sha256: str = Field(pattern=_SHA256_PATTERN)
    detection_label_receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    judge_calibration_receipt_sha256: str = Field(pattern=_SHA256_PATTERN)
    manifest_path: str
    input_results: list[InputResultArtifact]
    judge_candidate_id: str
    judge_prompt_sha256: str = Field(pattern=_SHA256_PATTERN)
    judge_pins: dict[str, dict[str, object]]
    mode_prompt_versions: dict[str, str]
    rubric_version: str
    scorer_version: str
    line_slack: int
    conservative_reserved_spend_usd: float
    total_campaign_spend_ceiling_usd: float
    providers: list[PublishedProviderMetrics]
    limitations: list[str]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_verified(root: Path, relative: str, expected_hash: str) -> Path:
    """Resolve a regular non-symlink artifact below ``root`` and verify it."""
    if root.is_symlink():
        raise ValueError("manifest directory must not be a symlink")
    candidate = root / relative
    current = candidate
    while current != root and current != current.parent:
        if current.is_symlink():
            raise ValueError(f"publication artifact must not be a symlink: {relative}")
        current = current.parent
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
        raise ValueError(f"publication artifact is missing or escapes manifest root: {relative}")
    if _sha256(resolved) != expected_hash:
        raise ValueError(f"publication artifact hash drift: {relative}")
    return resolved


def _wilson(successes: int, total: int) -> tuple[float, float] | None:
    if total == 0:
        return None
    z = 1.959963984540054
    estimate = successes / total
    denominator = 1 + z * z / total
    centre = (estimate + z * z / (2 * total)) / denominator
    margin = (
        z * math.sqrt(estimate * (1 - estimate) / total + z * z / (4 * total * total)) / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    rank = fraction * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def _validate_label_receipt(
    manifest: BenchmarkCampaignManifest,
    receipt: DetectionLabelReceipt,
) -> None:
    if receipt.corpus_commit != manifest.corpus_commit:
        raise ValueError("detection-label receipt corpus commit mismatch")
    expected = {
        case.case_id: DetectionLabelCasePin(
            patch_sha256=case.patch_sha256,
            baseline_sha256=case.baseline_sha256,
            closed_world=case.closed_world,
        )
        for case in manifest.cases
    }
    if receipt.case_hashes != expected:
        raise ValueError("detection-label receipt case hashes do not match the manifest")


def validate_campaign_artifacts(
    manifest: BenchmarkCampaignManifest,
    *,
    manifest_root: Path,
) -> JudgeCalibrationReport:
    """Verify current corpus artifacts and both prerequisite receipts."""
    for case in manifest.cases:
        _resolve_verified(manifest_root, case.patch_path, case.patch_sha256)
        _resolve_verified(manifest_root, case.baseline_path, case.baseline_sha256)
    label_path = _resolve_verified(
        manifest_root,
        manifest.detection_label_receipt_path,
        manifest.detection_label_receipt_sha256,
    )
    receipt = DetectionLabelReceipt.model_validate_json(label_path.read_text(encoding="utf-8"))
    _validate_label_receipt(manifest, receipt)
    judge_path = _resolve_verified(
        manifest_root,
        manifest.judge_calibration_receipt_path,
        manifest.judge_calibration_receipt_sha256,
    )
    judge = JudgeCalibrationReport.model_validate_json(judge_path.read_text(encoding="utf-8"))
    expected_calibration_results = threshold_results_for_metrics(
        judge.calibration.metrics, judge.acceptance_contract
    )
    expected_held_out_results = (
        threshold_results_for_metrics(judge.held_out.metrics, judge.acceptance_contract)
        if judge.held_out is not None
        else None
    )
    if (
        judge.state != "validated"
        or judge.seal_sha256 is None
        or judge.sealed_by is None
        or judge.sealed_at is None
        or not judge.calibration.passed
        or judge.held_out is None
        or not judge.held_out.passed
        or judge.calibration.threshold_results != expected_calibration_results
        or judge.held_out.threshold_results != expected_held_out_results
        or not all(expected_calibration_results.values())
        or expected_held_out_results is None
        or not all(expected_held_out_results.values())
        or judge.calibration_report_sha256 != calibration_report_sha256(judge.calibration)
    ):
        raise ValueError("judge-calibration receipt is not a complete passing validation")
    return judge


def _validate_case_result(
    row: DetectionCaseResult,
    case: CampaignCase,
    *,
    raw_root: Path,
) -> ArtifactDigest:
    receipt = row.execution_receipt
    if receipt is None:
        raise ValueError(f"case {row.case_id} has no versioned execution receipt")
    if receipt.patch_sha256 != case.patch_sha256:
        raise ValueError(f"case {row.case_id} executed patch hash does not match manifest")
    if receipt.baseline_sha256 != case.baseline_sha256:
        raise ValueError(f"case {row.case_id} executed baseline hash does not match manifest")
    raw_path = Path(receipt.raw_findings_path)
    if raw_root.is_symlink() or raw_path.is_symlink() or not raw_path.is_file():
        raise ValueError(f"case {row.case_id} raw findings artifact is missing")
    raw_root_absolute = raw_root.absolute()
    current = raw_path.absolute()
    while current != raw_root_absolute and current != current.parent:
        if current.is_symlink():
            raise ValueError(f"case {row.case_id} raw findings path contains a symlink")
        current = current.parent
    if not raw_path.resolve().is_relative_to(raw_root.resolve()):
        raise ValueError(f"case {row.case_id} raw findings path escapes its run directory")
    if _sha256(raw_path) != receipt.raw_findings_sha256:
        raise ValueError(f"case {row.case_id} raw findings hash drift")
    return ArtifactDigest(path=str(raw_path), sha256=receipt.raw_findings_sha256)


def _provider_metrics(
    manifest: BenchmarkCampaignManifest,
    result: BenchmarkResultSet,
    expected_model: str,
    *,
    manifest_root: Path,
) -> PublishedProviderMetrics:
    detection = result.detection
    if detection is None or result.skipped_reason is not None:
        raise ValueError(f"result for {expected_model} has no completed detection run")
    expected_provider = expected_model.split("/", 1)[0]
    if detection.model != expected_model or detection.provider != expected_provider:
        raise ValueError(f"result identity does not match manifest model {expected_model}")
    if result.pins.corpus_commit != manifest.corpus_commit:
        raise ValueError(f"result corpus commit mismatch for {expected_model}")
    identity = detection.execution_identity
    if identity is None or not identity.fully_pinned:
        raise ValueError(f"result has no immutable detection execution identity: {expected_model}")
    if (
        identity.provider != expected_provider
        or identity.requested_model != expected_model
        or identity.executed_model != expected_model
        or identity.immutable_model_pin != expected_model
        or identity.pin_provenance != "operator-declared"
    ):
        raise ValueError(f"detection execution identity does not match manifest: {expected_model}")
    if detection.calibration is None or not detection.calibration.eligible:
        raise ValueError(f"result labels are ineligible for comparative claims: {expected_model}")
    if (
        detection.cases_run != manifest.expected_case_count
        or detection.cases_failed != 0
        or detection.failed_case_ids
    ):
        raise ValueError(f"result is partial or failed for {expected_model}")
    rows = {row.case_id: row for row in detection.case_results}
    expected_cases = {case.case_id: case for case in manifest.cases}
    if len(rows) != len(detection.case_results) or set(rows) != set(expected_cases):
        raise ValueError(f"result case set does not match manifest for {expected_model}")

    raw_artifacts: list[ArtifactDigest] = []
    reports = []
    for case_id, case in sorted(expected_cases.items()):
        row = rows[case_id]
        raw_artifact = _validate_case_result(row, case, raw_root=Path(detection.raw_findings_dir))
        baseline_path = _resolve_verified(manifest_root, case.baseline_path, case.baseline_sha256)
        raw_payload = json.loads(Path(raw_artifact.path).read_text(encoding="utf-8"))
        baseline_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        report = score_findings(
            load_baseline_issues(baseline_payload),
            load_reported_findings(raw_payload),
            closed_world=case.closed_world,
            slack=result.pins.line_slack,
        )
        expected_values: tuple[tuple[str, int | float | bool | None], ...] = (
            ("closed_world", case.closed_world),
            ("total_issues", report.total_issues),
            ("total_reported", report.total_reported),
            ("found", report.found),
            ("recall", report.recall),
            ("corpus_confirmed_precision", report.corpus_confirmed_precision),
            ("f1", report.f1),
            ("strict_precision", report.strict_precision if case.closed_world else None),
        )
        for field, expected in expected_values:
            actual = getattr(row, field)
            if isinstance(expected, float):
                agrees = isinstance(actual, (int, float)) and math.isclose(
                    float(actual), expected, rel_tol=1e-12, abs_tol=1e-12
                )
            else:
                agrees = actual == expected
            if not agrees:
                raise ValueError(f"case {case_id} saved {field} does not match recomputed score")
        raw_artifacts.append(raw_artifact)
        reports.append(report)
    receipts = [rows[case_id].execution_receipt for case_id in sorted(rows)]
    if any(receipt is None for receipt in receipts):
        raise ValueError("missing execution receipt")
    complete_receipts = [receipt for receipt in receipts if receipt is not None]
    aggregate = fold_score_reports(reports)
    saved_aggregate = detection.aggregate
    aggregate_fields = (
        "total_cases",
        "total_issues",
        "total_reported",
        "found",
        "false_negatives",
        "unadjudicated",
        "false_positives",
        "false_positives_per_case",
        "clean_case_fp_rate",
    )
    if any(
        getattr(saved_aggregate, field) != getattr(aggregate, field) for field in aggregate_fields
    ):
        raise ValueError(f"saved aggregate does not match raw recomputation: {expected_model}")
    total_issues = aggregate.total_issues
    total_reported = aggregate.total_reported
    found = aggregate.found
    recall = aggregate.recall
    precision = aggregate.corpus_confirmed_precision
    f1 = aggregate.f1
    closed_reports = [report for report in reports if report.closed_world]
    closed_found = sum(report.found for report in closed_reports)
    closed_reported = sum(report.total_reported for report in closed_reports)
    strict_precision = (
        (closed_found / closed_reported if closed_reported else 1.0) if closed_reports else None
    )
    costs = [receipt.cost_usd for receipt in complete_receipts]
    for cost in costs:
        if cost is not None and cost > manifest.per_review_cost_budget_usd:
            raise ValueError(f"reported review cost exceeds per-review ceiling: {expected_model}")
    known_cost_total = sum(cost for cost in costs if cost is not None)
    if known_cost_total > manifest.total_campaign_spend_ceiling_usd:
        raise ValueError(f"reported cost exceeds campaign ceiling: {expected_model}")
    cost_known = all(cost is not None for cost in costs)
    elapsed = [receipt.elapsed_seconds for receipt in complete_receipts]
    return PublishedProviderMetrics(
        provider=expected_provider,
        model=expected_model,
        immutable_model_pin=manifest.model_pins[expected_model],
        cases_run=len(rows),
        cases_failed=0,
        failed_case_ids=[],
        expected_case_count=manifest.expected_case_count,
        total_issues=total_issues,
        total_reported=total_reported,
        found=found,
        recall=recall,
        recall_interval_95=_wilson(found, total_issues),
        corpus_confirmed_precision=precision,
        corpus_confirmed_precision_interval_95=_wilson(found, total_reported),
        corpus_confirmed_f1=f1,
        unadjudicated=aggregate.unadjudicated,
        false_positives=aggregate.false_positives,
        false_positives_per_case=aggregate.false_positives_per_case,
        clean_case_fp_rate=aggregate.clean_case_fp_rate,
        closed_world_case_count=len(closed_reports),
        strict_precision=strict_precision,
        latency_p50_seconds=_percentile(elapsed, 0.5),
        latency_p95_seconds=_percentile(elapsed, 0.95),
        cost_known=cost_known,
        cost_usd=sum(cost for cost in costs if cost is not None) if cost_known else None,
        configured_per_review_cost_budget_usd=manifest.per_review_cost_budget_usd,
        raw_artifacts=raw_artifacts,
        mergecraft_commit=result.pins.mergecraft_commit,
        mergecraft_version=result.pins.mergecraft_version,
        rubric_version=result.pins.rubric_version,
        corpus_commit=result.pins.corpus_commit,
    )


def _validate_common_protocol(
    results: list[BenchmarkResultSet],
    judge: JudgeCalibrationReport,
) -> None:
    """Require both providers to use one scorer/prompt/judge protocol."""
    first = results[0].pins
    if first.scorer_version != SCORER_VERSION:
        raise ValueError("result scorer version does not match the running scorer")
    if first.line_slack < 0:
        raise ValueError("result line slack must not be negative")
    if (
        not first.mergecraft_commit.strip()
        or not first.mergecraft_version.strip()
        or not first.mode_prompt_versions
        or any(
            not key.strip() or not value.strip()
            for key, value in first.mode_prompt_versions.items()
        )
        or not first.judge_pins
    ):
        raise ValueError("result protocol pins are incomplete")
    for result in results[1:]:
        pins = result.pins
        if (
            pins.rubric_version != first.rubric_version
            or pins.judge_pins != first.judge_pins
            or pins.mode_prompt_versions != first.mode_prompt_versions
            or pins.scorer_version != first.scorer_version
            or pins.line_slack != first.line_slack
            or pins.mergecraft_commit != first.mergecraft_commit
            or pins.mergecraft_version != first.mergecraft_version
        ):
            raise ValueError("provider results do not share one frozen evaluation protocol")

    match = re.fullmatch(
        r"(?P<identity>.+)@judge-(?P<judge>[^/]+)/rubric-(?P<rubric>[^/]+)"
        r"/prompt-(?P<prompt>[0-9a-f]{12})/policy-.+",
        judge.candidate_id,
    )
    if match is None or match.group("rubric") != first.rubric_version:
        raise ValueError("judge-calibration candidate does not match result rubric")
    if match.group("prompt") != judge.prompt_sha256[:12]:
        raise ValueError("judge-calibration candidate prompt identity is inconsistent")
    matching_pin = False
    for pin in first.judge_pins.values():
        if not isinstance(pin, dict):
            continue
        identity = f"{pin.get('provider', '')}/{pin.get('model', '')}"
        if (
            identity == match.group("identity")
            and pin.get("judge_version") == match.group("judge")
            and pin.get("rubric_version") == match.group("rubric")
            and pin.get("model_pinned") is True
        ):
            matching_pin = True
            break
    if not matching_pin:
        raise ValueError("judge-calibration candidate has no matching result judge pin")


def build_publication(
    manifest_path: Path,
    result_paths: list[Path],
) -> BenchmarkPublicationSummary:
    """Load and validate all local evidence, then recompute a publication."""
    manifest = BenchmarkCampaignManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    judge = validate_campaign_artifacts(manifest, manifest_root=manifest_path.parent)
    if len(result_paths) != 2:
        raise ValueError("publication requires exactly two result files")
    results = [
        BenchmarkResultSet.model_validate_json(path.read_text(encoding="utf-8"))
        for path in result_paths
    ]
    by_model: dict[str, BenchmarkResultSet] = {}
    for result in results:
        if result.detection is None:
            raise ValueError("publication result is missing detection metrics")
        model = result.detection.model
        if model in by_model:
            raise ValueError(f"duplicate publication result for {model}")
        by_model[model] = result
    if set(by_model) != set(manifest.models):
        raise ValueError("result models do not match the campaign manifest")
    _validate_common_protocol(results, judge)
    providers = [
        _provider_metrics(
            manifest,
            by_model[model],
            model,
            manifest_root=manifest_path.parent,
        )
        for model in manifest.models
    ]
    known_campaign_cost = sum(
        provider.cost_usd for provider in providers if provider.cost_usd is not None
    )
    if known_campaign_cost > manifest.total_campaign_spend_ceiling_usd:
        raise ValueError("reported provider costs exceed the campaign spend ceiling")
    first_pins = results[0].pins
    return BenchmarkPublicationSummary(
        campaign_id=manifest.campaign_id,
        generated_at=datetime.now(UTC),
        manifest_sha256=_sha256(manifest_path),
        detection_label_receipt_sha256=manifest.detection_label_receipt_sha256,
        judge_calibration_receipt_sha256=manifest.judge_calibration_receipt_sha256,
        manifest_path=str(manifest_path),
        input_results=[
            InputResultArtifact(path=str(path), sha256=_sha256(path)) for path in result_paths
        ],
        judge_candidate_id=judge.candidate_id,
        judge_prompt_sha256=judge.prompt_sha256,
        judge_pins=first_pins.judge_pins,
        mode_prompt_versions=first_pins.mode_prompt_versions,
        rubric_version=first_pins.rubric_version,
        scorer_version=first_pins.scorer_version,
        line_slack=first_pins.line_slack,
        conservative_reserved_spend_usd=manifest.reserved_spend_usd,
        total_campaign_spend_ceiling_usd=manifest.total_campaign_spend_ceiling_usd,
        providers=providers,
        limitations=[
            "Detection model pins are operator-declared and must equal the requested model "
            "slug; this does not verify the provider's execution identity or make a "
            "floating alias immutable.",
            "Providers are reported separately; this report does not average or rank them.",
            "Corpus-confirmed precision is a lower bound for open-world cases; unmatched "
            "findings are unadjudicated, not false positives.",
            "Re-running the frozen protocol is reproducible, but model outputs may be stochastic.",
        ],
    )


def render_publication_markdown(summary: BenchmarkPublicationSummary) -> str:
    """Render a dated report whose values come only from the validated summary."""
    lines = [
        f"# Detection benchmark: {summary.campaign_id}",
        "",
        f"Generated: {summary.generated_at.isoformat()}",
        "",
        "| Provider/model | Cases | Failed | Recall (95% CI) | "
        "Corpus-confirmed precision (95% CI) | Corpus-confirmed F1 | "
        "P50 / P95 latency | Cost |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    details: list[str] = []
    for provider in summary.providers:
        cost = (
            f"${provider.cost_usd:.4f}"
            if provider.cost_known and provider.cost_usd is not None
            else "unknown"
        )
        recall_interval = provider.recall_interval_95
        precision_interval = provider.corpus_confirmed_precision_interval_95
        recall_text = (
            f"{provider.recall:.2%} [{recall_interval[0]:.2%}, {recall_interval[1]:.2%}]"
            if recall_interval is not None
            else f"{provider.recall:.2%} [undefined]"
        )
        precision_text = (
            f"{provider.corpus_confirmed_precision:.2%} "
            f"[{precision_interval[0]:.2%}, {precision_interval[1]:.2%}]"
            if precision_interval is not None
            else f"{provider.corpus_confirmed_precision:.2%} [undefined]"
        )
        lines.append(
            f"| `{provider.model}` (`{provider.immutable_model_pin}`) | "
            f"{provider.cases_run}/{provider.expected_case_count} | "
            f"{provider.cases_failed} ({', '.join(provider.failed_case_ids) or 'none'}) | "
            f"{recall_text} | {precision_text} | {provider.corpus_confirmed_f1:.2%} | "
            f"{provider.latency_p50_seconds:.3f}s / {provider.latency_p95_seconds:.3f}s | "
            f"{cost} |"
        )
        details.extend(
            [
                "",
                f"- `{provider.model}` counts: issues={provider.total_issues}, "
                f"reported={provider.total_reported}, found={provider.found}, "
                f"unadjudicated={provider.unadjudicated}, "
                f"closed-world false positives={provider.false_positives}.",
                *[
                    f"- `{provider.model}` raw artifact: `{artifact.path}` "
                    f"(`sha256:{artifact.sha256}`)."
                    for artifact in provider.raw_artifacts
                ],
            ]
        )
    reproduction = [
        "mergecraft",
        "eval",
        "publish-benchmark",
        "--manifest",
        summary.manifest_path,
    ]
    for result in summary.input_results:
        reproduction.extend(["--result", result.path])
    reproduction.extend(["--output", "evals/results"])
    reproduction_command = " ".join(shlex.quote(part) for part in reproduction)
    lines.extend(details)
    lines.extend(
        [
            "",
            "## Limits and reproducibility",
            "",
            *[f"- {limitation}" for limitation in summary.limitations],
            "- Actual cost remains unknown wherever the provider supplied no cost receipt; "
            "unknown is never rendered as zero.",
            f"- Conservative reserved ceiling: ${summary.conservative_reserved_spend_usd:.4f} "
            f"of ${summary.total_campaign_spend_ceiling_usd:.4f} approved.",
            f"- Judge candidate: `{summary.judge_candidate_id}`; prompt "
            f"`sha256:{summary.judge_prompt_sha256}`; rubric `{summary.rubric_version}`; "
            f"scorer `{summary.scorer_version}`; line slack `{summary.line_slack}`.",
            *[
                f"- Input result: `{artifact.path}` (`sha256:{artifact.sha256}`)."
                for artifact in summary.input_results
            ],
            "",
            "Reproduce the keyless validation with:",
            "",
            "```bash",
            reproduction_command,
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_publication(
    summary: BenchmarkPublicationSummary,
    *,
    output_dir: Path,
) -> tuple[Path, Path]:
    """Write an immutable campaign directory below the requested output root."""
    campaign_dir = output_dir / summary.campaign_id
    if campaign_dir.exists():
        raise ValueError(f"campaign publication output already exists: {campaign_dir}")
    campaign_dir.mkdir(parents=True)
    summary_path = campaign_dir / "summary.json"
    report_path = campaign_dir / "report.md"
    summary_path.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_publication_markdown(summary), encoding="utf-8")
    return summary_path, report_path


__all__ = [
    "ArtifactDigest",
    "BenchmarkCampaignManifest",
    "BenchmarkPublicationSummary",
    "CampaignCase",
    "DetectionLabelReceipt",
    "InputResultArtifact",
    "PublishedProviderMetrics",
    "build_publication",
    "render_publication_markdown",
    "validate_campaign_artifacts",
    "write_publication",
]
