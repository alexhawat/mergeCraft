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
from pydantic import ValidationError
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
from mergecraft.evals.benchmark import DetectionCase, DetectionMetrics
from mergecraft.evals.corpora import CorpusCase
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
    load_baseline_issues,
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

    def test_existing_corpus_rows_default_to_unadjudicated(self) -> None:
        case = CorpusCase.model_validate(
            {
                "id": "golden-1",
                "title": "existing row",
                "language": "python",
                "framework": "django",
            }
        )
        assert case.provenance == ""
        assert case.adjudication is None


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

    def test_human_needs_no_model_identity(self) -> None:
        assert_independent(AdjudicationRecord(adjudicated_by="human", model="", produced_by=""))

    @pytest.mark.parametrize(
        ("model", "produced_by", "case"),
        [("judge-1", "", "producer omitted"), ("", "judge-1", "adjudicator omitted")],
    )
    def test_model_adjudication_fails_closed_on_missing_identity(
        self, model: str, produced_by: str, case: str
    ) -> None:
        """Omitting an argument must not be a way past the independence check."""
        record = AdjudicationRecord(adjudicated_by="llm", model=model, produced_by=produced_by)
        with pytest.raises(SelfAdjudicationRefused, match="auditable identities"):
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
        """Envelope shape — every baseline under ``evals/bench/`` looks like this."""
        path = tmp_path / "baseline.json"
        path.write_text(
            json.dumps(
                {
                    "closed_world": False,
                    "issues": [
                        {
                            "id": "1",
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
        return path

    @staticmethod
    def _rows(baseline: Path) -> list[dict[str, object]]:
        payload = json.loads(baseline.read_text())
        return payload["issues"] if isinstance(payload, dict) else payload

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
        before = baseline.read_bytes()
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "llm"]
        )
        assert result.exit_code != 0
        assert baseline.read_bytes() == before

    def test_approved_adjudicator_writes_derived_provenance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "human"]
        )
        assert result.exit_code == 0, result.output
        assert self._rows(baseline)[0]["provenance"] == "human"

    def test_enabling_llm_in_config_lets_it_write(
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
                "judge-2",
                "--produced-by",
                "judge-1",
            ],
        )
        assert result.exit_code == 0, result.output
        assert self._rows(baseline)[0]["provenance"] == "llm-adjudicated"

    def test_model_adjudicator_without_producer_is_refused_through_the_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Omitting --produced-by must not be a way past the independence check."""
        baseline = self._baseline(tmp_path)
        self._enable_llm(tmp_path)
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app,
            ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "llm", "--model", "j1"],
        )
        assert result.exit_code != 0
        assert self._rows(baseline)[0]["provenance"] == "agent-seeded"

    def test_self_adjudication_refused_even_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        before = baseline.read_bytes()
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
        assert baseline.read_bytes() == before

    def test_record_round_trips_so_independence_is_auditable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`llm-adjudicated` is unfalsifiable unless the identities persist."""
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
                "judge-2",
                "--produced-by",
                "judge-1",
            ],
        )
        assert result.exit_code == 0, result.output
        row = self._rows(baseline)[0]
        record = row["adjudication"]
        assert record["adjudicated_by"] == "llm"
        assert record["model"] == "judge-2"
        assert record["produced_by"] == "judge-1"
        assert record["independence"] == "model"
        assert record["at"]
        # The persisted identities must show the check could actually pass.
        assert record["model"] != record["produced_by"]

    def test_persisted_record_does_not_break_baseline_loading(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        monkeypatch.chdir(tmp_path)
        CliRunner().invoke(app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "human"])
        issues = load_baseline_issues(json.loads(baseline.read_text()))
        assert [issue.provenance for issue in issues] == ["human"]

    def test_envelope_other_keys_survive_the_rewrite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        payload = json.loads(baseline.read_text(encoding="utf-8"))
        payload.update({"source": "fixture", "kind": "detection", "notes": "keep me"})
        baseline.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        CliRunner().invoke(app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "human"])
        payload = json.loads(baseline.read_text())
        assert payload["closed_world"] is False
        assert payload["source"] == "fixture"
        assert payload["kind"] == "detection"
        assert payload["notes"] == "keep me"
        assert payload["issues"][0]["provenance"] == "human"

    def test_bare_list_baseline_is_still_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = tmp_path / "adhoc.json"
        baseline.write_text(
            json.dumps([{"id": "1", "path": "a.py", "provenance": "agent-seeded"}]),
            encoding="utf-8",
        )
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "human"]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(baseline.read_text())[0]["provenance"] == "human"

    def test_adjudicates_a_real_shipped_corpus_baseline(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guards the regression this class missed: synthetic shapes only."""
        repo_root = Path(__file__).resolve().parents[2]
        shipped = sorted((repo_root / "evals" / "bench" / "mergecraft").glob("*/baseline.json"))
        # Clean closed-world cases carry zero issues by design, so pick the
        # first baseline that actually has a row to adjudicate.
        source = next(
            path for path in shipped if json.loads(path.read_text(encoding="utf-8")).get("issues")
        )
        target = tmp_path / "baseline.json"
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        issue_id = json.loads(target.read_text())["issues"][0]["id"]
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(target), "--id", issue_id, "--by", "human"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(target.read_text())
        assert payload["issues"][0]["provenance"] == "human"
        assert "closed_world" in payload

    def test_adjudicates_real_golden_case_as_typed_object(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The supported writer must preserve and validate a shipped golden object."""
        repo_root = Path(__file__).resolve().parents[2]
        source = (
            repo_root / "evals" / "cases" / "golden" / "golden-python-django-migration-001.json"
        )
        target = tmp_path / source.name
        target.write_bytes(source.read_bytes())
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(
            app,
            [
                "eval",
                "adjudicate",
                str(target),
                "--id",
                "golden-python-django-migration-001",
                "--by",
                "human",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        case = CorpusCase.model_validate(payload)
        assert case.provenance == "human"
        assert case.adjudication is not None
        assert case.adjudication.adjudicated_by == "human"

    def test_unknown_issue_id_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        before = baseline.read_bytes()
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "nope", "--by", "human"]
        )
        assert result.exit_code != 0
        assert baseline.read_bytes() == before

    def test_malformed_row_leaves_original_bytes_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = tmp_path / "malformed.json"
        baseline.write_text(
            json.dumps([{"id": "1", "path": "a.py"}, "not an object"]),
            encoding="utf-8",
        )
        before = baseline.read_bytes()
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "human"]
        )

        assert result.exit_code != 0
        assert baseline.read_bytes() == before
        assert "adjudicated 1" not in result.output

    def test_incomplete_golden_object_leaves_original_bytes_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = tmp_path / "golden-incomplete.json"
        baseline.write_text(
            json.dumps(
                {
                    "id": "golden-incomplete",
                    "title": "missing required language",
                    "framework": "django",
                    "path": "a.py",
                }
            ),
            encoding="utf-8",
        )
        before = baseline.read_bytes()
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(
            app,
            [
                "eval",
                "adjudicate",
                str(baseline),
                "--id",
                "golden-incomplete",
                "--by",
                "human",
            ],
        )

        assert result.exit_code != 0
        assert baseline.read_bytes() == before
        assert "adjudicated golden-incomplete" not in result.output

    def test_ambiguous_bare_object_leaves_original_bytes_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = tmp_path / "ambiguous.json"
        baseline.write_text(json.dumps({"id": "1"}), encoding="utf-8")
        before = baseline.read_bytes()
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "human"]
        )

        assert result.exit_code != 0
        assert baseline.read_bytes() == before
        assert "adjudicated 1" not in result.output

    def test_replace_failure_leaves_original_bytes_and_mode_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        baseline.chmod(0o640)
        before = baseline.read_bytes()
        monkeypatch.chdir(tmp_path)

        def fail_replace(_source: object, _target: object) -> None:
            raise OSError("simulated replace failure")

        monkeypatch.setattr("mergecraft.cli.eval_cmd.os.replace", fail_replace)
        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "human"]
        )

        assert result.exit_code != 0
        assert baseline.read_bytes() == before
        assert baseline.stat().st_mode & 0o777 == 0o640
        assert "adjudicated 1" not in result.output
        assert list(tmp_path.glob(f".{baseline.name}.*.tmp")) == []

    def test_successful_atomic_replace_preserves_file_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        baseline = self._baseline(tmp_path)
        baseline.chmod(0o640)
        monkeypatch.chdir(tmp_path)

        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(baseline), "--id", "1", "--by", "human"]
        )

        assert result.exit_code == 0, result.output
        assert baseline.stat().st_mode & 0o777 == 0o640


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


