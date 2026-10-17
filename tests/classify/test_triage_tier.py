"""The triage tier: a deterministic function of the diff and the base-side config.

``skip`` means no LLM review runs; ``full`` is today's review. The tier is a pure
function of the unified diff, the operator-owned ``review.fastPath`` config, head-side
file text (only to prove a markdown edit stays out of a code fence) and the names of the
checks that passed on the head SHA. Nothing a pull request author writes — title, body,
labels, head-side config — is an input, because a fork author must not be able to opt
out of review.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from mergecraft.config.settings import FastPathSettings


_OLD = "1d479f7a0123456789abcdef0123456789abcdef"
_NEW = "08274ddafedcba9876543210fedcba9876543210"
_FIXTURES = Path(__file__).parent / "fixtures"
_VERIFIER = "Verify changed deployment candidates"
_PIN_DIFF = (_FIXTURES / "pin_bump_pr_889_shape.diff").read_text(encoding="utf-8")


def _config(**overrides: object) -> FastPathSettings:
    from mergecraft.config.settings import FastPathSettings

    base: dict[str, object] = {
        "enabled": True,
        "skipLlm": ["pinBump", "prose", "whitespace", "generated"],
        "pinBump": {"requireChecks": [_VERIFIER]},
    }
    base.update(overrides)
    return FastPathSettings.model_validate(base)


def _mixed_diff() -> str:
    return _PIN_DIFF + (
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
        "@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    )


# ── config ────────────────────────────────────────────────────────────────────


def test_the_fast_path_is_off_by_default() -> None:
    from mergecraft.config.settings import RepoSettings

    config = RepoSettings().review.fast_path

    assert config.enabled is False
    assert config.skip_llm == []


def test_missing_config_reproduces_todays_behaviour_for_every_diff() -> None:
    from mergecraft.classify.triage import triage_diff
    from mergecraft.config.settings import FastPathSettings

    decision = triage_diff(_PIN_DIFF, config=FastPathSettings(), passed_checks=[_VERIFIER])

    assert decision.tier == "full"
    assert decision.recognizer is None


def test_the_yaml_spellings_parse() -> None:
    from mergecraft.config.settings import RepoSettings

    settings = RepoSettings.model_validate(
        {
            "review": {
                "fastPath": {
                    "enabled": True,
                    "skipLlm": ["pinBump"],
                    "pinBump": {"requireChecks": [_VERIFIER]},
                }
            }
        }
    )

    assert settings.review.fast_path.enabled is True
    assert settings.review.fast_path.skip_llm == ["pinBump"]
    assert settings.review.fast_path.pin_bump.require_checks == [_VERIFIER]


def test_an_unknown_recognizer_name_is_rejected() -> None:
    from mergecraft.config.settings import FastPathSettings

    with pytest.raises(ValidationError):
        FastPathSettings.model_validate({"enabled": True, "skipLlm": ["everything"]})


# ── tiers ─────────────────────────────────────────────────────────────────────


def test_a_verified_pin_bump_is_skip_and_names_the_check_it_relied_on() -> None:
    from mergecraft.classify.triage import triage_diff

    decision = triage_diff(_PIN_DIFF, config=_config(), passed_checks=[_VERIFIER, "build"])

    assert decision.tier == "skip"
    assert decision.recognizer == "pinBump"
    assert decision.relied_on_checks == (_VERIFIER,)


def test_the_run_record_line_states_the_tier() -> None:
    from mergecraft.classify.triage import triage_diff

    decision = triage_diff(_PIN_DIFF, config=_config(), passed_checks=[_VERIFIER])

    assert decision.record_line() == "Tier: skip (pinBump) — no LLM review ran"


def test_a_pin_bump_without_the_verifier_check_passed_is_full() -> None:
    from mergecraft.classify.triage import triage_diff

    decision = triage_diff(_PIN_DIFF, config=_config(), passed_checks=["build"])

    assert decision.tier == "full"
    assert _VERIFIER in decision.reason


def test_a_pin_bump_with_no_configured_verifier_check_is_full() -> None:
    from mergecraft.classify.triage import triage_diff

    config = _config(pinBump={"requireChecks": []})

    decision = triage_diff(_PIN_DIFF, config=config, passed_checks=[_VERIFIER])

    assert decision.tier == "full"


def test_every_required_check_must_have_passed() -> None:
    from mergecraft.classify.triage import triage_diff

    config = _config(pinBump={"requireChecks": [_VERIFIER, "build"]})

    assert triage_diff(_PIN_DIFF, config=config, passed_checks=[_VERIFIER]).tier == "full"
    assert triage_diff(_PIN_DIFF, config=config, passed_checks=[_VERIFIER, "build"]).tier == "skip"


def test_a_recognizer_that_is_not_opted_in_stays_full() -> None:
    from mergecraft.classify.triage import triage_diff

    config = _config(skipLlm=["prose"])

    decision = triage_diff(_PIN_DIFF, config=config, passed_checks=[_VERIFIER])

    assert decision.tier == "full"
    assert "pinBump" in decision.reason


def test_a_mixed_diff_matches_no_recognizer_end_to_end_and_is_full() -> None:
    from mergecraft.classify.triage import triage_diff

    decision = triage_diff(_mixed_diff(), config=_config(), passed_checks=[_VERIFIER])

    assert decision.tier == "full"
    assert decision.recognizer is None


def test_one_with_input_changed_beside_the_sha_swap_is_full() -> None:
    from mergecraft.classify.triage import triage_diff

    diff = _PIN_DIFF.replace(
        "         with:\n           token: ${{ secrets.GITHUB_TOKEN }}\n@@ -88",
        "         with:\n-          fail-on: none\n+          fail-on: nothing\n@@ -88",
        1,
    )
    assert diff != _PIN_DIFF

    assert triage_diff(diff, config=_config(), passed_checks=[_VERIFIER]).tier == "full"


def test_prose_whitespace_and_generated_diffs_skip_when_opted_in() -> None:
    from mergecraft.classify.triage import triage_diff

    prose = (
        "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n"
        "@@ -1 +1 @@\n-Old words.\n+New words.\n"
    )
    whitespace = (
        "diff --git a/src/a.js b/src/a.js\n--- a/src/a.js\n+++ b/src/a.js\n"
        "@@ -1 +1 @@\n-let a = 1;  \n+let a = 1;\n"
    )
    generated = (
        "diff --git a/uv.lock b/uv.lock\n--- a/uv.lock\n+++ b/uv.lock\n"
        "@@ -1 +1 @@\n-a = 1\n+a = 2\n"
    )

    def tier(diff: str, head: dict[str, str] | None = None) -> tuple[str, str | None]:
        decision = triage_diff(diff, config=_config(), head_files=head, passed_checks=[])
        return decision.tier, decision.recognizer

    assert tier(prose, {"README.md": "New words.\n"}) == ("skip", "prose")
    assert tier(whitespace) == ("skip", "whitespace")
    assert tier(generated) == ("skip", "generated")


def test_an_empty_diff_is_full() -> None:
    from mergecraft.classify.triage import triage_diff

    assert triage_diff("", config=_config(), passed_checks=[_VERIFIER]).tier == "full"


def test_the_decision_is_deterministic() -> None:
    from mergecraft.classify.triage import triage_diff

    first = triage_diff(_PIN_DIFF, config=_config(), passed_checks=[_VERIFIER])
    second = triage_diff(_PIN_DIFF, config=_config(), passed_checks=[_VERIFIER])

    assert first == second


def test_no_pull_request_authored_field_is_an_input() -> None:
    """The title, body, labels and head-side config cannot select a tier — by signature."""
    from mergecraft.classify.triage import TriageDecision, triage_diff

    parameters = set(inspect.signature(triage_diff).parameters)

    assert parameters == {"diff_text", "config", "head_files", "passed_checks"}
    assert isinstance(triage_diff(_PIN_DIFF, config=_config(), passed_checks=[]), TriageDecision)
