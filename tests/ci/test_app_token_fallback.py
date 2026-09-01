"""GitHub App reviewer identity — token fallback contract (#550).

A user PAT cannot create check-runs at all (``403 You must authenticate via a
GitHub App``); ``GITHUB_TOKEN`` can create check-runs but carries no identity
distinct from every other ``github-actions[bot]`` comment in the repo. A
GitHub App installation token does both, which is why it is now the preferred
reviewer credential.

The wiring has a hard requirement: a fork PR, or a same-repo consumer that has
never registered the App, MUST still get a working review. These tests pin
that fallback at the YAML level — no live App credentials, no network — the
same way ``test_approval_gate_auth_predicate.py`` pins ``HAS_AUTH`` without
running the workflow.
"""

from __future__ import annotations

from typing import Any

from tests.ci.workflow_support import REPO_ROOT, job, load_workflow

_MERGECRAFT_WORKFLOW = "mergecraft.yml"
_APPROVE_WORKFLOW = "mergecraft-approve.yml"
_REVIEW_JOB = "review"
_APPROVE_JOB = "approve"
_MINT_STEP = "Mint reviewer App installation token"
_REVIEW_STEP_NAMES = (
    "mergeCraft PR review (Nous Tencent HY3)",
    "mergeCraft PR review (Codex)",
    "mergeCraft PR review (Claude)",
)
_TOKEN_FALLBACK_EXPR = "${{ steps.app_token.outputs.token || github.token }}"


def _review_steps() -> list[dict[str, Any]]:
    steps = job(load_workflow(_MERGECRAFT_WORKFLOW), _REVIEW_JOB).get("steps")
    assert isinstance(steps, list)
    return [s for s in steps if isinstance(s, dict)]


def _step(steps: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} not found")


class TestMergecraftReviewAppToken:
    """``mergecraft.yml``'s ``review`` job prefers the App token, falls back to github.token."""

    def test_mint_step_exists(self) -> None:
        steps = _review_steps()
        mint = _step(steps, _MINT_STEP)
        assert mint.get("id") == "app_token"

    def test_mint_step_uses_the_local_composite(self) -> None:
        """The mint must not ride the Action SHA pin.

        ``uses: alexhawat/mergeCraft/get-installation-token@<pin>`` runs the
        composite from that pin, so a revoke-before-use fix in this PR cannot
        take effect until a later bump — and it added a fifth pin site the
        freshness gate had to grow to see. The local composite is the copy
        ``pull_request_target`` already checked out from the default branch.
        """
        steps = _review_steps()
        mint = _step(steps, _MINT_STEP)
        assert mint.get("uses") == "./get-installation-token"

    def test_composite_does_not_revoke_before_callers_read_the_token(self) -> None:
        """Composite actions have no post-job hook; a sequential revoke step
        killed the just-minted token before any review rung ran (#578).
        """
        import yaml

        text = (REPO_ROOT / "get-installation-token" / "action.yml").read_text(encoding="utf-8")
        loaded = yaml.safe_load(text)
        steps = loaded["runs"]["steps"]
        names = [step.get("name", "") for step in steps]
        assert not any("revoke" in name.lower() for name in names)
        for step in steps:
            assert "--post" not in str(step.get("run", ""))

    def test_mint_step_is_gated_on_app_secrets(self) -> None:
        """Unconfigured consumers (no App secrets) must skip minting outright.

        The presence check is hoisted into job-level ``env.HAS_APP`` rather than
        read directly in the step's own ``if:`` — the ``secrets`` context is not
        available in a step ``if:`` (actionlint: "context secrets is not allowed
        here"), the same reason every other HAS_* flag on this job is computed
        in ``env:`` first. See ``test_no_step_if_reads_secrets_directly`` below.
        """
        steps = _review_steps()
        mint = _step(steps, _MINT_STEP)
        condition = mint.get("if", "")
        assert "env.HAS_APP" in condition

        env = job(load_workflow(_MERGECRAFT_WORKFLOW), _REVIEW_JOB)["env"]
        has_app = env.get("HAS_APP", "")
        assert "secrets.MERGECRAFT_APP_ID" in has_app
        assert "secrets.MERGECRAFT_APP_PRIVATE_KEY" in has_app

    def test_no_step_if_reads_secrets_directly(self) -> None:
        """Regression guard (#550): actionlint rejects ``secrets.*`` inside a
        step ``if:`` outright — it is not in the documented context-availability
        list for that field. Every HAS_* gate must be computed in job env first.
        """
        steps = _review_steps()
        for step in steps:
            condition = step.get("if")
            if isinstance(condition, str):
                assert "secrets." not in condition, (
                    f"step {step.get('name')!r} reads secrets.* directly in `if:` "
                    "— hoist it into job env instead (actionlint: context "
                    "'secrets' is not allowed in `if:`)"
                )

    def test_mint_step_is_gated_on_same_repo(self) -> None:
        """A fork PR must never receive the reviewer App's installation token."""
        steps = _review_steps()
        mint = _step(steps, _MINT_STEP)
        condition = mint.get("if", "")
        assert "env.IS_SAME_REPO" in condition

    def test_mint_step_tolerates_a_failed_mint(self) -> None:
        """A bad/expired App key must not fail the job — it must fall back."""
        steps = _review_steps()
        mint = _step(steps, _MINT_STEP)
        assert mint.get("continue-on-error") is True

    def test_mint_step_forwards_app_credentials_from_secrets(self) -> None:
        steps = _review_steps()
        mint = _step(steps, _MINT_STEP)
        env = mint.get("env", {})
        assert env.get("GITHUB_APP_ID") == "${{ secrets.MERGECRAFT_APP_ID }}"
        assert env.get("GITHUB_APP_PRIVATE_KEY") == "${{ secrets.MERGECRAFT_APP_PRIVATE_KEY }}"

    def test_every_review_rung_prefers_the_app_token_falling_back_to_github_token(self) -> None:
        steps = _review_steps()
        for name in _REVIEW_STEP_NAMES:
            rung = _step(steps, name)
            with_block = rung.get("with", {})
            assert with_block.get("token") == _TOKEN_FALLBACK_EXPR, (
                f"{name!r} does not prefer the App token with a github.token fallback"
            )

    def test_no_review_rung_hardcodes_bare_github_token(self) -> None:
        """Regression guard: a rung silently reverting to bare github.token would
        drop the App identity without any test failing elsewhere.
        """
        steps = _review_steps()
        for name in _REVIEW_STEP_NAMES:
            rung = _step(steps, name)
            token = rung.get("with", {}).get("token")
            assert token != "${{ github.token }}"

    def test_mint_step_runs_before_every_review_rung(self) -> None:
        """The fallback expression only resolves correctly once the mint step
        has already run (or been skipped) earlier in the step list.
        """
        steps = _review_steps()
        names = [s.get("name") for s in steps]
        mint_index = names.index(_MINT_STEP)
        for name in _REVIEW_STEP_NAMES:
            assert names.index(name) > mint_index

    def test_no_step_references_the_retired_reviewer_pat(self) -> None:
        """#550 retires MERGECRAFT_REVIEWER_PAT — no step may still wire it as a secret."""
        steps = _review_steps()
        for step in steps:
            for value in step.get("env", {}).values():
                assert "secrets.MERGECRAFT_REVIEWER_PAT" not in str(value)
            for value in step.get("with", {}).values():
                assert "secrets.MERGECRAFT_REVIEWER_PAT" not in str(value)


