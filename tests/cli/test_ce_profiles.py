"""W21 / W23 — remaining profiles + risk-based select (#369 / D10).

Out of scope: token/cost/tool-call budget mechanism (already on ``ReviewProfile``);
latency budgets per profile (#367 already landed).
Additive CLI only — new ``cli/profile_cmd.py``; no root-callback edits.
"""

from __future__ import annotations

import pytest
from tests.support.cc_batch import invoke, plain, require_registered
from tests.support.ce_batch import (
    CE_PROFILE_NAMES,
    SHIPPED_PROFILE_NAMES,
    d10_root_callback_owns_globals,
    green_after,
    require_callable,
    require_module,
)
from tests.support.dead_package_wiring import CLI_DIR, SRC_ROOT, root_callback_source

from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE, CLI_USAGE_EXIT_CODE
from mergecraft.cli.profiles import parse_profile_name, resolve_profile
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.run_bounds import BudgetExhausted, budget_exhaustion_outcome

_W23 = green_after("W23", "remaining profiles + risk-based select; additive CLI (#369 / D10)")
_PROFILES_MODULE = "mergecraft.cli.profiles"


def test_shipped_profiles_are_fast_deep_security_only() -> None:
    """W21 current state — five plan profiles are still missing."""
    for name in SHIPPED_PROFILE_NAMES:
        assert parse_profile_name(name) == name
        assert resolve_profile(name) is not None
    for missing in sorted(CE_PROFILE_NAMES - SHIPPED_PROFILE_NAMES):
        with pytest.raises(ValueError, match=r"unknown profile"):
            parse_profile_name(missing)


def test_profile_recommend_is_currently_a_usage_error() -> None:
    """W21 current state — ``mergecraft profile`` is not a command yet."""
    result = invoke("profile", "recommend")
    assert result.exit_code == CLI_USAGE_EXIT_CODE, plain(result.stdout + result.stderr)


def test_profile_token_cost_and_tool_budgets_remain_out_of_scope() -> None:
    """#369 out of scope — budget fields already exist; this wave does not rebuild them."""
    deep = resolve_profile("deep")
    assert deep is not None
    assert deep.token_budget > 0
    assert deep.cost_budget_usd > 0
    assert deep.tool_call_budget > 0
    assert deep.latency_budget_ms > 0


def test_budget_exhaustion_never_returns_passed() -> None:
    """Lasting — budget exhaustion is ``inconclusive``, never a false clean."""
    outcome = budget_exhaustion_outcome(BudgetExhausted("token", "token budget exhausted"))
    assert outcome is RunOutcome.inconclusive
    assert outcome is not RunOutcome.passed


def test_w23_does_not_fold_profile_into_root_callback() -> None:
    """D10 — profile select is additive; ``_root`` keeps only global flags."""
    root_block = d10_root_callback_owns_globals()
    assert "profile_cmd" not in root_block
    assert "select_profile_from_risk" not in root_block
    source = root_callback_source()
    assert "def _root(" in source


@_W23
def test_eight_named_profiles_are_registered() -> None:
    """Happy: the eight plan profiles resolve."""
    require_module(_PROFILES_MODULE)
    for name in sorted(CE_PROFILE_NAMES):
        profile = resolve_profile(name)
        assert profile is not None
        assert profile.name == name
        assert profile.token_budget > 0


@_W23
@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("api-compatibility", "api_compatibility"),
        ("cross-repo", "cross_repo"),
    ],
)
def test_hyphenated_cli_aliases_map_to_canonical_names(alias: str, canonical: str) -> None:
    """Edge: CLI hyphens parse to the Python profile names."""
    parsed = parse_profile_name(alias)
    assert parsed == canonical


@_W23
def test_unknown_profile_names_the_full_set() -> None:
    """Error: unknown profile names the eight allowed values (type + message)."""
    with pytest.raises(ValueError, match=r"standard") as err:
        parse_profile_name("not-a-profile")
    message = str(err.value)
    for name in ("fast", "deep", "security", "monorepo", "migration"):
        assert name in message


