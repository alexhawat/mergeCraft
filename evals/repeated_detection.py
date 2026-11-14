"""Run and rescore a frozen repository-context detection campaign.

Module: evals.repeated_detection
Depends: mergecraft.evals, mergecraft.offline_review, pydantic

Exports:
    Classes:
        RepeatProtocol — Operator-approved held-out context and repeat schedule.
    Functions:
        context_sha256 — Fingerprint the exact pre-patch repository inputs.
        run_campaign — Record each provider's live runs with existing eval receipts.
        summarize_campaign — Verify and rescore the saved campaign without credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import random
import re
import statistics
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.config import load_repo_settings
from mergecraft.evals.benchmark import (
    BenchmarkResultSet,
    DetectionCase,
    run_structural_replay,
    write_result_set,
)
from mergecraft.evals.live_run import (
    ReviewBudget,
    ReviewOutcome,
    ReviewRunFailed,
    _bounded_environment,
    materialize_case_repo,
    run_live_detection,
)
from mergecraft.evals.publication import (
    BenchmarkCampaignManifest,
    _percentile,
    _provider_metrics,
    _resolve_verified,
    _validate_common_protocol,
    validate_campaign_artifacts,
)
from mergecraft.evals.scoring import (
    load_baseline_issues,
    load_reported_findings,
    score_findings,
)
from mergecraft.evidence.packet import MergeEvidencePacket
from mergecraft.run_outcome import RunOutcome
from mergecraft.tracing.sinks import read_jsonl_events
from mergecraft.utils.agent_resolve import has_credentials_for_slug
from mergecraft.utils.atomic_write import write_text_atomically
from mergecraft.utils.run_bounds import round_budget_multiplier

if TYPE_CHECKING:
    from mergecraft.evals.judge_calibration import JudgeCalibrationReport
    from mergecraft.evals.live_run import ReviewFn
    from mergecraft.evals.publication import CampaignCase

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_BOOTSTRAP_SAMPLES = 2000
_BOOTSTRAP_SEED = 1379
RecordedCost = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class RepeatProtocol(BaseModel):
    """Pin a conventional campaign, its repository contexts and its repeat count."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0.0"]
    campaign_manifest: str
    campaign_sha256: Sha256
    split: Literal["held-out"]
    repetitions: int = Field(ge=3)
    context_sha256: dict[str, Sha256]


class _RunReceipt(BaseModel):
    """Bind one run and its sanitized usage/dispatch observations to the protocol."""

    model_config = ConfigDict(extra="forbid", strict=True)

    protocol_sha256: Sha256
    result_sha256: Sha256
    repetition: int
    model: str
    context_sha256: dict[str, Sha256]
    single_attempt_cases: list[str]
    recorded_costs: dict[str, RecordedCost]


@dataclass
class _ReviewObservations:
    """Execution evidence retained without including the local trace or packet."""

    recorded_costs: dict[str, float] = field(default_factory=dict)
    single_attempt_cases: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Campaign:
    """Validated inputs used by both live execution and keyless rescore."""

    protocol: RepeatProtocol
    protocol_sha256: str
    manifest_path: Path
    manifest: BenchmarkCampaignManifest
    cases: list[DetectionCase]
    judge: JudgeCalibrationReport


@dataclass
class _Spend:
    """Sum the reported spend across all paid attempts in the campaign."""

    ceiling_usd: float
    known_usd: float = 0.0

    @property
    def exhausted(self) -> bool:
        """Return whether the reported spend has reached the global ceiling."""
        return self.known_usd >= self.ceiling_usd


class _Counts(NamedTuple):
    """One case attempt's counts for the clustered statistics."""

    found: int
    issues: int
    reported: int
    clean_reviews: int
    clean_reviews_with_findings: int
    clean_findings: int