class TestMergecraftApproveAppToken:
    """``mergecraft-approve.yml`` mints its own App token; no PAT anywhere."""

    def _approve_steps(self) -> list[dict[str, Any]]:
        steps = job(load_workflow(_APPROVE_WORKFLOW), _APPROVE_JOB).get("steps")
        assert isinstance(steps, list)
        return [s for s in steps if isinstance(s, dict)]

    def test_mint_step_exists_and_is_gated_on_the_structural_verdict(self) -> None:
        steps = self._approve_steps()
        mint = _step(steps, _MINT_STEP)
        assert mint.get("id") == "app_token"
        condition = mint.get("if", "")
        assert "steps.verdict.outputs.conclusion == 'success'" in condition
        assert "env.HAS_APP" in condition

        env = job(load_workflow(_APPROVE_WORKFLOW), _APPROVE_JOB).get("env", {})
        has_app = env.get("HAS_APP", "")
        assert "secrets.MERGECRAFT_APP_ID" in has_app
        assert "secrets.MERGECRAFT_APP_PRIVATE_KEY" in has_app

    def test_mint_step_uses_the_local_composite(self) -> None:
        steps = self._approve_steps()
        mint = _step(steps, _MINT_STEP)
        assert mint.get("uses") == "./get-installation-token"

    def test_no_step_if_reads_secrets_directly(self) -> None:
        """Same regression guard as the mergecraft.yml side (#550)."""
        steps = self._approve_steps()
        for step in steps:
            condition = step.get("if")
            if isinstance(condition, str):
                assert "secrets." not in condition

    def test_mint_step_tolerates_a_failed_mint(self) -> None:
        steps = self._approve_steps()
        mint = _step(steps, _MINT_STEP)
        assert mint.get("continue-on-error") is True

    def test_submit_approve_step_reads_the_minted_token(self) -> None:
        steps = self._approve_steps()
        submit = _step(steps, "Submit privileged APPROVE")
        env = submit.get("env", {})
        assert env.get("GH_TOKEN") == "${{ steps.app_token.outputs.token }}"

    def test_submit_approve_step_no_longer_reads_the_pat_secret(self) -> None:
        steps = self._approve_steps()
        submit = _step(steps, "Submit privileged APPROVE")
        env = submit.get("env", {})
        assert env.get("GH_TOKEN") != "${{ secrets.MERGECRAFT_REVIEWER_PAT }}"

    def test_submit_approve_step_still_no_ops_on_an_empty_token(self) -> None:
        """A repo with no App configured must not error — it must skip cleanly,
        the same shape the old ``MERGECRAFT_REVIEWER_PAT`` no-op used.
        """
        steps = self._approve_steps()
        submit = _step(steps, "Submit privileged APPROVE")
        run = submit.get("run", "")
        assert 'if [ -z "${GH_TOKEN}" ]' in run
        assert "exit 0" in run

    def test_no_step_references_the_retired_reviewer_pat(self) -> None:
        steps = self._approve_steps()
        for step in steps:
            for value in step.get("env", {}).values():
                assert "secrets.MERGECRAFT_REVIEWER_PAT" not in str(value)


__all__ = [
    "TestMergecraftApproveAppToken",
    "TestMergecraftReviewAppToken",
]
