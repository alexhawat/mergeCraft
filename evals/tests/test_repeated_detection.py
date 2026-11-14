"""Exercise the campaign with synthetic inputs and no live credentials."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from evals.repeated_detection import context_sha256, run_campaign, summarize_campaign
from tests.evals.test_benchmark_publication_contract import _campaign

from mergecraft.evals.benchmark import run_structural_replay
from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION
from mergecraft.review.offline_result import OfflineReviewResult
from mergecraft.run_outcome import RunOutcome


def _sha(path: Path) -> str:
    """Digest one fixture artifact."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    """Write one JSON fixture artifact."""
    path.write_text(json.dumps(value), encoding="utf-8")


def _protocol(tmp_path: Path) -> tuple[Path, list[str]]:
    """Create separate synthetic defect and clean cases plus test-only receipts."""
    manifest_path, _ = _campaign(tmp_path)
    manifest = json.loads(manifest_path.read_bytes())
    cases = manifest["cases"]
    label_path = tmp_path / manifest["detection_label_receipt_path"]
    labels = json.loads(label_path.read_bytes())
    pins: dict[str, str] = {}
    for number in (1, 2, 3):
        case_id = f"case-{number}"
        folder = tmp_path / "corpus" / case_id
        repo = folder / "repo"
        repo.mkdir(parents=True)
        (repo / "context.txt").write_text(f"case {number}", encoding="utf-8")
        patch, baseline = folder / "task.patch", folder / "baseline.json"
        patch.write_text(f"test-only patch {number}", encoding="utf-8")
        issues = (
            []
            if number == 3
            else [
                {
                    "id": case_id,
                    "path": "a.py",
                    "start_line": 1,
                    "end_line": 1,
                    "provenance": "human",
                }
            ]
        )
        _write(baseline, {"closed_world": True, "issues": issues})
        case = {
            "case_id": case_id,
            "patch_path": patch.relative_to(tmp_path).as_posix(),
            "baseline_path": baseline.relative_to(tmp_path).as_posix(),
            "patch_sha256": _sha(patch),
            "baseline_sha256": _sha(baseline),
            "closed_world": True,
            "label_status": "independently_adjudicated",
        }
        cases[number - 1 : number] = [case]
        labels["case_hashes"][case_id] = {
            key: case[key] for key in ("patch_sha256", "baseline_sha256", "closed_world")
        }
        pins[case_id] = context_sha256(repo)

    _write(label_path, labels)
    manifest["detection_label_receipt_sha256"] = _sha(label_path)
    manifest["expected_case_count"] = 3
    manifest["total_campaign_spend_ceiling_usd"] = 18
    replay = run_structural_replay()
    judge_pin = replay.pins.judge_pins["claude"]
    judge_path = tmp_path / manifest["judge_calibration_receipt_path"]
    judge = json.loads(judge_path.read_bytes())
    judge["candidate_id"] = (
        f"claude/{judge_pin['model']}@judge-{judge_pin['judge_version']}"
        f"/rubric-{judge_pin['rubric_version']}/prompt-111111111111/policy-policy-v1"
    )
    _write(judge_path, judge)
    manifest["judge_calibration_receipt_sha256"] = _sha(judge_path)
    _write(manifest_path, manifest)
    protocol = tmp_path / "protocol.json"
    _write(
        protocol,
        {
            "schema_version": "1.0.0",
            "campaign_manifest": manifest_path.name,
            "campaign_sha256": _sha(manifest_path),
            "split": "held-out",
            "repetitions": 3,
            "context_sha256": pins,
        },
    )
    models: list[str] = manifest["models"]
    return protocol, models


@pytest.mark.parametrize(
    "failure",
    [None, "campaign-cap", "partial-review-cap", "scope", "altered-patch", "retry", "round-budget"],
    ids=[
        "scored",
        "spent-ceiling",
        "partial-review-overrun",
        "scope-reduction",
        "filtered-patch",
        "hidden-retry",
        "scaled-round-budget",
    ],
)
def test_campaign_reuses_receipts_and_scores_by_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    """Execute the real runner and scorer with an offline-engine boundary fake."""
    import mergecraft.offline_review

    protocol, models = _protocol(tmp_path)
    monkeypatch.setattr("evals.repeated_detection.has_credentials_for_slug", lambda _slug: True)
    monkeypatch.setattr("mergecraft.evals.benchmark.git_tracked_tree_clean", lambda: True)
    seen: dict[tuple[str, int], int] = {}
    if failure == "round-budget":
        repo = tmp_path / "corpus/case-1/repo"
        config = repo / ".mergecraft/config.yaml"
        config.parent.mkdir()
        config.write_text("review:\n  roundBudgets:\n    multipliers: [1.5]\n", encoding="utf-8")
        payload = json.loads(protocol.read_bytes())
        payload["context_sha256"]["case-1"] = context_sha256(repo)
        _write(protocol, payload)

    async def review(**kwargs: Any) -> OfflineReviewResult:
        """Replace only the offline review boundary that would invoke a provider."""
        return record_review(kwargs)

    def record_review(kwargs: dict[str, Any]) -> OfflineReviewResult:
        """Check what reaches the boundary and persist synthetic provider output."""
        cwd = Path(kwargs["cwd"])
        number = int((cwd / "context.txt").read_text(encoding="utf-8")[-1])
        assert sorted(path.name for path in cwd.iterdir()) == ["context.txt"]
        assert kwargs["diff_file"].read_text(encoding="utf-8") == f"test-only patch {number}"
        assert os.environ["MERGECRAFT_TOKEN_BUDGET"] == "12000"
        assert os.environ["MERGECRAFT_COST_BUDGET_USD"] == "1.0"
        model = kwargs["model"]
        assert model in models
        key = (model, number)
        attempt = seen.get(key, 0)
        seen[key] = attempt + 1
        finding = {"path": "a.py", "start_line": 1, "end_line": 1, "message": "test-only"}
        findings = [finding, {**finding, "message": "paraphrase"}] if number == 1 else []
        if number == 2 and attempt == 0:
            findings = [finding]
        if number == 2 and attempt != 0:
            findings = [{**finding, "path": "wrong.py"}]
        amount = 0.12
        if failure == "campaign-cap":
            amount = 20.0
        if failure == "partial-review-cap" and number == 1:
            amount = 1.25
        complete = model == models[0] and failure != "partial-review-cap"
        packet = {
            "schema_version": PACKET_SCHEMA_VERSION,
            "change_id": "test-only",
            "agent": {
                "id": "test-only",
                "version": "test-only",
                "model": model,
                "requested_model": model,
                "executed_model": model,
                "provider": model.split("/")[0],
            },
            "files_changed": [],
            "findings": [],
            "deterministic_checks": [],
            "run_metrics": {
                "tool_calls": 0,
                "read_tool_calls": 0,
                "read_tool_turns": 0,
                "distinct_files_read": 0,
                "diff_lines": 0,
                "diff_added_lines": 0,
                "diff_deleted_lines": 0,
                "cost_availability": "available" if complete else "partial",
                "recorded_cost_usd": amount,
            },
        }
        _write(kwargs["evidence_packet_path"], packet)
        _write(kwargs["json_path"], {"findings": findings})
        tracing_cli = kwargs["tracing_cli"]
        traces = Path(tracing_cli[tracing_cli.index("--trace-dir") + 1])
        traces.mkdir()
        attempts = (
            [("retryable", 1), ("ok", 2)] if failure == "retry" and number == 1 else [("ok", 1)]
        )
        trace_rows = [
            json.dumps(
                {
                    "kind": "agent.attempt",
                    "status": status,
                    "attrs": {"model.attempt_number": number, "model.id": model},
                }
            )
            for status, number in attempts
        ]
        (traces / "trace.jsonl").write_text("\n".join(trace_rows), encoding="utf-8")
        reviewed = kwargs["diff_file"].with_name("reviewed.patch")
        patch = kwargs["diff_file"].read_text(encoding="utf-8")
        reviewed.write_text(
            "filtered" if failure == "altered-patch" and number == 1 else patch + "\n",
            encoding="utf-8",
        )
        return OfflineReviewResult(
            success=True,
            diff_path=str(reviewed),
            outcome=RunOutcome.inconclusive
            if failure == "scope" and number == 1
            else RunOutcome.passed,
        )

    monkeypatch.setattr(mergecraft.offline_review, "run_offline_diff_review", review)
    results = tmp_path / "results"
    if failure == "campaign-cap":
        with pytest.raises(ValueError, match="campaign spend ceiling reached"):
            run_campaign(protocol, results)
        assert seen == {(models[0], 1): 1}
        result = json.loads((results / "repeat-001-anthropic.json").read_bytes())
        assert result["detection"]["cases_failed"] == 3
        return
    run_campaign(protocol, results)
    if failure is not None:
        with pytest.raises(ValueError, match="partial or failed"):
            summarize_campaign(protocol, results)
        expected_message = {
            "partial-review-cap": "reported cost exceeds the per-review ceiling",
            "scope": "review did not complete",
            "altered-patch": "reviewed diff does not match the approved patch",
            "retry": "exactly one successful pinned model attempt",
            "round-budget": "configured round budget changes review limits",
        }
        if failure == "partial-review-cap":
            receipt = results / "repeat-001-anthropic.receipt.json"
            assert json.loads(receipt.read_bytes())["recorded_costs"]["case-1"] == 1.25
        result = json.loads((results / "repeat-001-anthropic.json").read_bytes())
        if failure == "round-budget":
            assert set(seen) == {(model, case) for model in models for case in (2, 3)}
        assert expected_message[failure] in result["detection"]["failed_case_errors"]["case-1"]
        return
    report = summarize_campaign(protocol, results)
    assert len(seen) == 6
    assert set(seen.values()) == {3}
    first, second = report["providers"]
    assert first["model"] == models[0]
    assert second["model"] == models[1]
    assert first["recall"] == pytest.approx(2 / 3)
    assert first["precision"] == pytest.approx(2 / 3)
    assert first["recall_interval_95"] == pytest.approx((1 / 3, 1))
    assert first["recall_run_stdev"] == pytest.approx((1 / 12) ** 0.5)
    assert first["clean_case_fp_rate"] == 0
    assert first["median_cost_usd"] == 0.12
    assert second["median_cost_usd"] is None
    assert second["known_spend_usd"] == pytest.approx(9 * 0.12)
    assert second["cost_partial_reviews"] == 9

    command = [
        "make",
        "--no-print-directory",
        "-C",
        "evals",
        "detection-summarize",
        f"PROTOCOL={protocol}",
        f"RESULTS={results}",
        f"UV_PROJECT_ENVIRONMENT={sys.prefix}",
    ]
    stdout = subprocess.check_output(command, text=True, timeout=30)
    assert json.loads(stdout) == json.loads(json.dumps(report))

    payload = json.loads(protocol.read_bytes())
    context = tmp_path / "corpus/case-1/repo"
    (context / "context.txt").write_text("different base tree", encoding="utf-8")
    payload["context_sha256"]["case-1"] = context_sha256(context)
    different = protocol.with_name("different.json")
    _write(different, payload)
    with pytest.raises(ValueError, match="run receipt does not match the repeated campaign"):
        summarize_campaign(different, results)
    (context / "context.txt").write_text("case 1", encoding="utf-8")

    cost_receipt = results / "repeat-001-anthropic.receipt.json"
    original_receipt = cost_receipt.read_bytes()
    mismatched_cost = json.loads(original_receipt)
    mismatched_cost["recorded_costs"]["case-1"] = 0.13
    _write(cost_receipt, mismatched_cost)
    with pytest.raises(ValueError, match="case case-1 recorded cost disagrees with receipt"):
        summarize_campaign(protocol, results)
    cost_receipt.write_bytes(original_receipt)

    raw_path = next(results.glob("raw-findings/*/case-1.json"))
    raw_path.write_text('{"findings": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="raw findings hash drift"):
        summarize_campaign(protocol, results)


@pytest.mark.parametrize(
    "name",
    [".git", ".env", ".env.local", ".env.production", ".env.test"],
    ids=["git-metadata", "dotenv", "local-dotenv", "production-dotenv", "test-dotenv"],
)
def test_context_rejects_metadata_and_dotenv_files(tmp_path: Path, name: str) -> None:
    """Reject these names anywhere in a repository snapshot."""
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "ordinary.txt").write_text("test-only file", encoding="utf-8")
    (nested / name).write_text("test-only metadata", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported repository context entry") as caught:
        context_sha256(tmp_path)
    assert str(caught.value).endswith(f"nested/{name}")


def test_context_rejects_links_and_trees_without_files(tmp_path: Path) -> None:
    """A directory tree needs real files and cannot point outside its root."""
    root = tmp_path / "repo"
    (root / "nested").mkdir(parents=True)
    with pytest.raises(ValueError, match="empty repository context"):
        context_sha256(root)

    external = tmp_path / "outside.txt"
    external.write_text("test-only context", encoding="utf-8")
    link = root / "nested" / "link.txt"
    link.symlink_to(external)
    with pytest.raises(ValueError, match=r"unsupported repository context entry: nested/link\.txt"):
        context_sha256(root)


def test_missing_provider_credentials_refuse_the_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require credentials for all campaign models before creating the run directory."""
    protocol, models = _protocol(tmp_path)
    monkeypatch.setattr("mergecraft.evals.benchmark.git_tracked_tree_clean", lambda: True)
    monkeypatch.setattr(
        "evals.repeated_detection.has_credentials_for_slug", lambda model: model == models[0]
    )
    results = tmp_path / "results"
    with pytest.raises(
        ValueError, match="live credentials must be available for each pinned model"
    ):
        run_campaign(protocol, results)
    assert not results.exists()


