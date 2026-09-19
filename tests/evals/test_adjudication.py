"""Provenance tiers and the calibration bar (#736).

One property carries these tests: scores are reported for any corpus, but the
word *calibrated* is withheld unless every label clears the configured bar, and
no configuration can lower that bar to nothing.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.config.settings import AdjudicationSettings, RepoSettings
from mergecraft.evals.adjudication import (
    calibration_status,
)
from mergecraft.evals.benchmark import DetectionCase, DetectionMetrics
from mergecraft.evals.live_run import (
    ReviewRunFailed,
    run_detection,
    run_full_benchmark,
    run_live_detection,
)
from mergecraft.evals.scoring import (
    BaselineIssue,
    ReportedFinding,
    ScoreReport,
    format_report,
    score_findings,
)


class TestCalibrationStatus:
    """What the labels entitle a caller to claim."""

    def test_one_agent_seeded_row_sinks_the_whole_corpus(self) -> None:
        status = calibration_status(["human", "human", "agent-seeded"])
        assert status.eligible is False
        assert "1 of 3" in status.reason

    def test_all_human_labels_are_eligible_at_the_default_bar(self) -> None:
        assert calibration_status(["human", "human"]).eligible is True

    def test_model_labels_fail_the_independent_bar(self) -> None:
        assert calibration_status(["llm-adjudicated"]).eligible is False

    def test_model_labels_pass_when_the_bar_is_lowered(self) -> None:
        status = calibration_status(["llm-adjudicated", "jev-adjudicated"], required="model")
        assert status.eligible is True

    def test_empty_label_set_is_never_eligible(self) -> None:
        status = calibration_status([])
        assert status.eligible is False
        assert status.reason == "no labels to score"

    def test_counts_partition_every_label(self) -> None:
        status = calibration_status(["human", "llm-adjudicated", "agent-seeded", "human"])
        assert status.counts == {"independent": 2, "model": 1, "none": 1}

    def test_default_bar_is_independent(self) -> None:
        assert RepoSettings().adjudication.require_for_calibration == "independent"


class TestScoringIntegration:
    """Scoring reports calibration eligibility without withholding numbers."""

    @staticmethod
    def _issue(identifier: str, provenance: str) -> BaselineIssue:
        return BaselineIssue(
            id=identifier, path="a.py", start_line=1, end_line=2, provenance=provenance
        )

    @staticmethod
    def _finding() -> ReportedFinding:
        return ReportedFinding(path="a.py", start_line=1, end_line=2)

    def test_agent_seeded_corpus_still_reports_recall(self) -> None:
        report = score_findings([self._issue("1", "agent-seeded")], [self._finding()])
        assert report.recall == 1.0

    def test_agent_seeded_corpus_is_not_calibrated(self) -> None:
        report = score_findings([self._issue("1", "agent-seeded")], [self._finding()])
        assert report.calibration is not None
        assert report.calibration.eligible is False

    def test_human_corpus_is_calibrated(self) -> None:
        report = score_findings([self._issue("1", "human")], [self._finding()])
        assert report.calibration is not None
        assert report.calibration.eligible is True

    def test_lowering_the_bar_admits_model_labels(self) -> None:
        report = score_findings(
            [self._issue("1", "llm-adjudicated")],
            [self._finding()],
            required_provenance="model",
        )
        assert report.calibration is not None
        assert report.calibration.eligible is True

    def test_format_report_states_the_calibration_verdict(self) -> None:
        rendered = format_report(
            score_findings([self._issue("1", "agent-seeded")], [self._finding()])
        )
        assert "NOT calibrated" in rendered

    def test_format_report_says_calibrated_for_independent_labels(self) -> None:
        rendered = format_report(score_findings([self._issue("1", "human")], [self._finding()]))
        assert "calibration      : calibrated" in rendered

    def test_report_predating_the_field_is_not_read_as_eligible(self) -> None:
        report = ScoreReport(
            total_issues=0,
            total_reported=0,
            matches=[],
            missed_issue_ids=[],
            unmatched_finding_indexes=[],
        )
        assert report.calibration is None


class TestConfigReachesScoring:
    """The config block must change real behaviour, not merely validate.

    A settings field no production path reads is worse than no field: it
    advertises a policy the tool does not apply. These drive the operator
    entry points through a real ``.mergecraft/config.yaml``.
    """

    @staticmethod
    def _write_corpus(tmp_path: Path, provenance: str) -> tuple[Path, Path]:
        expected = tmp_path / "baseline.json"
        expected.write_text(
            json.dumps(
                [
                    {
                        "id": "1",
                        "path": "a.py",
                        "startLine": 1,
                        "endLine": 2,
                        "provenance": provenance,
                    }
                ]
            ),
            encoding="utf-8",
        )
        actual = tmp_path / "findings.json"
        actual.write_text(
            json.dumps([{"path": "a.py", "startLine": 1, "endLine": 2}]), encoding="utf-8"
        )
        return actual, expected

    @staticmethod
    def _write_config(tmp_path: Path, bar: str) -> None:
        config_dir = tmp_path / ".mergecraft"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "config.yaml").write_text(
            f"adjudication:\n  requireForCalibration: {bar}\n", encoding="utf-8"
        )

    def test_default_bar_rejects_model_labels_through_the_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        actual, expected = self._write_corpus(tmp_path, "llm-adjudicated")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["eval", "score", str(actual), str(expected)])
        assert result.exit_code == 0, result.output
        assert "NOT calibrated" in result.output

    def test_lowering_the_bar_in_config_changes_the_cli_verdict(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        actual, expected = self._write_corpus(tmp_path, "llm-adjudicated")
        self._write_config(tmp_path, "model")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["eval", "score", str(actual), str(expected)])
        assert result.exit_code == 0, result.output
        assert "NOT calibrated" not in result.output
        assert "calibrated" in result.output

    def test_live_detection_accepts_and_applies_the_bar(self) -> None:
        signature = inspect.signature(run_live_detection)
        assert "required_provenance" in signature.parameters
        assert signature.parameters["required_provenance"].default == "independent"


class TestBenchmarkChainThreadsTheBar:
    """Every hop from the benchmark CLI down to scoring must carry the bar."""

    @pytest.mark.parametrize("func", [run_live_detection, run_detection, run_full_benchmark])
    def test_each_hop_accepts_required_provenance(self, func: Callable[..., object]) -> None:
        signature = inspect.signature(func)
        assert "required_provenance" in signature.parameters


class TestBenchmarkCarriesCalibration:
    """A published benchmark artifact must carry its calibration verdict."""

    def test_detection_metrics_has_a_calibration_field(self) -> None:
        assert "calibration" in DetectionMetrics.model_fields

    def test_field_defaults_to_none_so_older_artifacts_are_not_eligible(self) -> None:
        assert DetectionMetrics.model_fields["calibration"].default is None

    def test_live_detection_folds_case_provenance_into_the_metrics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        case_dir = tmp_path / "case-1"
        case_dir.mkdir()
        baseline = case_dir / "baseline.json"
        baseline.write_text(
            json.dumps(
                [
                    {
                        "id": "1",
                        "path": "a.py",
                        "startLine": 1,
                        "endLine": 2,
                        "provenance": "agent-seeded",
                    }
                ]
            ),
            encoding="utf-8",
        )
        patch = case_dir / "change.patch"
        patch.write_text("", encoding="utf-8")
        case = DetectionCase(
            case_id="case-1",
            patch_path=patch,
            baseline_path=baseline,
            closed_world=False,
        )
        metrics = run_live_detection(
            [case],
            provider="p",
            model="m",
            review_fn=lambda _case: [{"path": "a.py", "startLine": 1, "endLine": 2}],
            results_dir=tmp_path / "results",
        )
        assert metrics.calibration is not None
        assert metrics.calibration.eligible is False
        assert metrics.calibration.counts["none"] == 1


class TestScoreJsonCarriesCalibration:
    """The --json path must not drop what the human path states."""

    @staticmethod
    def _corpus(tmp_path: Path, provenance: str) -> tuple[Path, Path]:
        expected = tmp_path / "baseline.json"
        expected.write_text(
            json.dumps(
                [
                    {
                        "id": "1",
                        "path": "a.py",
                        "startLine": 1,
                        "endLine": 2,
                        "provenance": provenance,
                    }
                ]
            ),
            encoding="utf-8",
        )
        actual = tmp_path / "findings.json"
        actual.write_text(
            json.dumps([{"path": "a.py", "startLine": 1, "endLine": 2}]), encoding="utf-8"
        )
        return actual, expected

    def test_ineligible_corpus_is_marked_in_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        actual, expected = self._corpus(tmp_path, "agent-seeded")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["eval", "score", str(actual), str(expected), "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["calibration"]["eligible"] is False

    def test_eligible_corpus_is_marked_in_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        actual, expected = self._corpus(tmp_path, "human")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["eval", "score", str(actual), str(expected), "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["calibration"]["eligible"] is True


class TestNoBarCannotBeConfigured:
    """`requireForCalibration` must not be able to admit unadjudicated labels."""

    def test_config_rejects_none_as_a_bar(self) -> None:
        with pytest.raises(ValidationError):
            AdjudicationSettings.model_validate({"requireForCalibration": "none"})

    def test_calibration_status_refuses_a_none_bar_programmatically(self) -> None:
        status = calibration_status(["agent-seeded"], required="none")
        assert status.eligible is False
        assert "not a calibration bar" in status.reason

    def test_none_bar_does_not_admit_unknown_provenance_either(self) -> None:
        assert calibration_status(["made-up-string"], required="none").eligible is False

    def test_config_to_cli_agent_seeded_stays_uncalibrated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The end-to-end regression: no config makes the shipped corpus calibrated."""
        expected = tmp_path / "baseline.json"
        expected.write_text(
            json.dumps(
                {
                    "closed_world": False,
                    "issues": [
                        {
                            "id": "1",
                            "path": "a.py",
                            "startLine": 1,
                            "endLine": 2,
                            "provenance": "agent-seeded",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        actual = tmp_path / "findings.json"
        actual.write_text(
            json.dumps([{"path": "a.py", "startLine": 1, "endLine": 2}]), encoding="utf-8"
        )
        config_dir = tmp_path / ".mergecraft"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "adjudication:\n  requireForCalibration: model\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(app, ["eval", "score", str(actual), str(expected)])
        assert result.exit_code == 0, result.output
        assert "NOT calibrated" in result.output


class TestFailedCaseStillCounts:
    """A failed review must not remove its labels from the corpus verdict."""

    @staticmethod
    def _case(tmp_path: Path, case_id: str, provenance: str) -> DetectionCase:
        case_dir = tmp_path / case_id
        case_dir.mkdir()
        baseline = case_dir / "baseline.json"
        baseline.write_text(
            json.dumps(
                {
                    "closed_world": False,
                    "issues": [
                        {
                            "id": f"{case_id}-1",
                            "path": "a.py",
                            "startLine": 1,
                            "endLine": 2,
                            "provenance": provenance,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        patch = case_dir / "change.patch"
        patch.write_text("", encoding="utf-8")
        return DetectionCase(
            case_id=case_id, patch_path=patch, baseline_path=baseline, closed_world=False
        )

    def test_agent_seeded_label_on_a_failed_case_still_sinks_the_verdict(
        self, tmp_path: Path
    ) -> None:
        good = self._case(tmp_path, "ok", "human")
        bad = self._case(tmp_path, "boom", "agent-seeded")

        def review(case: DetectionCase) -> list[dict[str, object]]:
            if case.case_id == "boom":
                raise ReviewRunFailed("simulated")
            return [{"path": "a.py", "startLine": 1, "endLine": 2}]

        metrics = run_live_detection(
            [good, bad],
            provider="p",
            model="m",
            review_fn=review,
            results_dir=tmp_path / "results",
        )
        assert metrics.failed_case_ids == ["boom"]
        assert metrics.calibration is not None
        assert metrics.calibration.counts["none"] == 1
        assert metrics.calibration.eligible is False
