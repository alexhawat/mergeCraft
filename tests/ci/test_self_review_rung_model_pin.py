"""Every fallback rung must name the one model it runs and credential it uses.

A rung that walks the configured chain can advance into a provider it has no
credential for, and then reports a reviewer slot it was never meant to run. A
pinned rung runs exactly its `model:`, so the run's own record and its
credentials agree.
"""

from __future__ import annotations

from typing import Any

from tests.ci.workflow_support import job, load_workflow

_WORKFLOW = "mergecraft.yml"
_REVIEW_JOB = "review"
_MERGECRAFT_ACTION = "alexhawat/mergeCraft@"

# Provider prefix of `with.model` -> the credential env vars that rung must carry.
_PROVIDER_CREDENTIALS: dict[str, frozenset[str]] = {
    "nous": frozenset({"NOUS_API_KEY", "MERGECRAFT_CUSTOM_PROVIDER_API_KEY"}),
    "openai": frozenset({"OPENAI_API_KEY", "CODEX_AUTH_JSON"}),
    "anthropic": frozenset({"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}),
}


def _rungs() -> list[dict[str, Any]]:
    steps = job(load_workflow(_WORKFLOW), _REVIEW_JOB).get("steps")
    assert isinstance(steps, list), "review job steps must be a list"
    rungs = [
        step
        for step in steps
        if isinstance(step, dict)
        and isinstance(step.get("uses"), str)
        and step["uses"].startswith(_MERGECRAFT_ACTION)
    ]
    assert len(rungs) == 3, f"expected three review rungs, found {len(rungs)}"
    return rungs


def test_every_rung_pins_the_model_it_runs() -> None:
    for rung in _rungs():
        with_block = rung.get("with") or {}
        assert isinstance(with_block, dict)
        assert with_block.get("model_pin") == "enabled", (
            f"rung {rung.get('id')!r} does not set model_pin: enabled; it can walk "
            "into a provider it has no credential for"
        )


def test_every_rung_env_carries_the_credential_for_its_model() -> None:
    for rung in _rungs():
        with_block = rung.get("with") or {}
        assert isinstance(with_block, dict)
        model = str(with_block.get("model", ""))
        provider = model.split("/", 1)[0].lower()
        expected = _PROVIDER_CREDENTIALS.get(provider)
        assert expected is not None, f"unmapped provider {provider!r} in rung {rung.get('id')!r}"
        env_block = rung.get("env") or {}
        assert isinstance(env_block, dict)
        present = expected.intersection(env_block)
        assert present, (
            f"rung {rung.get('id')!r} runs {model!r} but its env carries none of {sorted(expected)}"
        )
