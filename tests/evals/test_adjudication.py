"""Configurable eval-corpus adjudication (#736, #738).

Two properties carry these tests. Configuration decides who *may* adjudicate,
and provenance decides what a label *entitles* a caller to claim — enabling an
adjudicator must never by itself upgrade a calibration claim. And no
configuration may permit a model to adjudicate labels it produced, because that
is the circularity the corpus already suffers from.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.config.settings import AdjudicationSettings, RepoSettings
from mergecraft.evals.adjudication import (
    AdjudicationRecord,
    AdjudicatorNotApproved,
    SelfAdjudicationRefused,
    approved_kinds,
    assert_independent,
    calibration_status,
    provenance_for,
    resolve_adjudicator,
    tier_for_provenance,
)
from mergecraft.evals.live_run import (
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


def _settings(**kinds: dict[str, object]) -> AdjudicationSettings:
    return AdjudicationSettings.model_validate({"adjudicators": kinds})


class TestApproval:
    """Configuration is the only thing that lets an adjudicator run."""

    def test_default_approves_human_only(self) -> None:
        defaults = RepoSettings().adjudication
        assert approved_kinds(defaults.adjudicators) == frozenset({"human"})

    def test_unapproved_kind_raises_and_names_the_config_key(self) -> None:
        defaults = RepoSettings().adjudication
        with pytest.raises(AdjudicatorNotApproved, match=r"adjudication\.adjudicators\.llm"):
            resolve_adjudicator("llm", settings=defaults.adjudicators)

    def test_enabling_a_kind_approves_it_and_returns_its_tier(self) -> None:
        cfg = _settings(llm={"enabled": True, "independence": "model"})
        assert resolve_adjudicator("llm", settings=cfg.adjudicators) == "model"

    def test_jev_is_approvable_like_any_other_kind(self) -> None:
        cfg = _settings(jev={"enabled": True, "independence": "model"})
        assert resolve_adjudicator("jev", settings=cfg.adjudicators) == "model"

    def test_absent_block_approves_nothing(self) -> None:
        assert approved_kinds(None) == frozenset()

    def test_unknown_kind_is_a_configuration_error(self) -> None:
        with pytest.raises(ValueError, match="unknown adjudicator kind"):
            _settings(oracle={"enabled": True})


class TestSelfAdjudication:
    """Refused regardless of configuration — this is not an approval question."""

    def test_same_model_producing_and_adjudicating_is_refused(self) -> None:
        record = AdjudicationRecord(adjudicated_by="llm", model="judge-1", produced_by="judge-1")
        with pytest.raises(SelfAdjudicationRefused, match="produced this label"):
            assert_independent(record)

    def test_enabling_the_adjudicator_does_not_waive_the_refusal(self) -> None:
        cfg = _settings(llm={"enabled": True, "independence": "model"})
        assert resolve_adjudicator("llm", settings=cfg.adjudicators) == "model"
        record = AdjudicationRecord(adjudicated_by="llm", model="judge-1", produced_by="judge-1")
        with pytest.raises(SelfAdjudicationRefused):
            assert_independent(record)

    def test_different_models_are_allowed(self) -> None:
        record = AdjudicationRecord(adjudicated_by="llm", model="judge-2", produced_by="judge-1")
        assert_independent(record)

    def test_unknown_producer_does_not_block(self) -> None:
        record = AdjudicationRecord(adjudicated_by="human", model="", produced_by="")
        assert_independent(record)


class TestProvenance:
    """Provenance is derived from the record, never asserted by hand."""

    @pytest.mark.parametrize(
        ("kind", "expected"),
        [("human", "human"), ("jev", "jev-adjudicated"), ("llm", "llm-adjudicated")],
    )
    def test_provenance_is_derived_from_the_adjudicator(self, kind: str, expected: str) -> None:
        record = AdjudicationRecord.model_validate({"adjudicated_by": kind})
        assert provenance_for(record) == expected

    @pytest.mark.parametrize(
        ("provenance", "tier"),
        [
            ("human", "independent"),
            ("jev-adjudicated", "model"),
            ("llm-adjudicated", "model"),
            ("agent-seeded", "none"),
            ("", "none"),
        ],
    )
    def test_known_provenance_maps_to_its_tier(self, provenance: str, tier: str) -> None:
        assert tier_for_provenance(provenance) == tier

    def test_unrecognised_provenance_falls_to_none_not_through(self) -> None:
        assert tier_for_provenance("hand-wavy") == "none"


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
            "adjudication:\n"
            "  adjudicators:\n"
            "    llm:\n"
            "      enabled: true\n"
            "      independence: model\n"
            f"  requireForCalibration: {bar}\n",
            encoding="utf-8",
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


class TestAdjudicateCommand:
    """The production label-writing path enforces approval and independence.

    Without a writer that calls ``adjudicate_label``, ``enabled`` guards
    nothing and the self-adjudication ban is advisory. These drive the CLI.
    """

    @staticmethod
    def _baseline(tmp_path: Path, provenance: str = "agent-seeded") -> Path:
        path = tmp_path / "baseline.json"
        path.write_text(
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
        return path

    @staticmethod
    def _enable_llm(tmp_path: Path) -> None:
        config_dir = tmp_path / ".mergecraft"
        config_dir.mkdir(exist_ok=True)
        (config_dir / "config.yaml").write_text(
            "adjudication:\n"
            "  adjudicators:\n"
            "    llm:\n"
            "      enabled: true\n"
            "      independence: model\n",
            encoding="utf-8",
        )

    def test_unapproved_adjudicator_cannot_write_a_label(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "llm"]
        )
        assert result.exit_code != 0
        assert json.loads(baseline.read_text())[0]["provenance"] == "agent-seeded"

    def test_approved_adjudicator_writes_derived_provenance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "human"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(baseline.read_text())[0]["provenance"] == "human"

    def test_enabling_llm_in_config_lets_it_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        self._enable_llm(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app,
            ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "llm", "--model", "j1"],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(baseline.read_text())[0]["provenance"] == "llm-adjudicated"

    def test_self_adjudication_refused_even_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        self._enable_llm(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app,
            [
                "eval",
                "adjudicate",
                str(baseline),
                "--id",
                "1",
                "--by",
                "llm",
                "--model",
                "j1",
                "--produced-by",
                "j1",
            ],
        )
        assert result.exit_code != 0
        assert json.loads(baseline.read_text())[0]["provenance"] == "agent-seeded"

    def test_unknown_issue_id_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "nope", "--by", "human"]
        )
        assert result.exit_code != 0
        assert json.loads(baseline.read_text())[0]["provenance"] == "agent-seeded"


class TestBenchmarkChainThreadsTheBar:
    """Every hop from the benchmark CLI down to scoring must carry the bar."""

    @pytest.mark.parametrize("func", [run_live_detection, run_detection, run_full_benchmark])
    def test_each_hop_accepts_required_provenance(self, func: Callable[..., object]) -> None:
        signature = inspect.signature(func)
        assert "required_provenance" in signature.parameters