def context_sha256(root: Path) -> str:
    """Digest the paths, contents and executable bits of a pre-patch tree.

    The canonical inventory also covers empty directories. Context must be
    nonempty, confined to regular files, and free of Git metadata and dotenv
    files so it can be copied without importing external repository state.

    Args:
        root (Path): The case's pre-patch repo directory.

    Returns:
        str: SHA-256 of the canonical JSON inventory.

    Raises:
        ValueError: If the context is missing, empty or contains unsupported entries.

    Examples:
        >>> context_sha256(Path("absent-repo"))
        Traceback (most recent call last):
        ...
        ValueError: missing repository context: absent-repo
    """
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"missing repository context: {root}")
    inventory: list[tuple[str, str, bool]] = []
    file_count = 0
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink() or path.name in {".git", ".env"} or path.name.startswith(".env."):
            raise ValueError(f"unsupported repository context entry: {name}")
        if path.is_dir():
            inventory.append((name, "directory", False))
        elif path.is_file():
            inventory.append((name, _sha256(path), bool(path.stat().st_mode & 0o111)))
            file_count += 1
        else:
            raise ValueError(f"unsupported repository context entry: {name}")
    if not file_count:
        raise ValueError(f"empty repository context: {root}")
    return hashlib.sha256(json.dumps(inventory, separators=(",", ":")).encode()).hexdigest()


