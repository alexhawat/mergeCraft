"""The ``lite`` triage tier: a single capped LLM call for two deliberately-left-out cases.

``skip`` runs no LLM review and ``full`` is today's review. ``lite`` sits between them
and is chosen in exactly two cases, and only when the operator enabled
``review.fastPath.lite``: a recognizer matched the whole diff but is not opted in to
``skipLlm``, or a pin bump matched but its verifying checks have not passed from a
trusted App. Every other diff is ``full``, and with ``lite`` disabled both cases stay
``full`` with today's reason. The decision carries the token cap so the run record can
show it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, get_args

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from mergecraft.config.settings import FastPathSettings


_FIXTURES = Path(__file__).parent / "fixtures"
_PIN_DIFF = (_FIXTURES / "pin_bump_pr_889_shape.diff").read_text(encoding="utf-8")
_VERIFIER = "Verify changed deployment candidates"
_TRUSTED_APP = "mergecraft-reviewer"
_CAP = 9_000


def _diff(path: str, *lines: str, start: int = 1) -> str:
    old = sum(1 for line in lines if line[:1] in {" ", "-"})
    new = sum(1 for line in lines if line[:1] in {" ", "+"})
    body = "".join(f"{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -{start},{old} +{start},{new} @@\n{body}"
    )


_PROSE = _diff("README.md", "-Old words.", "+New words.")
_PROSE_HEAD = {"README.md": "New words.\n"}
_WHITESPACE = _diff("src/a.js", "-let a = 1;  ", "+let a = 1;")
_GENERATED = _diff("uv.lock", "-a = 1", "+a = 2")
_COMMENT = _diff("src/a.ts", " let a = 1;", "-// old note", "+// new note", " let b = 2;")
_COMMENT_HEAD = {"src/a.ts": "let a = 1;\n// new note\nlet b = 2;\n"}
_CODE = _diff("src/app.py", "-x = 1", "+x = 2")

# recognizer name -> (diff, head files)
_CASES: dict[str, tuple[str, dict[str, str]]] = {
    "pinBump": (_PIN_DIFF, {}),
    "prose": (_PROSE, _PROSE_HEAD),
    "whitespace": (_WHITESPACE, {"src/a.js": "let a = 1;\n"}),
    "generated": (_GENERATED, {}),
    "commentOnly": (_COMMENT, _COMMENT_HEAD),
}


def _lite(**overrides: object) -> dict[str, object]:
    block: dict[str, object] = {
        "enabled": True,
        "provider": "cheapo",
        "model": "tiny-1",
        "tokenCap": _CAP,
    }
    block.update(overrides)
    return block


def _config(*, lite: dict[str, object] | None = None, **overrides: object) -> FastPathSettings:
    from mergecraft.config.settings import FastPathSettings

    base: dict[str, Any] = {
        "enabled": True,
        "skipLlm": [],
        "pinBump": {"requireChecks": [_VERIFIER], "trustedCheckApps": [_TRUSTED_APP]},
    }
    if lite is not None:
        base["lite"] = lite
    base.update(overrides)
    return FastPathSettings.model_validate(base)


# ── settings ──────────────────────────────────────────────────────────────────


def test_the_lite_tier_is_off_by_default_with_the_documented_cap() -> None:
    from mergecraft.config.settings import RepoSettings

    lite = RepoSettings().review.fast_path.lite

    assert lite.enabled is False
    assert lite.token_cap == 50_000
    assert lite.max_output_tokens == 4_000


def test_the_lite_yaml_spellings_parse() -> None:
    from mergecraft.config.settings import RepoSettings

    settings = RepoSettings.model_validate(
        {
            "review": {
                "fastPath": {
                    "enabled": True,
                    "lite": {
                        "enabled": True,
                        "provider": "cheapo",
                        "model": "tiny-1",
                        "tokenCap": 12_000,
                        "maxOutputTokens": 2_000,
                    },
                }
            }
        }
    )

    lite = settings.review.fast_path.lite
    assert (lite.enabled, lite.provider, lite.model) == (True, "cheapo", "tiny-1")
    assert (lite.token_cap, lite.max_output_tokens) == (12_000, 2_000)


def test_the_lite_settings_model_is_exported_under_its_contract_name() -> None:
    from mergecraft.config import settings as settings_mod

    model = settings_mod.FastPathLiteSettings
    parsed = model.model_validate({"enabled": True, "provider": "p", "model": "m"})

    assert parsed.token_cap == 50_000


@pytest.mark.parametrize("cap", [4_000, 200_000])
def test_the_token_cap_bounds_are_inclusive(cap: int) -> None:
    config = _config(lite=_lite(tokenCap=cap))

    assert config.lite.token_cap == cap


@pytest.mark.parametrize(
    ("cap", "error_type"),
    [(3_999, "greater_than_equal"), (200_001, "less_than_equal"), (0, "greater_than_equal")],
)
def test_an_out_of_range_token_cap_is_rejected_naming_the_field(cap: int, error_type: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _config(lite=_lite(tokenCap=cap))

    errors = excinfo.value.errors()
    cap_errors = [e for e in errors if {"tokenCap", "token_cap"} & {str(p) for p in e["loc"]}]
    assert cap_errors, errors
    assert cap_errors[0]["type"] == error_type


def test_an_unknown_lite_key_is_rejected() -> None:
    """The lite block is security-relevant config: a typo must not be silently ignored."""
    with pytest.raises(ValidationError) as excinfo:
        _config(lite=_lite(tokenBudget=10_000))

    assert any("tokenBudget" in str(e["loc"]) for e in excinfo.value.errors())
    assert _config(lite=_lite()).lite.enabled is True


def test_comment_only_is_a_recognizer_name_skip_llm_accepts() -> None:
    from mergecraft.config.settings import FastPathRecognizer

    config = _config(skipLlm=["commentOnly"])

    assert "commentOnly" in get_args(FastPathRecognizer)
    assert config.skip_llm == ["commentOnly"]


# ── the tier vocabulary ───────────────────────────────────────────────────────


def test_the_tier_vocabulary_is_skip_lite_full() -> None:
    from mergecraft.classify import triage

    assert set(get_args(triage.Tier)) == {"skip", "lite", "full"}


def test_the_decision_carries_a_token_cap_defaulting_to_none() -> None:
    from mergecraft.classify.triage import TriageDecision

    full = TriageDecision(tier="full", recognizer=None, reason="x")
    lite = TriageDecision(tier="lite", recognizer="prose", reason="x", token_cap=_CAP)

    assert full.token_cap is None
    assert lite.token_cap == _CAP


def test_the_lite_record_line_states_a_single_call_and_its_cap() -> None:
    from mergecraft.classify.triage import TriageDecision

    decision = TriageDecision(tier="lite", recognizer="whitespace", reason="x", token_cap=_CAP)

    assert decision.record_line() == f"Tier: lite — single-call review, cap {_CAP} tokens"


def test_the_skip_and_full_record_lines_are_unchanged() -> None:
    from mergecraft.classify.triage import TriageDecision

    skip = TriageDecision(tier="skip", recognizer="prose", reason="x")
    full = TriageDecision(tier="full", recognizer=None, reason="x")

    assert skip.record_line() == "Tier: skip (prose) — no LLM review ran"
    assert full.record_line() == "Tier: full"


# ── case (a): matched but not opted in ────────────────────────────────────────


@pytest.mark.parametrize("name", sorted(_CASES))
def test_a_matched_recognizer_not_in_skip_llm_is_lite_when_enabled(name: str) -> None:
    from mergecraft.classify.triage import triage_diff

    diff, heads = _CASES[name]

    decision = triage_diff(diff, config=_config(lite=_lite()), head_files=heads, passed_checks=[])

    assert decision.tier == "lite"
    assert decision.recognizer == name
    assert decision.token_cap == _CAP
    assert name in decision.reason


@pytest.mark.parametrize("name", ["prose", "whitespace", "generated"])
def test_a_matched_recognizer_not_in_skip_llm_stays_full_when_lite_is_disabled(name: str) -> None:
    from mergecraft.classify.triage import triage_diff

    diff, heads = _CASES[name]

    for config in (_config(), _config(lite=_lite(enabled=False))):
        decision = triage_diff(diff, config=config, head_files=heads, passed_checks=[])

        assert decision.tier == "full"
        assert decision.reason == f"{name} matched but is not enabled in review.fastPath.skipLlm"
        assert decision.token_cap is None


def test_a_comment_only_diff_not_opted_in_is_full_with_todays_reason_when_lite_is_off() -> None:
    from mergecraft.classify.triage import triage_diff

    decision = triage_diff(_COMMENT, config=_config(), head_files=_COMMENT_HEAD, passed_checks=[])

    assert decision.tier == "full"
    assert decision.reason == "commentOnly matched but is not enabled in review.fastPath.skipLlm"


def test_an_opted_in_recognizer_still_skips_when_lite_is_enabled() -> None:
    """``lite`` only replaces a ``full``; it never takes a diff away from ``skip``."""
    from mergecraft.classify.triage import triage_diff

    config = _config(lite=_lite(), skipLlm=["whitespace"])

    decision = triage_diff(
        _WHITESPACE, head_files={"src/a.js": "let a = 1;\n"}, config=config, passed_checks=[]
    )

    assert (decision.tier, decision.recognizer) == ("skip", "whitespace")
    assert decision.token_cap is None


def test_an_opted_in_comment_only_diff_skips() -> None:
    from mergecraft.classify.triage import triage_diff

    config = _config(skipLlm=["commentOnly"])

    decision = triage_diff(_COMMENT, config=config, head_files=_COMMENT_HEAD, passed_checks=[])

    assert (decision.tier, decision.recognizer) == ("skip", "commentOnly")
    assert decision.reason.startswith("every change is a ")
    assert decision.record_line() == "Tier: skip (commentOnly) — no LLM review ran"


# ── case (b): an unverified pin bump ──────────────────────────────────────────


def test_an_opted_in_pin_bump_whose_checks_have_not_passed_is_lite() -> None:
    from mergecraft.classify.triage import triage_diff

    config = _config(lite=_lite(), skipLlm=["pinBump"])

    decision = triage_diff(_PIN_DIFF, config=config, passed_checks=["build"])

    assert decision.tier == "lite"
    assert decision.recognizer == "pinBump"
    assert decision.token_cap == _CAP
    assert _VERIFIER in decision.reason
    assert decision.relied_on_checks == ()


def test_an_unverified_pin_bump_stays_full_when_lite_is_disabled() -> None:
    from mergecraft.classify.triage import triage_diff

    config = _config(skipLlm=["pinBump"])

    decision = triage_diff(_PIN_DIFF, config=config, passed_checks=["build"])

    assert decision.tier == "full"
    assert decision.reason.startswith("a pin bump needs its verifying check(s) passed")
    assert decision.token_cap is None


def test_a_verified_pin_bump_still_skips_when_lite_is_enabled() -> None:
    from mergecraft.classify.triage import triage_diff

    config = _config(lite=_lite(), skipLlm=["pinBump"])

    decision = triage_diff(_PIN_DIFF, config=config, passed_checks=[_VERIFIER])

    assert (decision.tier, decision.recognizer) == ("skip", "pinBump")
    assert decision.relied_on_checks == (_VERIFIER,)


# ── everything else is full ───────────────────────────────────────────────────


def test_a_mixed_diff_is_full_even_with_lite_enabled() -> None:
    from mergecraft.classify.triage import triage_diff

    decision = triage_diff(_PIN_DIFF + _CODE, config=_config(lite=_lite()), passed_checks=[])

    assert decision.tier == "full"
    assert decision.reason == "no recognizer matches the whole diff"
    assert decision.token_cap is None


def test_a_real_code_change_is_full_with_lite_enabled() -> None:
    from mergecraft.classify.triage import triage_diff

    decision = triage_diff(_CODE, config=_config(lite=_lite()), passed_checks=[])

    assert decision.tier == "full"
    assert decision.recognizer is None


def test_an_empty_diff_is_full_with_lite_enabled() -> None:
    from mergecraft.classify.triage import triage_diff

    decision = triage_diff("", config=_config(lite=_lite()), passed_checks=[])

    assert decision.tier == "full"
    assert decision.reason == "the diff is empty"


def test_lite_enabled_under_a_disabled_fast_path_is_full() -> None:
    from mergecraft.classify.triage import triage_diff

    config = _config(lite=_lite(), enabled=False)

    decision = triage_diff(
        _WHITESPACE, head_files={"src/a.js": "let a = 1;\n"}, config=config, passed_checks=[]
    )

    assert decision.tier == "full"
    assert decision.reason == "review.fastPath is not enabled"


def test_the_lite_decision_is_deterministic() -> None:
    from mergecraft.classify.triage import triage_diff

    config = _config(lite=_lite())
    first = triage_diff(
        _WHITESPACE, head_files={"src/a.js": "let a = 1;\n"}, config=config, passed_checks=[]
    )
    second = triage_diff(
        _WHITESPACE, head_files={"src/a.js": "let a = 1;\n"}, config=config, passed_checks=[]
    )

    assert first.tier == "lite"
    assert first == second


def test_the_lite_cap_on_the_decision_follows_the_operator_config() -> None:
    from mergecraft.classify.triage import triage_diff

    decision = triage_diff(
        _WHITESPACE,
        head_files={"src/a.js": "let a = 1;\n"},
        config=_config(lite=_lite(tokenCap=120_000)),
        passed_checks=[],
    )

    assert decision.tier == "lite"
    assert decision.token_cap == 120_000
    assert decision.record_line() == "Tier: lite — single-call review, cap 120000 tokens"


# ── a pin bump the operator cannot verify is lite, never skip ─────────────────


@pytest.mark.parametrize(
    ("pin_bump", "passed", "reason_fragment"),
    [
        ({"requireChecks": [], "trustedCheckApps": [_TRUSTED_APP]}, (), "requireChecks"),
        ({"requireChecks": [_VERIFIER], "trustedCheckApps": []}, (_VERIFIER,), "trustedCheckApps"),
        (
            {"requireChecks": [_VERIFIER], "trustedCheckApps": ["github-actions"]},
            (_VERIFIER,),
            "trustedCheckApps",
        ),
    ],
    ids=["no-require-checks", "no-trusted-app", "only-github-actions"],
)
def test_an_unverifiable_opted_in_pin_bump_is_lite_when_enabled(
    pin_bump: dict[str, object], passed: tuple[str, ...], reason_fragment: str
) -> None:
    from mergecraft.classify.triage import triage_diff

    config = _config(lite=_lite(), skipLlm=["pinBump"], pinBump=pin_bump)

    decision = triage_diff(_PIN_DIFF, config=config, passed_checks=passed)

    assert decision.tier == "lite"
    assert decision.recognizer == "pinBump"
    assert decision.token_cap == _CAP
    assert reason_fragment in decision.reason
