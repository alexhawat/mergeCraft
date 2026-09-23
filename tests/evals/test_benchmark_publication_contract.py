"""Keyless campaign publication validates immutable execution evidence."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.evals.adjudication import CalibrationStatus
from mergecraft.evals.benchmark import (
    BenchmarkResultSet,
    DetectionCaseResult,
    DetectionExecutionReceipt,
    DetectionMetrics,
    ReviewingModelPin,
    run_structural_replay,
)
from mergecraft.evals.judge_calibration import (
    CalibrationSplitReport,
    calibration_report_sha256,
)
from mergecraft.evals.publication import (
    BenchmarkCampaignManifest,
    build_publication,
    write_publication,
)
from mergecraft.evals.scoring import AggregateScoreReport

WHEN = datetime(2026, 9, 22, 12, 0, tzinfo=UTC)
CORPUS_COMMIT = "a" * 40
MODELS = ("anthropic/model-a", "openai/model-b")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _aggregate() -> AggregateScoreReport:
    return AggregateScoreReport(
        total_cases=1,
        total_issues=1,
        total_reported=1,
        found=1,
        false_negatives=0,
        unadjudicated=0,
        false_positives=0,
        false_positives_per_case=0.0,
        clean_case_fp_rate=0.0,
    )


def _write_prerequisites(root: Path, patch_hash: str, baseline_hash: str) -> tuple[str, str]:
    label_receipt = root / "receipts" / "labels.json"
    judge_receipt = root / "receipts" / "judge.json"
    label_receipt.parent.mkdir()
    label_receipt.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "corpus_commit": CORPUS_COMMIT,
                "case_hashes": {
                    "case-1": {
                        "patch_sha256": patch_hash,
                        "baseline_sha256": baseline_hash,
                        "closed_world": False,
                    }
                },
                "label_status": "independently_adjudicated",
                "adjudicator_login": "reviewer",
                "adjudicated_at": WHEN.isoformat(),
            }
        ),
        encoding="utf-8",
    )
    class_metrics = {
        label: {
            "support": 1,
            "predicted": 1,
            "true_positive": 1,
            "precision": 1.0,
            "recall": 1.0,
            "f1": 1.0,
        }
        for label in ("confirm", "downgrade", "drop")
    }
    metrics = {
        "sample_count": 3,
        "human_class_counts": {"confirm": 1, "downgrade": 1, "drop": 1},
        "confusion_matrix": {
            "confirm": {"confirm": 1, "downgrade": 0, "drop": 0},
            "downgrade": {"confirm": 0, "downgrade": 1, "drop": 0},
            "drop": {"confirm": 0, "downgrade": 0, "drop": 1},
        },
        "per_class": class_metrics,
        "micro_precision": 1.0,
        "micro_recall": 1.0,
        "micro_f1": 1.0,
        "macro_precision": 1.0,
        "macro_recall": 1.0,
        "macro_f1": 1.0,
        "disagreement_rate": 0.0,
        "cohen_kappa": 1.0,
        "downgrade_severity_agreement": 1.0,
        "downgrade_severity_pair_count": 1,
        "high_stakes_escalation_recall": 1.0,
        "high_stakes_drop_count": 1,
        "limitations": ["single human"],
    }
    thresholds = {
        "minimum_per_class": True,
        "minimum_macro_f1": True,
        "minimum_drop_precision": True,
        "minimum_confirm_recall": True,
        "minimum_kappa": True,
        "maximum_disagreement_rate": True,
        "required_high_stakes_escalation_recall": True,
    }
    split = {"metrics": metrics, "threshold_results": thresholds, "passed": True}
    calibration_hash = calibration_report_sha256(CalibrationSplitReport.model_validate(split))
    judge_receipt.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "state": "validated",
                "candidate_id": (
                    "judge/judge-model@judge-1/rubric-1.0.0/prompt-111111111111/policy-policy-v1"
                ),
                "prompt_sha256": "1" * 64,
                "policy_id": "policy-v1",
                "policy_parameters": {"high_stakes_drop": "human-escalation"},
                "protocol_sha256": "2" * 64,
                "calibration_report_sha256": calibration_hash,
                "case_hashes": {"judge-case": "4" * 64},
                "acceptance_contract": {
                    "minimum_per_class": 1,
                    "minimum_macro_f1": 0.9,
                    "minimum_drop_precision": 0.9,
                    "minimum_confirm_recall": 0.9,
                    "minimum_kappa": 0.8,
                    "maximum_disagreement_rate": 0.1,
                    "required_high_stakes_escalation_recall": 1.0,
                },
                "calibration": split,
                "held_out": split,
                "seal_sha256": "5" * 64,
                "sealed_by": "release-operator",
                "sealed_at": WHEN.isoformat(),
                "limitations": ["single human"],
            }
        ),
        encoding="utf-8",
    )
    return _digest(label_receipt), _digest(judge_receipt)


def _result(
    root: Path,
    model: str,
    *,
    patch_hash: str,
    baseline_hash: str,
    include_receipt: bool = True,
    pin_matches: bool = True,
) -> Path:
    provider = model.split("/", 1)[0]
    raw_dir = root / "raw" / provider
    raw_dir.mkdir(parents=True)
    raw_path = raw_dir / "case-1.json"
    raw_path.write_text(
        json.dumps({"findings": [{"path": "a.py", "start_line": 1, "end_line": 1}]}),
        encoding="utf-8",
    )
    receipt = (
        DetectionExecutionReceipt(
            patch_sha256=patch_hash,
            baseline_sha256=baseline_hash,
            raw_findings_path=str(raw_path),
            raw_findings_sha256=_digest(raw_path),
            elapsed_seconds=1.25,
            cost_known=False,
            cost_usd=None,
        )
        if include_receipt
        else None
    )
    row = DetectionCaseResult(
        case_id="case-1",
        closed_world=False,
        total_issues=1,
        total_reported=1,
        found=1,
        recall=1.0,
        corpus_confirmed_precision=1.0,
        f1=1.0,
        execution_receipt=receipt,
    )
    detection = DetectionMetrics(
        provider=provider,
        model=model,
        cases_run=1,
        aggregate=_aggregate(),
        case_results=[row],
        raw_findings_dir=str(raw_dir),
        calibration=CalibrationStatus(
            counts={"independent": 1, "model": 0, "none": 0},
            required="independent",
            eligible=True,
            reason="all labels eligible",
        ),
        execution_identity={
            "provider": provider,
            "requested_model": model,
            "executed_model": model,
            "immutable_model_pin": model if pin_matches else f"{model}@different",
            "pin_provenance": "operator-declared",
        },
    )
    base = run_structural_replay(root / "missing-bank", providers=(provider,))
    recorded_model = model if pin_matches else f"{provider}/different"
    pins = base.pins.model_copy(
        update={
            "corpus_commit": CORPUS_COMMIT,
            "reviewing_model": {
                provider: ReviewingModelPin(
                    model_id=recorded_model,
                    model_pin=recorded_model,
                    model_pinned=True,
                )
            },
            "rubric_version": "1.0.0",
            "judge_pins": {
                "judge": {
                    "provider": "judge",
                    "model": "judge-model",
                    "model_pinned": True,
                    "judge_version": "1",
                    "rubric_version": "1.0.0",
                }
            },
        }
    )
    result = base.model_copy(update={"pins": pins, "detection": detection})
    path = root / f"{provider}-result.json"
    path.write_text(result.model_dump_json(), encoding="utf-8")
    return path


def _campaign(tmp_path: Path) -> tuple[Path, list[Path]]:
    case_dir = tmp_path / "corpus" / "case-1"
    case_dir.mkdir(parents=True)
    patch = case_dir / "task.patch"
    baseline = case_dir / "baseline.json"
    patch.write_text("frozen patch", encoding="utf-8")
    baseline.write_text(
        json.dumps(
            {
                "closed_world": False,
                "issues": [
                    {
                        "id": "i",
                        "path": "a.py",
                        "startLine": 1,
                        "endLine": 1,
                        "provenance": "human",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    patch_hash = _digest(patch)
    baseline_hash = _digest(baseline)
    label_hash, judge_hash = _write_prerequisites(tmp_path, patch_hash, baseline_hash)
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "campaign_id": "campaign-20260922",
        "corpus_commit": CORPUS_COMMIT,
        "cases": [
            {
                "case_id": "case-1",
                "patch_path": "corpus/case-1/task.patch",
                "patch_sha256": patch_hash,
                "baseline_path": "corpus/case-1/baseline.json",
                "baseline_sha256": baseline_hash,
                "closed_world": False,
                "label_status": "independently_adjudicated",
            }
        ],
        "detection_label_receipt_path": "receipts/labels.json",
        "detection_label_receipt_sha256": label_hash,
        "judge_calibration_receipt_path": "receipts/judge.json",
        "judge_calibration_receipt_sha256": judge_hash,
        "models": list(MODELS),
        "model_pins": {model: model for model in MODELS},
        "per_review_timeout_seconds": 180,
        "per_review_token_limit": 12000,
        "per_review_cost_budget_usd": 1.0,
        "retry_limit": 0,
        "expected_case_count": 1,
        "total_campaign_spend_ceiling_usd": 2.0,
    }
    manifest_path = tmp_path / "campaign.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    results = [
        _result(
            tmp_path,
            model,
            patch_hash=patch_hash,
            baseline_hash=baseline_hash,
        )
        for model in MODELS
    ]
    return manifest_path, results


def test_keyless_publication_recomputes_each_provider_and_keeps_unknown_cost_null(
    tmp_path: Path,
) -> None:
    manifest, results = _campaign(tmp_path)
    summary = build_publication(manifest, results)
    assert [provider.model for provider in summary.providers] == list(MODELS)
    assert all(provider.recall == 1.0 for provider in summary.providers)
    assert all(provider.corpus_confirmed_f1 == 1.0 for provider in summary.providers)
    assert all(provider.cost_known is False for provider in summary.providers)
    assert all(provider.cost_usd is None for provider in summary.providers)
    assert all(provider.unadjudicated == 0 for provider in summary.providers)
    assert all(provider.false_positives == 0 for provider in summary.providers)
    assert summary.conservative_reserved_spend_usd == 2.0

    summary_path, report_path = write_publication(summary, output_dir=tmp_path / "published")
    assert summary_path == tmp_path / "published" / "campaign-20260922" / "summary.json"
    assert any("operator-declared" in limitation for limitation in summary.limitations)
    report = report_path.read_text(encoding="utf-8")
    assert "Corpus-confirmed F1" in report
    assert "operator-declared" in report
    assert "does not verify the provider's execution identity" in report
    assert "make a floating alias immutable" in report
    with pytest.raises(ValueError, match="already exists"):
        write_publication(summary, output_dir=tmp_path / "published")


def test_publish_benchmark_cli_writes_campaign_directory(tmp_path: Path) -> None:
    manifest, results = _campaign(tmp_path)
    output = tmp_path / "cli-published"
    invocation = [
        "eval",
        "publish-benchmark",
        "--manifest",
        str(manifest),
        "--result",
        str(results[0]),
        "--result",
        str(results[1]),
        "--output",
        str(output),
    ]
    result = CliRunner().invoke(app, invocation)
    assert result.exit_code == 0, result.output
    assert (output / "campaign-20260922" / "summary.json").is_file()
    assert (output / "campaign-20260922" / "report.md").is_file()


def test_bench_cli_refuses_alias_to_pin_assertion(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "eval",
            "bench",
            "--model",
            "openai/floating",
            "--model-pin",
            "openai/immutable",
            "--detection-corpus",
            str(tmp_path / "unused"),
        ],
    )
    assert result.exit_code != 0
    assert "must be the exact requested model slug" in result.output


def test_bench_cli_describes_model_pin_as_operator_declared() -> None:
    result = CliRunner().invoke(app, ["eval", "bench", "--help"])
    assert result.exit_code == 0, result.output
    help_text = " ".join(result.output.replace("│", "").split())
    assert "Operator-declared model pin" in help_text
    assert "does not verify provider execution identity" in help_text
    assert "make a floating alias immutable" in help_text


def test_manifest_rejects_same_provider_agent_seeded_and_nonfinite_budget() -> None:
    base = {
        "schema_version": "1.0.0",
        "campaign_id": "campaign",
        "corpus_commit": CORPUS_COMMIT,
        "cases": [
            {
                "case_id": "case",
                "patch_path": "case/task.patch",
                "patch_sha256": "1" * 64,
                "baseline_path": "case/baseline.json",
                "baseline_sha256": "2" * 64,
                "closed_world": False,
                "label_status": "independently_adjudicated",
            }
        ],
        "detection_label_receipt_path": "labels.json",
        "detection_label_receipt_sha256": "3" * 64,
        "judge_calibration_receipt_path": "judge.json",
        "judge_calibration_receipt_sha256": "4" * 64,
        "models": ["openai/a", "openai/b"],
        "model_pins": {"openai/a": "openai/a", "openai/b": "openai/b"},
        "per_review_timeout_seconds": 1,
        "per_review_token_limit": 1,
        "per_review_cost_budget_usd": 1.0,
        "retry_limit": 0,
        "expected_case_count": 1,
        "total_campaign_spend_ceiling_usd": 2.0,
    }
    with pytest.raises(ValidationError, match="distinct providers"):
        BenchmarkCampaignManifest.model_validate(base)
    base["models"] = list(MODELS)
    base["model_pins"] = {model: model for model in MODELS}
    base["model_pins"][MODELS[0]] = "unrelated-pin"
    with pytest.raises(ValidationError, match="directly name"):
        BenchmarkCampaignManifest.model_validate(base)
    base["model_pins"] = {model: model for model in MODELS}
    base["cases"][0]["label_status"] = "agent-seeded"
    with pytest.raises(ValidationError):
        BenchmarkCampaignManifest.model_validate(base)
    base["cases"][0]["label_status"] = "independently_adjudicated"
    base["per_review_cost_budget_usd"] = float("nan")
    with pytest.raises(ValidationError):
        BenchmarkCampaignManifest.model_validate(base)


def test_old_result_without_execution_receipt_is_readable_but_ineligible(
    tmp_path: Path,
) -> None:
    manifest, results = _campaign(tmp_path)
    payload = json.loads(results[0].read_text(encoding="utf-8"))
    payload["detection"]["case_results"][0].pop("execution_receipt")
    results[0].write_text(json.dumps(payload), encoding="utf-8")
    assert BenchmarkResultSet.model_validate(payload).detection is not None
    with pytest.raises(ValueError, match="no versioned execution receipt"):
        build_publication(manifest, results)


def test_publication_rejects_pin_mismatch_hash_drift_and_raw_path_escape(
    tmp_path: Path,
) -> None:
    manifest, results = _campaign(tmp_path)
    payload = json.loads(results[0].read_text(encoding="utf-8"))
    payload["detection"]["execution_identity"]["immutable_model_pin"] = "wrong-pin"
    results[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="execution identity does not match"):
        build_publication(manifest, results)

    manifest, results = _campaign(tmp_path / "hash-drift")
    (tmp_path / "hash-drift" / "corpus" / "case-1" / "task.patch").write_text(
        "changed", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="hash drift"):
        build_publication(manifest, results)

    manifest, results = _campaign(tmp_path / "escape")
    payload = json.loads(results[0].read_text(encoding="utf-8"))
    escaped = tmp_path / "outside.json"
    escaped.write_text('{"findings": []}\n', encoding="utf-8")
    receipt = payload["detection"]["case_results"][0]["execution_receipt"]
    receipt["raw_findings_path"] = str(escaped)
    receipt["raw_findings_sha256"] = _digest(escaped)
    results[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes its run directory"):
        build_publication(manifest, results)


def test_missing_or_unvalidated_judge_receipt_blocks_publication(tmp_path: Path) -> None:
    manifest, results = _campaign(tmp_path)
    judge = tmp_path / "receipts" / "judge.json"
    payload = json.loads(judge.read_text(encoding="utf-8"))
    payload["state"] = "provisional"
    judge.write_text(json.dumps(payload), encoding="utf-8")
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_payload["judge_calibration_receipt_sha256"] = _digest(judge)
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="complete passing validation"):
        build_publication(manifest, results)

    payload["state"] = "validated"
    payload["held_out"]["passed"] = True
    payload["held_out"]["threshold_results"] = {}
    judge.write_text(json.dumps(payload), encoding="utf-8")
    manifest_payload["judge_calibration_receipt_sha256"] = _digest(judge)
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="complete passing validation"):
        build_publication(manifest, results)

    payload["state"] = "validated"
    payload["held_out"]["passed"] = False
    judge.write_text(json.dumps(payload), encoding="utf-8")
    manifest_payload["judge_calibration_receipt_sha256"] = _digest(judge)
    manifest.write_text(json.dumps(manifest_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="complete passing validation"):
        build_publication(manifest, results)


def test_nonfinite_execution_receipt_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DetectionExecutionReceipt(
            patch_sha256="1" * 64,
            baseline_sha256="2" * 64,
            raw_findings_path="raw.json",
            raw_findings_sha256="3" * 64,
            elapsed_seconds=float("inf"),
            cost_known=False,
        )


def test_raw_recomputation_rejects_fabricated_rows_and_aggregate(tmp_path: Path) -> None:
    manifest, results = _campaign(tmp_path)
    payload = json.loads(results[0].read_text(encoding="utf-8"))
    payload["detection"]["case_results"][0]["found"] = 0
    results[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match recomputed score"):
        build_publication(manifest, results)

    manifest, results = _campaign(tmp_path / "aggregate")
    payload = json.loads(results[0].read_text(encoding="utf-8"))
    payload["detection"]["aggregate"]["found"] = 0
    results[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="aggregate does not match"):
        build_publication(manifest, results)


def test_protocol_and_execution_pin_mismatches_block_publication(tmp_path: Path) -> None:
    manifest, results = _campaign(tmp_path)
    payload = json.loads(results[1].read_text(encoding="utf-8"))
    payload["pins"]["scorer_version"] = "different"
    results[1].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="one frozen evaluation protocol"):
        build_publication(manifest, results)

    manifest, results = _campaign(tmp_path / "identity")
    payload = json.loads(results[0].read_text(encoding="utf-8"))
    payload["detection"]["execution_identity"]["immutable_model_pin"] = None
    results[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="no immutable detection execution identity"):
        build_publication(manifest, results)

    manifest, results = _campaign(tmp_path / "scorer")
    for result_path in results:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        payload["pins"]["scorer_version"] = "old-scorer"
        result_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="running scorer"):
        build_publication(manifest, results)

    manifest, results = _campaign(tmp_path / "slack")
    for result_path in results:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        payload["pins"]["line_slack"] = -1
        result_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="must not be negative"):
        build_publication(manifest, results)


def test_reported_cost_above_operator_limit_is_rejected(tmp_path: Path) -> None:
    manifest, results = _campaign(tmp_path)
    payload = json.loads(results[0].read_text(encoding="utf-8"))
    receipt = payload["detection"]["case_results"][0]["execution_receipt"]
    receipt["cost_known"] = True
    receipt["cost_usd"] = 1.5
    results[0].write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="per-review ceiling"):
        build_publication(manifest, results)


def test_human_receipt_prevents_manifest_from_flipping_closed_world(tmp_path: Path) -> None:
    manifest, results = _campaign(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["cases"][0]["closed_world"] = True
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="case hashes do not match"):
        build_publication(manifest, results)
