"""The wheel's packaging config excludes exactly the modules with no runtime caller.

Plan 46's Appendix A lists test/script-support modules that ship today. Screening
each one's callers showed that only ``evals/corpora.py`` has a shipped runtime
caller (``cli/eval_cmd.py`` and ``evals/human_batch.py`` import it); the rest are
reached only from tests, scripts, or the Make surface, so they can leave the
wheel.

This test pins the packaging config itself — it does **not** build a wheel. The
real, installed-wheel proof is ``make test-wheel-corpus`` (the corpus check plus
``mergecraft --help`` / ``mergecraft eval --help`` from a scratch venv), which CI
runs in ``build-dist``. If a module's absence breaks the installed CLI, this list
must shrink.
"""

from __future__ import annotations

import tomllib

from tests.ci.workflow_support import REPO_ROOT

_PYPROJECT = REPO_ROOT / "pyproject.toml"

# The seven modules the installed-wheel smoke tolerates dropping.
_EXCLUDED = (
    "src/mergecraft/evals/mcp_public.py",
    "src/mergecraft/evals/quality_metrics.py",
    "src/mergecraft/evals/skill_taxonomy_gate.py",
    "src/mergecraft/utils/git_ref.py",
    "src/mergecraft/integrations/live_providers.py",
    "src/mergecraft/mcp/codegen.py",
    "src/mergecraft/scm/errors.py",
)

# A shipped CLI path imports this one, so it must stay in the wheel.
_KEPT = "src/mergecraft/evals/corpora.py"


def _wheel_config() -> dict[str, object]:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert isinstance(wheel, dict)
    return wheel


def _normalize(pattern: str) -> str:
    return pattern.strip().removeprefix("./").lstrip("/")


def test_wheel_excludes_exactly_the_modules_with_no_runtime_caller() -> None:
    exclude = _wheel_config().get("exclude")
    assert isinstance(exclude, list), (
        "the wheel target declares no `exclude` list; the test/eval-support modules still ship"
    )
    assert exclude, "the wheel `exclude` list is empty"
    normalized = {_normalize(str(pattern)) for pattern in exclude}

    assert normalized == set(_EXCLUDED), (
        "the wheel exclusion list drifted; "
        f"extra={sorted(normalized - set(_EXCLUDED))} "
        f"missing={sorted(set(_EXCLUDED) - normalized)}"
    )


def test_wheel_keeps_the_module_with_a_runtime_caller() -> None:
    exclude = _wheel_config().get("exclude")
    assert isinstance(exclude, list)
    normalized = {_normalize(str(pattern)) for pattern in exclude}
    assert _KEPT not in normalized, (
        "evals/corpora.py has shipped runtime callers (cli/eval_cmd.py, "
        "evals/human_batch.py) and must stay in the wheel"
    )


def test_every_excluded_path_exists_on_disk() -> None:
    """An exclusion naming a path that does not exist is a stale pin."""
    for relative in _EXCLUDED:
        assert (REPO_ROOT / relative).is_file(), f"excluded path does not exist: {relative}"


def test_the_kept_runtime_module_exists() -> None:
    assert (REPO_ROOT / _KEPT).is_file(), f"runtime module missing: {_KEPT}"
