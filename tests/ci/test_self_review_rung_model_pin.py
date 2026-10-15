"""Every fallback rung must name the one model it runs and credential it uses.

A rung that walks the configured chain can advance into a provider it has no
credential for, and then reports a reviewer slot it was never meant to run. A
pinned rung runs exactly its `model:`, so the run's own record and its
credentials agree.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mergecraft.config.runtime_provider_registry import indexed_env_key
from mergecraft.config.settings import load_repo_settings
from tests.ci.workflow_support import REPO_ROOT, job, load_workflow

_WORKFLOW = "mergecraft.yml"
_REVIEW_JOB = "review"
_MERGECRAFT_ACTION = "alexhawat/mergeCraft@"

# Built-in provider prefix of `with.model` -> the credential env vars that rung
# must carry. A provider registered in the repo config instead needs its
# indexed slot (see `_registered_credentials`).
_PROVIDER_CREDENTIALS: dict[str, frozenset[str]] = {
    "openai": frozenset({"OPENAI_API_KEY", "CODEX_AUTH_JSON"}),
    "anthropic": frozenset({"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"}),
}


def _registered_credentials() -> dict[str, frozenset[str]]:
    """Map each provider registered in the repo config to its indexed API-key slot."""
    settings = load_repo_settings(root=Path(REPO_ROOT))
    return {
        entry.label.lower(): frozenset({indexed_env_key(entry.env_index, "API_KEY")})
        for entry in settings.providers
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
        expected = _registered_credentials().get(provider) or _PROVIDER_CREDENTIALS.get(provider)
        assert expected is not None, f"unmapped provider {provider!r} in rung {rung.get('id')!r}"
        env_block = rung.get("env") or {}
        assert isinstance(env_block, dict)
        present = expected.intersection(env_block)
        assert present, (
            f"rung {rung.get('id')!r} runs {model!r} but its env carries none of {sorted(expected)}"
        )


def test_the_first_rung_runs_a_provider_the_repo_config_registers() -> None:
    """``opencode-go/...`` is refused unless registered, whatever key the env carries."""
    first = _rungs()[0]
    model = str((first.get("with") or {}).get("model", ""))
    assert model == "opencode-go/deepseek-v4.1-flash", model
    assert "opencode-go" in _registered_credentials(), (
        "the first rung needs an `opencode-go` entry under providers:"
    )