def _sha256(path: Path) -> str:
    """Digest the exact bytes of an artifact."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_campaign(protocol_path: Path) -> _Campaign:
    """Verify the published campaign prerequisites and each held-out input."""
    protocol_bytes = protocol_path.read_bytes()
    protocol = RepeatProtocol.model_validate_json(protocol_bytes)
    manifest_path = _resolve_verified(
        protocol_path.parent, protocol.campaign_manifest, protocol.campaign_sha256
    )
    manifest = BenchmarkCampaignManifest.model_validate_json(manifest_path.read_bytes())
    reserved = manifest.reserved_spend_usd * protocol.repetitions
    if reserved > manifest.total_campaign_spend_ceiling_usd:
        raise ValueError("repeat reservation exceeds the campaign spend ceiling")
    if set(protocol.context_sha256) != {case.case_id for case in manifest.cases}:
        raise ValueError("repository context pins must cover the exact campaign case set")
    if any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", model.split("/", 1)[0])
        for model in manifest.models
    ):
        raise ValueError("provider names must be safe path components")
    judge = validate_campaign_artifacts(manifest, manifest_root=manifest_path.parent)

    cases = []
    defect_cases = clean_cases = 0
    for case in sorted(manifest.cases, key=lambda case: case.case_id):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", case.case_id):
            raise ValueError(f"unsafe case id: {case.case_id!r}")
        patch = _resolve_verified(manifest_path.parent, case.patch_path, case.patch_sha256)
        baseline = _resolve_verified(manifest_path.parent, case.baseline_path, case.baseline_sha256)
        if not case.closed_world:
            raise ValueError(f"{case.case_id} requires a closed-world baseline")
        if context_sha256(patch.parent / "repo") != protocol.context_sha256[case.case_id]:
            raise ValueError(f"context hash drift: {case.case_id}")
        payload = json.loads(baseline.read_bytes())
        if (
            not isinstance(payload, dict)
            or payload.get("closed_world") is not case.closed_world
            or not isinstance(payload.get("issues"), list)
            or any(not isinstance(row, dict) for row in payload["issues"])
        ):
            raise ValueError(f"{case.case_id} requires a baseline with explicit closure and issues")
        issues = load_baseline_issues(payload)
        if any(
            issue.provenance != "human"
            or not issue.path
            or issue.start_line < 1
            or issue.end_line < issue.start_line
            for issue in issues
        ) or len({issue.id for issue in issues}) != len(issues):
            raise ValueError(f"{case.case_id} needs valid, distinct human-adjudicated issues")
        defect_cases += bool(issues)
        clean_cases += not issues
        cases.append(
            DetectionCase(
                case_id=case.case_id,
                patch_path=patch,
                baseline_path=baseline,
                closed_world=case.closed_world,
            )
        )
    if not defect_cases or not clean_cases:
        raise ValueError("held-out corpus requires labelled defects and adjudicated clean cases")
    return _Campaign(
        protocol, hashlib.sha256(protocol_bytes).hexdigest(), manifest_path, manifest, cases, judge
    )


def _verify_single_attempt(traces: Path, model: str) -> None:
    """Reject a review with any retry or without one observed pinned dispatch."""
    attempts = [
        (
            event["attrs"].get("model.attempt_number"),
            event["attrs"].get("model.id"),
            event["status"],
        )
        for path in traces.glob("*.jsonl")
        for event in read_jsonl_events(path)
        if event.get("kind") == "agent.attempt" and event.get("status") != "not_visited"
    ]
    if attempts != [(1, model, "ok")]:
        raise ReviewRunFailed("review must record exactly one successful pinned model attempt")


def _review_fn(
    model: str,
    budget: ReviewBudget,
    campaign: _Campaign,
    spend: _Spend,
    observations: _ReviewObservations,
) -> ReviewFn:
    """Use the existing offline review with the case context and cost evidence."""
    from mergecraft.offline_review import run_offline_diff_review

    pins: dict[str, CampaignCase] = {case.case_id: case for case in campaign.manifest.cases}

    def review(case: DetectionCase) -> ReviewOutcome:
        """Materialize only the case files and bound one real review."""
        if spend.exhausted:
            raise ReviewRunFailed("reported campaign spend ceiling reached")
        with tempfile.TemporaryDirectory(prefix="mergecraft-held-out-") as work_dir:
            work = Path(work_dir)
            repo = materialize_case_repo(case, work / "repo")
            if context_sha256(repo) != campaign.protocol.context_sha256[case.case_id]:
                raise ReviewRunFailed(f"{case.case_id}: materialized context hash drift")
            settings = load_repo_settings(root=repo, load_learnings_files=False)
            if round_budget_multiplier(settings.review.round_budgets, round_index=1) != 1.0:
                raise ReviewRunFailed(
                    f"{case.case_id}: configured round budget changes review limits"
                )
            pin = pins[case.case_id]
            patch_bytes = case.patch_path.read_bytes()
            if (
                hashlib.sha256(patch_bytes).hexdigest() != pin.patch_sha256
                or _sha256(case.baseline_path) != pin.baseline_sha256
            ):
                raise ReviewRunFailed(f"{case.case_id}: patch or baseline hash drift")
            patch = work / "task.patch"
            patch.write_bytes(patch_bytes)
            output = work / "findings.json"
            evidence = work / "evidence.json"
            traces = work / "traces"
            with _bounded_environment(budget):
                result = asyncio.run(
                    asyncio.wait_for(
                        run_offline_diff_review(
                            cwd=repo,
                            diff_file=patch,
                            model=model,
                            json_path=output,
                            evidence_packet_path=evidence,
                            trust_override="untrusted",
                            shell="disabled",
                            tracing_cli=[
                                "--tracing",
                                "--tracing-to",
                                "local_files",
                                "--trace-dir",
                                str(traces),
                                "--tracing-content",
                                "off",
                                "--no-tracing-export-untrusted-content",
                            ],
                        ),
                        timeout=budget.per_review_timeout_seconds,
                    )
                )
            packet = (
                MergeEvidencePacket.model_validate_json(evidence.read_bytes())
                if evidence.is_file()
                else None
            )
            metrics = packet.run_metrics if packet is not None else None
            reported_cost = metrics.recorded_cost_usd if metrics is not None else None
            if reported_cost is not None:
                observations.recorded_costs[case.case_id] = reported_cost
                spend.known_usd += reported_cost
                if (
                    budget.per_review_cost_budget_usd is not None
                    and reported_cost > budget.per_review_cost_budget_usd
                ):
                    raise ReviewRunFailed(
                        f"{case.case_id}: reported cost exceeds the per-review ceiling"
                    )
            if not result.success or result.outcome is not RunOutcome.passed or packet is None:
                raise ReviewRunFailed(f"{case.case_id}: review did not complete or emit evidence")
            expected_diff = patch.read_text(encoding="utf-8")
            if expected_diff and not expected_diff.endswith("\n"):
                expected_diff += "\n"
            if (
                result.diff_path is None
                or Path(result.diff_path).read_text(encoding="utf-8") != expected_diff
            ):
                raise ReviewRunFailed(
                    f"{case.case_id}: reviewed diff does not match the approved patch"
                )
            _verify_single_attempt(traces, model)
            observations.single_attempt_cases.append(case.case_id)
            if (
                packet.agent.requested_model != model
                or packet.agent.executed_model != model
                or packet.agent.fallback_occurred
            ):
                raise ReviewRunFailed(f"{case.case_id}: evidence does not match the pinned model")
            cost = (
                reported_cost
                if metrics is not None and metrics.cost_availability == "available"
                else None
            )
            payload = json.loads(output.read_bytes())
            if not isinstance(payload, dict) or not isinstance(payload.get("findings"), list):
                raise ReviewRunFailed(f"{case.case_id}: missing structured findings")
            findings = payload["findings"]
            if any(not isinstance(row, dict) for row in findings):
                raise ReviewRunFailed(f"{case.case_id}: invalid structured findings")
            load_reported_findings(payload)
            return ReviewOutcome(findings=findings, cost_usd=cost)

    return review


def _result_path(results_dir: Path, repetition: int, provider: str) -> Path:
    """Give every planned run one explicit result file for keyless replay."""
    return results_dir / f"repeat-{repetition:03d}-{provider}.json"


def run_campaign(protocol_path: Path, results_dir: Path) -> None:
    """Run the exact recorded schedule in a new results directory.

    Args:
        protocol_path (Path): Approved protocol document pinning the inputs.
        results_dir (Path): A new directory for raw findings and result sets.

    Raises:
        ValueError: If evidence, credentials, budgets, or execution pins do not qualify.

    Examples:
        >>> run_campaign(Path("missing.json"), Path("new-results"))
        Traceback (most recent call last):
        ...
        FileNotFoundError: ...
    """
    campaign = _load_campaign(protocol_path)
    manifest = campaign.manifest
    template = run_structural_replay()
    if template.pins.working_tree_clean is not True:
        raise ValueError("benchmark requires a clean tracked checkout")
    _validate_common_protocol([template], campaign.judge)
    if any(not has_credentials_for_slug(model) for model in manifest.models):
        raise ValueError("live credentials must be available for each pinned model")

    results_dir = results_dir.resolve()
    results_dir.mkdir(parents=True)
    budget = ReviewBudget(
        per_review_timeout_seconds=manifest.per_review_timeout_seconds,
        per_review_token_limit=manifest.per_review_token_limit,
        per_review_cost_budget_usd=manifest.per_review_cost_budget_usd,
    )
    spend = _Spend(manifest.total_campaign_spend_ceiling_usd)
    for repetition in range(1, campaign.protocol.repetitions + 1):
        for model in manifest.models:
            if spend.exhausted:
                raise ValueError("reported campaign spend ceiling reached before all runs")
            provider = model.split("/", 1)[0]
            pins = template.pins.model_copy(
                update={"corpus_commit": manifest.corpus_commit, "recorded_at": datetime.now(UTC)}
            )
            observations = _ReviewObservations()
            detection = run_live_detection(
                campaign.cases,
                provider=provider,
                model=model,
                review_fn=_review_fn(model, budget, campaign, spend, observations),
                results_dir=results_dir,
                immutable_model_pin=model,
                budget=budget,
            )
            result = template.model_copy(update={"pins": pins, "detection": detection})
            path = _result_path(results_dir, repetition, provider)
            write_result_set(
                result, results_dir=results_dir, filename=path.name, update_latest=False
            )
            receipt = _RunReceipt(
                protocol_sha256=campaign.protocol_sha256,
                result_sha256=_sha256(path),
                repetition=repetition,
                model=model,
                context_sha256=campaign.protocol.context_sha256,
                single_attempt_cases=observations.single_attempt_cases,
                recorded_costs=observations.recorded_costs,
            )
            write_text_atomically(path.with_suffix(".receipt.json"), receipt.model_dump_json())
    if spend.known_usd > spend.ceiling_usd:
        raise ValueError("reported campaign spend exceeded the approved ceiling")


def _sum_counts(rows: list[_Counts]) -> _Counts:
    """Pool counts before taking a ratio."""
    return (
        _Counts(*(sum(column) for column in zip(*rows, strict=True)))
        if rows
        else _Counts(0, 0, 0, 0, 0, 0)
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    """Keep undefined rates null."""
    return numerator / denominator if denominator else None


def _intervals(clusters: list[_Counts]) -> dict[str, tuple[float, float] | None]:
    """Draw whole case IDs with replacement, carrying all their attempts."""
    randomizer = random.Random(_BOOTSTRAP_SEED)
    precision: list[float] = []
    recall: list[float] = []
    if len(clusters) >= 2:
        for _ in range(_BOOTSTRAP_SAMPLES):
            counts = _sum_counts(randomizer.choices(clusters, k=len(clusters)))
            if counts.reported:
                precision.append(counts.found / counts.reported)
            if counts.issues:
                recall.append(counts.found / counts.issues)
    return {
        f"{name}_interval_95": (_percentile(values, 0.025), _percentile(values, 0.975))
        if values
        else None
        for name, values in (("precision", precision), ("recall", recall))
    }


def _score_case(raw: bytes, case: DetectionCase, slack: int) -> _Counts:
    """Rescore verified raw findings after dropping same-location duplicates."""
    issues = load_baseline_issues(json.loads(case.baseline_path.read_bytes()))
    findings = load_reported_findings(json.loads(raw))
    duplicates = set(score_findings([], findings, slack=0).duplicate_finding_indexes)
    unique = [row for index, row in enumerate(findings) if index not in duplicates]
    scored = score_findings(issues, unique, closed_world=case.closed_world, slack=slack)
    clean = not issues
    return _Counts(
        scored.found,
        len(issues),
        len(unique),
        int(clean),
        int(clean and bool(unique)),
        len(unique) if clean else 0,
    )


def _summarize_provider(
    campaign: _Campaign, model: str, runs: list[tuple[BenchmarkResultSet, _RunReceipt]]
) -> dict[str, object]:
    """Use the existing raw artifact validator before duplicate-aware scoring."""
    cases = {case.case_id: case for case in campaign.cases}
    clusters: dict[str, list[_Counts]] = defaultdict(list)
    per_run: list[dict[str, float | None]] = []
    costs: list[float] = []
    lower_bound_costs: list[float] = []
    latencies: list[float] = []
    for result, run_receipt in runs:
        _provider_metrics(
            campaign.manifest, result, model, manifest_root=campaign.manifest_path.parent
        )
        detection = result.detection
        assert detection is not None
        if sorted(run_receipt.single_attempt_cases) != sorted(cases):
            raise ValueError(f"missing or repeated pinned dispatch evidence for {model}")
        recorded_costs = run_receipt.recorded_costs
        if not recorded_costs.keys() <= cases.keys() or any(
            cost > campaign.manifest.per_review_cost_budget_usd for cost in recorded_costs.values()
        ):
            raise ValueError(f"invalid recorded review costs for {model}")
        lower_bound_costs.extend(recorded_costs.values())
        run_rows: list[_Counts] = []
        for row in sorted(detection.case_results, key=lambda row: row.case_id):
            receipt = row.execution_receipt
            assert receipt is not None
            raw = Path(receipt.raw_findings_path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != receipt.raw_findings_sha256:
                raise ValueError(f"case {row.case_id} raw findings hash drift")
            counts = _score_case(raw, cases[row.case_id], result.pins.line_slack)
            run_rows.append(counts)
            clusters[row.case_id].append(counts)
            latencies.append(receipt.elapsed_seconds)
            if receipt.cost_usd is not None:
                if recorded_costs.get(row.case_id) != receipt.cost_usd:
                    raise ValueError(f"case {row.case_id} recorded cost disagrees with receipt")
                costs.append(receipt.cost_usd)
        run = _sum_counts(run_rows)
        per_run.append(
            {
                "precision": _ratio(run.found, run.reported),
                "recall": _ratio(run.found, run.issues),
            }
        )
    count_clusters = [_sum_counts(rows) for _, rows in sorted(clusters.items())]
    total = _sum_counts(count_clusters)
    stdev = {}
    for metric in ("precision", "recall"):
        values = [value for row in per_run if (value := row[metric]) is not None]
        stdev[f"{metric}_run_stdev"] = statistics.stdev(values) if len(values) > 1 else None
    reviews = len(latencies)
    cost_complete = len(costs) == reviews
    f1 = _ratio(2 * total.found, total.issues + total.reported)
    return {
        "model": model,
        "provider": model.split("/", 1)[0],
        "completed_reviews": reviews,
        "counts": total._asdict(),
        "precision": _ratio(total.found, total.reported),
        "recall": _ratio(total.found, total.issues),
        "f1": f1,
        **_intervals(count_clusters),
        **stdev,
        "per_run": per_run,
        "clean_case_fp_rate": _ratio(total.clean_reviews_with_findings, total.clean_reviews),
        "findings_per_clean_review": _ratio(total.clean_findings, total.clean_reviews),
        "median_latency_seconds": statistics.median(latencies),
        "cost_known_reviews": len(costs),
        "cost_partial_reviews": len(lower_bound_costs) - len(costs),
        "known_spend_usd": math.fsum(lower_bound_costs) if lower_bound_costs else None,
        "total_cost_usd": math.fsum(costs) if cost_complete else None,
        "median_cost_usd": statistics.median(costs) if cost_complete else None,
    }


def summarize_campaign(protocol_path: Path, results_dir: Path) -> dict[str, object]:
    """Verify every complete run and recompute provider statistics from raw findings.

    Args:
        protocol_path (Path): The approved protocol used for live execution.
        results_dir (Path): The run directory and its recorded receipts.

    Returns:
        dict[str, object]: The provider-level report and artifact pins.

    Raises:
        ValueError: If the protocol or any result does not qualify for comparison.

    Examples:
        >>> summarize_campaign(Path("missing.json"), Path("results"))
        Traceback (most recent call last):
        ...
        FileNotFoundError: ...
    """
    campaign = _load_campaign(protocol_path)
    all_results: dict[str, list[tuple[BenchmarkResultSet, _RunReceipt]]] = {}
    result_hashes = {}
    raw_dirs: set[Path] = set()
    for model in campaign.manifest.models:
        all_results[model] = []
        for repetition in range(1, campaign.protocol.repetitions + 1):
            path = _result_path(results_dir, repetition, model.split("/", 1)[0])
            data = path.read_bytes()
            result = BenchmarkResultSet.model_validate_json(data)
            if result.detection is None or result.pins.working_tree_clean is not True:
                raise ValueError(f"{path.name}: missing clean-checkout detection result")
            raw_dir = Path(result.detection.raw_findings_dir).resolve()
            if raw_dir in raw_dirs or raw_dir.parent != (results_dir / "raw-findings").resolve():
                raise ValueError(f"{path.name}: repeated or out-of-campaign raw findings directory")
            raw_dirs.add(raw_dir)
            receipt_path = path.with_suffix(".receipt.json")
            receipt_bytes = receipt_path.read_bytes()
            receipt = _RunReceipt.model_validate_json(receipt_bytes)
            result_sha256 = hashlib.sha256(data).hexdigest()
            if (
                receipt.protocol_sha256 != campaign.protocol_sha256
                or receipt.result_sha256 != result_sha256
                or receipt.repetition != repetition
                or receipt.model != model
                or receipt.context_sha256 != campaign.protocol.context_sha256
            ):
                raise ValueError(f"{path.name}: run receipt does not match the repeated campaign")
            all_results[model].append((result, receipt))
            result_hashes[path.name] = result_sha256
            result_hashes[receipt_path.name] = hashlib.sha256(receipt_bytes).hexdigest()
    _validate_common_protocol(
        [result for runs in all_results.values() for result, _ in runs], campaign.judge
    )
    providers = [
        _summarize_provider(campaign, model, results) for model, results in all_results.items()
    ]
    spend = math.fsum(
        float(value) for row in providers if isinstance(value := row["known_spend_usd"], float)
    )
    if spend > campaign.manifest.total_campaign_spend_ceiling_usd:
        raise ValueError("recorded review costs exceed the repeat campaign ceiling")
    return {
        "schema_version": "1.0.0",
        "campaign_id": campaign.manifest.campaign_id,
        "split": campaign.protocol.split,
        "protocol_sha256": campaign.protocol_sha256,
        "campaign_sha256": campaign.protocol.campaign_sha256,
        "corpus_commit": campaign.manifest.corpus_commit,
        "mergecraft_commit": all_results[campaign.manifest.models[0]][0][0].pins.mergecraft_commit,
        "reserved_spend_usd": campaign.manifest.reserved_spend_usd * campaign.protocol.repetitions,
        "campaign_spend_ceiling_usd": campaign.manifest.total_campaign_spend_ceiling_usd,
        "input_result_sha256": result_hashes,
        "case_count": len(campaign.cases),
        "repetitions": campaign.protocol.repetitions,
        "bootstrap_samples": _BOOTSTRAP_SAMPLES,
        "bootstrap_seed": _BOOTSTRAP_SEED,
        "providers": providers,
    }


def _main() -> None:
    """Expose operator-only live execution and credential-free rescore."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("command", choices=["run", "summarize", "context-sha256"])
    parser.add_argument("path", type=Path, help="Repeat protocol, or repo/ for context-sha256.")
    parser.add_argument("results_dir", type=Path, nargs="?")
    args = parser.parse_args()
    try:
        import sys

        if args.command == "context-sha256":
            if args.results_dir is not None:
                parser.error("context-sha256 expects only the repository directory")
            sys.stdout.write(context_sha256(args.path) + "\n")
            return
        if args.results_dir is None:
            parser.error(f"{args.command} requires a results directory")
        if args.command == "run":
            run_campaign(args.path, args.results_dir)
        else:
            json.dump(summarize_campaign(args.path, args.results_dir), sys.stdout, indent=2)
            sys.stdout.write("\n")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"campaign refused: {exc}\n")


if __name__ == "__main__":
    _main()