def test_changed_context_is_refused_before_review(tmp_path: Path) -> None:
    """A context changed after the protocol was frozen is ineligible to run."""
    protocol, _ = _protocol(tmp_path)
    path = tmp_path / "corpus/case-1/repo/context.txt"
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="context hash drift"):
        run_campaign(protocol, tmp_path / "results")
    assert not (tmp_path / "results").exists()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("open-world", "requires a closed-world baseline"),
        ("unadjudicated", "needs valid, distinct human-adjudicated issues"),
        ("reservation", "repeat reservation exceeds the campaign spend ceiling"),
    ],
    ids=["open-world-defect", "agent-seeded-label", "insufficient-reservation"],
)
def test_ineligible_protocol_is_refused_before_review(
    tmp_path: Path, change: str, message: str
) -> None:
    """Passing receipt integrity alone cannot make the scheduled corpus eligible."""
    protocol_path, _ = _protocol(tmp_path)
    protocol = json.loads(protocol_path.read_bytes())
    manifest_path = tmp_path / protocol["campaign_manifest"]
    manifest = json.loads(manifest_path.read_bytes())
    if change == "reservation":
        manifest["total_campaign_spend_ceiling_usd"] = 6
    else:
        case = manifest["cases"][0]
        baseline_path = tmp_path / case["baseline_path"]
        baseline = json.loads(baseline_path.read_bytes())
        label_path = tmp_path / manifest["detection_label_receipt_path"]
        labels = json.loads(label_path.read_bytes())
        if change == "open-world":
            labels["case_hashes"][case["case_id"]]["closed_world"] = False
            case["closed_world"] = baseline["closed_world"] = False
        else:
            baseline["issues"][0]["provenance"] = "agent-seeded"
        _write(baseline_path, baseline)
        case["baseline_sha256"] = _sha(baseline_path)
        labels["case_hashes"][case["case_id"]]["baseline_sha256"] = case["baseline_sha256"]
        _write(label_path, labels)
        manifest["detection_label_receipt_sha256"] = _sha(label_path)
    _write(manifest_path, manifest)
    protocol["campaign_sha256"] = _sha(manifest_path)
    _write(protocol_path, protocol)
    with pytest.raises(ValueError, match=message):
        run_campaign(protocol_path, tmp_path / "results")
    assert not (tmp_path / "results").exists()