@_W23
def test_select_profile_from_risk_picks_security_for_high_risk() -> None:
    """Happy: high/critical risk selects the security profile."""
    module = require_module(_PROFILES_MODULE)
    select = require_callable(module, "select_profile_from_risk")
    for risk in ("high", "critical"):
        chosen = select(risk)
        name = getattr(chosen, "name", chosen)
        assert name == "security"


@_W23
def test_select_profile_from_risk_picks_fast_for_trivial() -> None:
    """Happy: trivial risk selects fast."""
    module = require_module(_PROFILES_MODULE)
    select = require_callable(module, "select_profile_from_risk")
    chosen = select("trivial")
    name = getattr(chosen, "name", chosen)
    assert name == "fast"


@_W23
def test_unknown_risk_is_an_error() -> None:
    """Error: unknown risk fails closed (type + message)."""
    module = require_module(_PROFILES_MODULE)
    select = require_callable(module, "select_profile_from_risk")
    with pytest.raises((ValueError, KeyError), match=r"risk"):
        select("not-a-risk")


@_W23
def test_cli_profile_overrides_risk_selection() -> None:
    """Happy: explicit CLI profile wins over risk auto-select."""
    module = require_module(_PROFILES_MODULE)
    resolve = require_callable(module, "resolve_review_profile")
    chosen = resolve(risk="high", cli_name="fast", policy_name=None)
    name = getattr(chosen, "name", chosen)
    assert name == "fast"


@_W23
def test_policy_profile_overrides_risk_selection() -> None:
    """Happy: policy profile wins over risk when CLI is unset."""
    module = require_module(_PROFILES_MODULE)
    resolve = require_callable(module, "resolve_review_profile")
    chosen = resolve(risk="trivial", cli_name=None, policy_name="deep")
    name = getattr(chosen, "name", chosen)
    assert name == "deep"


@_W23
def test_cli_profile_overrides_policy() -> None:
    """Happy: CLI still wins when policy also pins a profile."""
    module = require_module(_PROFILES_MODULE)
    resolve = require_callable(module, "resolve_review_profile")
    chosen = resolve(risk="high", cli_name="standard", policy_name="security")
    name = getattr(chosen, "name", chosen)
    assert name == "standard"


@_W23
def test_profile_cli_is_a_new_cmd_module() -> None:
    """Happy: additive ``cli/profile_cmd.py`` (D10), not a root-callback fold-in."""
    path = CLI_DIR / "profile_cmd.py"
    assert path.is_file()
    source = path.read_text(encoding="utf-8")
    assert "recommend" in source
    app_src = (SRC_ROOT / "cli" / "app.py").read_text(encoding="utf-8")
    assert "profile_cmd" in app_src
    assert "add_typer" in app_src


@_W23
def test_root_help_lists_profile() -> None:
    """Functional: root help lists the ``profile`` command."""
    result = invoke("--help")
    help_text = plain(result.stdout + result.stderr)
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "profile" in help_text


@_W23
def test_profile_recommend_help_is_registered() -> None:
    """Functional: ``profile recommend`` help is registered."""
    result = require_registered("profile", "recommend", "--help", label="profile recommend")
    help_text = plain(result.stdout + result.stderr)
    assert "risk" in help_text.casefold()


@_W23
def test_profile_recommend_emits_auto_selected_name() -> None:
    """Functional: ``profile recommend --risk high`` prints security."""
    result = invoke("profile", "recommend", "--risk", "high")
    output = plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "security" in output


@_W23
def test_budget_exhaustion_is_partial_or_inconclusive_never_clean() -> None:
    """Happy: profile budget exhaustion is ``partial`` or ``inconclusive``, never passed."""
    module = require_module(_PROFILES_MODULE)
    exhaust = require_callable(module, "profile_budget_exhaustion_outcome")
    outcome = exhaust(profile="fast")
    value = outcome.value if isinstance(outcome, RunOutcome) else str(outcome)
    assert value in {"partial", "inconclusive"}
    assert value != "passed"
