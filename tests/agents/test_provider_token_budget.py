"""E4 — lift J2 ``TokenBudget`` + kill-switch to every provider path (E-D9).

Closes #723 item 8 without forking a second budget system. Lazy imports keep
collection clean.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any, get_args

import pytest
from tests.agents.conftest import make_agent_run_context
from tests.evals.support_eval_calibration import PROVIDER_PATHS

from mergecraft.agents.shared import AgentImpl, AgentResult
from mergecraft.jev.cost import TokenBudget as JevTokenBudget
from mergecraft.jev.cost import compute_cost as jev_compute_cost


def _budget_mod() -> Any:
    import mergecraft.agents.token_budget as module

    return module


def test_token_budget_imports_in_a_fresh_interpreter() -> None:
    """Action ``main()`` lazy-imports this before any ``jev`` import."""
    result = subprocess.run(
        [sys.executable, "-c", "import mergecraft.agents.token_budget"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_token_budget_is_the_jev_class_not_a_fork() -> None:
    """E-D9 — the lift re-exports J2's ``TokenBudget``, it does not invent one."""
    module = _budget_mod()
    assert module.TokenBudget is JevTokenBudget
    assert module.compute_cost is jev_compute_cost


def test_provider_paths_cover_every_agent_and_jev() -> None:
    """Every reviewing provider path is in the lift set, including Jev."""
    from mergecraft.agents import agents

    module = _budget_mod()
    paths = frozenset(module.PROVIDER_PATHS)
    assert paths == PROVIDER_PATHS
    assert set(agents) <= paths
    assert "jev" in paths


@pytest.mark.parametrize("provider", sorted(PROVIDER_PATHS - {"jev"}))
async def test_kill_switch_stops_provider_dispatch(tmp_path: Path, provider: str) -> None:
    """Guard-deletion: a stopped budget must prevent ``_run`` from dispatching."""
    module = _budget_mod()
    budget = JevTokenBudget(max_tokens=1)
    assert budget.record_usage(input_tokens=2, output_tokens=0) is False
    assert budget.should_stop() is True

    dispatched = False

    async def fake_run(_ctx: object) -> AgentResult:
        nonlocal dispatched
        dispatched = True
        return AgentResult(success=True)

    async def fake_install(_token: str | None = None) -> str:
        return "ok"

    impl = AgentImpl(name=provider, _install=fake_install, _run=fake_run)
    ctx = make_agent_run_context(tmp_path, resolved_model=f"{provider}-pinned")
    with module.bind_run_budget(budget):
        result = await impl.run(ctx)
    assert dispatched is False
    assert result.success is False
    blob = f"{result.error} {result.diagnostics}".casefold()
    reason = (result.diagnostics or {}).get("reason")
    assert reason == "kill_switch" or "kill_switch" in blob


def test_unreported_tokens_stay_honest_on_the_shared_path() -> None:
    """Same J2 contract: ``None`` tokens are not recorded as zero cost."""
    module = _budget_mod()
    budget = JevTokenBudget(max_tokens=50)
    accepted = module.record_provider_usage(budget, input_tokens=None, output_tokens=None)
    assert accepted is True
    assert budget.tokens_used == 0
    assert budget.cost_known is False
    assert budget.stopped is False
    assessment = module.compute_cost(model="claude-sonnet-5", input_tokens=None, output_tokens=8)
    assert assessment.cost_known is False
    assert assessment.cost_usd is None


def test_record_provider_usage_does_not_zero_partial_none() -> None:
    """Guard: a wrapper that coerces ``None`` to ``0`` fails this test."""
    module = _budget_mod()
    budget = JevTokenBudget(max_tokens=10)
    accepted = module.record_provider_usage(budget, input_tokens=None, output_tokens=1)
    assert accepted is True
    assert budget.tokens_used == 0
    assert budget.cost_known is False
    assert budget.stopped is False


async def test_concurrent_same_credential_shares_one_budget(tmp_path: Path) -> None:
    """Two provider dispatches bearing the same bound budget share one cap."""
    module = _budget_mod()
    budget = JevTokenBudget(max_tokens=10_000)

    async def fake_run(_ctx: object) -> AgentResult:
        module.record_provider_usage(budget, input_tokens=50, output_tokens=10)
        return AgentResult(success=True)

    async def fake_install(_token: str | None = None) -> str:
        return "ok"

    impl = AgentImpl(name="claude", _install=fake_install, _run=fake_run)
    ctx = make_agent_run_context(tmp_path, resolved_model="claude-sonnet-5")
    with module.bind_run_budget(budget):
        first, second = await asyncio.gather(impl.run(ctx), impl.run(ctx))
    assert first.success is True
    assert second.success is True
    assert budget.tokens_used == 120
    assert budget.tokens_used <= budget.max_tokens


def test_budget_is_keyed_by_pinned_model_id() -> None:
    """Price / budget lookup stays keyed by pinned model id (J2 PRICE_TABLE)."""
    module = _budget_mod()
    from mergecraft.jev.cost import PRICE_TABLE
    from mergecraft.jev.types import PINNED_MODEL

    budget = module.token_budget_for(model=PINNED_MODEL, max_tokens=100)
    assert isinstance(budget, JevTokenBudget)
    assert budget.max_tokens == 100
    assert PINNED_MODEL in PRICE_TABLE
    known = module.compute_cost(model=PINNED_MODEL, input_tokens=1_000_000, output_tokens=1_000_000)
    unknown = module.compute_cost(
        model="not-a-pinned-model", input_tokens=1_000_000, output_tokens=1_000_000
    )
    assert known.cost_known is True
    assert unknown.cost_known is False


def test_kill_switch_stop_reason_is_the_j2_token() -> None:
    """Skip / stop reason stays ``kill_switch``, not an English sentence."""
    module = _budget_mod()
    budget = JevTokenBudget(max_tokens=1)
    budget.record_usage(input_tokens=2, output_tokens=0)
    stopped = module.apply_kill_switch(budget)
    assert stopped == "kill_switch"
    assert module.apply_kill_switch(JevTokenBudget(max_tokens=100)) == "ok"


def test_current_run_budget_reads_the_bound_cap() -> None:
    """Public bind reader: unbound is None; bind yields the same object."""
    module = _budget_mod()
    assert module.current_run_budget() is None
    budget = JevTokenBudget(max_tokens=50)
    with module.bind_run_budget(budget):
        assert module.current_run_budget() is budget
    assert module.current_run_budget() is None


def test_kill_switch_status_is_the_j2_literal_pair() -> None:
    """KillSwitchStatus is Literal['kill_switch', 'ok'] — apply_kill_switch's type."""
    module = _budget_mod()
    assert get_args(module.KillSwitchStatus) == ("kill_switch", "ok")
    stopped = JevTokenBudget(max_tokens=1)
    stopped.record_usage(input_tokens=2, output_tokens=0)
    statuses = get_args(module.KillSwitchStatus)
    assert module.apply_kill_switch(stopped) in statuses
    assert module.apply_kill_switch(JevTokenBudget(max_tokens=100)) in statuses
