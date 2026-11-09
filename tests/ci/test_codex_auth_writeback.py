"""The self-review writes the refreshed Codex login back to ``CODEX_AUTH_JSON`` (#970).

Codex rotates the ChatGPT-subscription refresh token on use. The rung that
consumed the secret must be the one that stores the rotated login, under a
token that can write repository secrets and nothing else, and only on a
same-repository run that actually ran Codex. These tests pin that shape in
``.github/workflows/mergecraft.yml``.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from tests.ci.support_self_review_cascade import TRUSTED_SCRIPTS
from tests.ci.workflow_support import load_workflow

_WORKFLOW = "mergecraft.yml"
_CODEX_STEP_ID = "mergecraft_codex"
_MINT_STEP_ID = "app_token_codex_writeback"
_WRITEBACK_STEP_ID = "codex_auth_writeback"
_EXPORT_ENV = "MERGECRAFT_CODEX_AUTH_EXPORT"
_EXPORT_PATH = "${{ runner.temp }}/mergecraft-codex-auth/auth.json"
_SCRIPT = "scripts/codex_auth_writeback.py"
_SERIALISATION_GROUP = "codex-subscription-auth"
_EXPRESSION = re.compile(r"\$\{\{")


def _jobs() -> dict[str, dict[str, Any]]:
    jobs = load_workflow(_WORKFLOW).get("jobs")
    assert isinstance(jobs, dict)
    return {name: job for name, job in jobs.items() if isinstance(job, dict)}


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    if "uses" in job:
        # A reusable-workflow call cannot contain inline steps.
        assert "steps" not in job
        return []
    steps = job.get("steps")
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def _jobs_with_step(step_id: str) -> list[str]:
    return [
        name for name, job in _jobs().items() if any(s.get("id") == step_id for s in _steps(job))
    ]


def _step(job: dict[str, Any], step_id: str) -> dict[str, Any]:
    for step in _steps(job):
        if step.get("id") == step_id:
            return step
    raise AssertionError(f"no step id={step_id!r} in job")


@pytest.fixture(scope="module")
def codex_job() -> dict[str, Any]:
    names = _jobs_with_step(_CODEX_STEP_ID)
    assert len(names) == 1, f"exactly one job must hold the Codex rung, found {names}"
    return _jobs()[names[0]]


class TestWriteBackPlacement:
    def test_write_back_lives_only_on_the_job_holding_the_codex_rung(self) -> None:
        """The job that spent the refresh token is the one that stores the new one."""
        assert _jobs_with_step(_WRITEBACK_STEP_ID) == _jobs_with_step(_CODEX_STEP_ID)
        assert _jobs_with_step(_MINT_STEP_ID) == _jobs_with_step(_CODEX_STEP_ID)

    def test_write_back_runs_after_the_codex_rung(self, codex_job: dict[str, Any]) -> None:
        ids = [step.get("id") for step in _steps(codex_job)]
        assert ids.index(_CODEX_STEP_ID) < ids.index(_MINT_STEP_ID) < ids.index(_WRITEBACK_STEP_ID)

    def test_codex_rung_exports_the_refreshed_login(self, codex_job: dict[str, Any]) -> None:
        """Without the export env the driver leaves auth.json in the temp dir it deletes."""
        env = _step(codex_job, _CODEX_STEP_ID).get("env")
        assert isinstance(env, dict)
        assert env.get(_EXPORT_ENV) == _EXPORT_PATH

    def test_write_back_reads_the_same_export_path(self, codex_job: dict[str, Any]) -> None:
        env = _step(codex_job, _WRITEBACK_STEP_ID).get("env")
        assert isinstance(env, dict)
        assert env.get("CODEX_AUTH_EXPORT") == _EXPORT_PATH

    def test_export_is_discarded_on_every_path(self, codex_job: dict[str, Any]) -> None:
        """The exported credential must not outlive the job on the runner disk."""
        discard = [
            step
            for step in _steps(codex_job)
            if isinstance(step.get("run"), str)
            and "rm -f" in step["run"]
            and isinstance(step.get("env"), dict)
            and step["env"].get("CODEX_AUTH_EXPORT") == _EXPORT_PATH
        ]
        assert discard, "no always() step removes the exported login"
        assert all(step.get("if") == "always()" for step in discard)


class TestWriteBackGating:
    @pytest.mark.parametrize("step_id", [_MINT_STEP_ID, _WRITEBACK_STEP_ID])
    def test_gated_on_same_repo_and_a_codex_run(
        self, codex_job: dict[str, Any], step_id: str
    ) -> None:
        condition = str(_step(codex_job, step_id).get("if"))
        assert "always()" in condition, "a rung that failed after refreshing still rotated it"
        assert "env.IS_SAME_REPO == 'true'" in condition
        assert "env.HAS_CODEX == 'true'" in condition
        assert f"steps.{_CODEX_STEP_ID}.outcome != 'skipped'" in condition

    def test_write_back_needs_the_dedicated_token(self, codex_job: dict[str, Any]) -> None:
        condition = str(_step(codex_job, _WRITEBACK_STEP_ID).get("if"))
        assert f"steps.{_MINT_STEP_ID}.outputs.token != ''" in condition
        env = _step(codex_job, _WRITEBACK_STEP_ID).get("env")
        assert isinstance(env, dict)
        assert env.get("GH_TOKEN") == f"${{{{ steps.{_MINT_STEP_ID}.outputs.token }}}}"

    def test_neither_step_fails_the_review(self, codex_job: dict[str, Any]) -> None:
        for step_id in (_MINT_STEP_ID, _WRITEBACK_STEP_ID):
            assert _step(codex_job, step_id).get("continue-on-error") is True


class TestWriteBackToken:
    def test_mint_requests_only_secrets_write(self, codex_job: dict[str, Any]) -> None:
        """A review token must not be able to rewrite repository secrets."""
        mint = _step(codex_job, _MINT_STEP_ID)
        assert str(mint.get("uses", "")).startswith("actions/create-github-app-token@")
        with_ = mint.get("with")
        assert isinstance(with_, dict)
        permissions = {k: v for k, v in with_.items() if k.startswith("permission-")}
        assert permissions == {"permission-secrets": "write"}
        assert with_.get("repositories") == "${{ github.event.repository.name }}"

    def test_review_tokens_cannot_write_secrets(self, codex_job: dict[str, Any]) -> None:
        for step in _steps(codex_job):
            if step.get("id") == _MINT_STEP_ID:
                continue
            with_ = step.get("with")
            if isinstance(with_, dict):
                assert "permission-secrets" not in with_, step.get("name")


class TestWriteBackScript:
    def test_script_is_staged_as_a_trusted_copy(self, codex_job: dict[str, Any]) -> None:
        assert _SCRIPT in TRUSTED_SCRIPTS
        staging = [step for step in _steps(codex_job) if step.get("id") == "trusted_scripts"]
        assert staging, "no trusted-copy staging step"
        assert _SCRIPT in str(staging[0].get("run"))

    def test_write_back_runs_the_verified_copy(self, codex_job: dict[str, Any]) -> None:
        run = str(_step(codex_job, _WRITEBACK_STEP_ID).get("run"))
        assert "sha256sum" in run
        assert "TRUSTED_HASHES" in run
        assert f'"${{TRUSTED_ROOT}}/{_SCRIPT}"' in run
        assert not re.search(rf"(?<![\w/$]){re.escape(_SCRIPT)}", run), (
            "the write-back must not run the workspace copy of the script"
        )

    def test_credential_is_never_printed(self, codex_job: dict[str, Any]) -> None:
        run = str(_step(codex_job, _WRITEBACK_STEP_ID).get("run"))
        for word in ("echo", "printf", "cat "):
            for line in run.splitlines():
                if word in line:
                    assert "CODEX_AUTH_JSON_ORIGINAL" not in line
                    assert "CODEX_AUTH_EXPORT" not in line
        assert "upload-artifact" not in run
        env = _step(codex_job, _WRITEBACK_STEP_ID).get("env")
        assert isinstance(env, dict)
        assert env.get("CODEX_AUTH_JSON_ORIGINAL") == "${{ secrets.CODEX_AUTH_JSON }}"


class TestWriteBackSerialisation:
    def test_codex_job_is_serialised_on_the_subscription_group(
        self, codex_job: dict[str, Any]
    ) -> None:
        """Two consumers refreshing one login retire each other's session (#882)."""
        concurrency = codex_job.get("concurrency")
        assert isinstance(concurrency, dict), (
            f"the job holding the Codex rung must carry the {_SERIALISATION_GROUP!r} group (#1126)"
        )
        assert concurrency.get("group") == _SERIALISATION_GROUP
        assert concurrency.get("cancel-in-progress") is False


def test_no_expression_in_the_write_back_comments() -> None:
    """Comments are documentation text: GitHub evaluates ``${{ }}`` wherever it appears."""
    from tests.ci.workflow_support import read_text

    text = read_text(f".github/workflows/{_WORKFLOW}")
    start = text.index("Mint App token for the Codex login write-back")
    end = text.index("Discard the exported Codex login")
    for line in text[start:end].splitlines():
        if line.lstrip().startswith("#"):
            assert not _EXPRESSION.search(line), line