class TestBaselineInputShapes:
    """Every shape `read_json_or_jsonl` can hand back must round-trip.

    A one-row JSONL file is the trap: it is also valid JSON, so the loader
    returns a bare dict that is a row rather than an envelope. A compact
    single-line array is the mirror trap — it parses on one line but is not
    a JSONL row.
    """

    @staticmethod
    def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, body: str, row_id: str):
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        result = CliRunner().invoke(
            app, ["eval", "adjudicate", str(path), "--id", row_id, "--by", "human"]
        )
        return result, path

    def test_envelope_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        body = json.dumps({"closed_world": False, "issues": [{"id": "1", "path": "a.py"}]})
        result, path = self._run(tmp_path, monkeypatch, "b.json", body, "1")
        assert result.exit_code == 0, result.output
        payload = json.loads(path.read_text())
        assert payload["issues"][0]["provenance"] == "human"
        assert payload["closed_world"] is False

    def test_bare_list_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        result, path = self._run(
            tmp_path, monkeypatch, "b.json", json.dumps([{"id": "1", "path": "a.py"}]), "1"
        )
        assert result.exit_code == 0, result.output
        assert json.loads(path.read_text())[0]["provenance"] == "human"

    def test_one_row_jsonl_stays_one_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = json.dumps({"id": "1", "path": "a.py"}) + "\n"
        result, path = self._run(tmp_path, monkeypatch, "b.jsonl", body, "1")
        assert result.exit_code == 0, result.output
        lines = [line for line in path.read_text().splitlines() if line.strip()]
        assert len(lines) == 1, "a JSONL input must not be rewritten as indented JSON"
        assert json.loads(lines[0])["provenance"] == "human"

    def test_multi_row_jsonl_keeps_every_line(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = (
            json.dumps({"id": "1", "path": "a.py"})
            + "\n"
            + json.dumps({"id": "2", "path": "b.py"})
            + "\n"
        )
        result, path = self._run(tmp_path, monkeypatch, "b.jsonl", body, "2")
        assert result.exit_code == 0, result.output
        lines = [line for line in path.read_text().splitlines() if line.strip()]
        assert len(lines) == 2
        assert json.loads(lines[0]).get("provenance") is None
        assert json.loads(lines[1])["provenance"] == "human"

    def test_jsonl_comment_lines_survive_the_rewrite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`read_json_or_jsonl` accepts `//` comments, so the writer must keep them."""
        body = (
            "// corpus notes: seeded 2026-01\n"
            + json.dumps({"id": "1", "path": "a.py"})
            + "\n"
            + "\n"
            + "// second row below\n"
            + json.dumps({"id": "2", "path": "b.py"})
            + "\n"
        )
        result, path = self._run(tmp_path, monkeypatch, "c.jsonl", body, "1")
        assert result.exit_code == 0, result.output
        lines = path.read_text().splitlines()
        assert lines[0] == "// corpus notes: seeded 2026-01"
        assert lines[2] == ""
        assert lines[3] == "// second row below"
        assert json.loads(lines[1])["provenance"] == "human"
        assert json.loads(lines[4]).get("provenance") is None

    def test_jsonl_row_order_is_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = "".join(json.dumps({"id": str(n), "path": f"{n}.py"}) + "\n" for n in range(1, 4))
        result, path = self._run(tmp_path, monkeypatch, "c.jsonl", body, "2")
        assert result.exit_code == 0, result.output
        ids = [json.loads(line)["id"] for line in path.read_text().splitlines() if line.strip()]
        assert ids == ["1", "2", "3"]

    def test_pretty_printed_list_is_not_mistaken_for_jsonl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = json.dumps([{"id": "1", "path": "a.py"}], indent=2) + "\n"
        result, path = self._run(tmp_path, monkeypatch, "b.json", body, "1")
        assert result.exit_code == 0, result.output
        assert json.loads(path.read_text())[0]["provenance"] == "human"

    def test_single_object_row_document(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = json.dumps({"id": "1", "path": "a.py"}, indent=2) + "\n"
        result, path = self._run(tmp_path, monkeypatch, "b.json", body, "1")
        assert result.exit_code == 0, result.output
        decoded = json.loads(path.read_text())
        assert isinstance(decoded, dict)
        assert decoded["provenance"] == "human"

    def test_bare_baseline_with_title_and_category_is_not_a_corpus_case(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = json.dumps(
            {
                "id": "1",
                "path": "a.py",
                "title": "ordinary baseline issue",
                "category": "correctness",
            }
        )
        result, path = self._run(tmp_path, monkeypatch, "baseline.json", body, "1")
        assert result.exit_code == 0, result.output
        decoded = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(decoded, dict)
        assert decoded["provenance"] == "human"

    def test_compact_corpus_object_stays_an_object(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = json.dumps(
            {
                "id": "golden-1",
                "title": "compact corpus case",
                "language": "python",
                "framework": "django",
                "path": "a.py",
            }
        )
        result, path = self._run(tmp_path, monkeypatch, "golden.json", body, "golden-1")
        assert result.exit_code == 0, result.output
        decoded = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(decoded, dict)
        assert CorpusCase.model_validate(decoded).provenance == "human"
