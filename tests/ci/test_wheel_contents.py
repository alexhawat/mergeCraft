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

# The twelve modules the installed-wheel smoke tolerates dropping. The last five
# were re-measured on the tree that landed them (#947): none has a production
# importer, and every caller is a Make target, ``scripts/``, a workflow step
# run from the checkout, or a test.
_EXCLUDED = (
    "src/mergecraft/evals/mcp_public.py",
    "src/mergecraft/evals/quality_metrics.py",
    "src/mergecraft/evals/skill_taxonomy_gate.py",
    "src/mergecraft/utils/git_ref.py",
    "src/mergecraft/integrations/live_providers.py",
    "src/mergecraft/mcp/codegen.py",
    "src/mergecraft/scm/errors.py",
    "src/mergecraft/scm/webhooks.py",
    "src/mergecraft/evidence/shadow_compare.py",
    "src/mergecraft/evals/human_batch.py",
    "src/mergecraft/evals/skill.py",
    "src/mergecraft/agents/catalog_docs.py",
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


# Each re-measured module is reached only from the checkout; if a shipped module
# starts importing one, excluding it would break the installed CLI.
_CHECKOUT_ONLY = (
    "mergecraft.scm.webhooks",
    "mergecraft.evidence.shadow_compare",
    "mergecraft.evals.human_batch",
    "mergecraft.evals.skill",
    "mergecraft.agents.catalog_docs",
)


def test_no_shipped_module_imports_a_checkout_only_module() -> None:
    """The exclusion is only safe while nothing the wheel ships imports these five."""
    import ast

    src = REPO_ROOT / "src" / "mergecraft"
    excluded_files = {REPO_ROOT / relative for relative in _EXCLUDED}
    offenders: list[str] = []
    for path in sorted(src.rglob("*.py")):
        if path in excluded_files:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported.extend(f"{node.module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            for name in imported:
                if name in _CHECKOUT_ONLY:
                    offenders.append(f"{path.relative_to(REPO_ROOT)} imports {name}")
    assert not offenders, offenders


def test_every_checkout_only_module_has_a_checkout_caller() -> None:
    """A module nobody calls at all is dead code, not a packaging decision."""
    callers = "\n".join(
        (REPO_ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "Makefile",
            ".github/workflows/ci.yml",
        )
    )
    tests = "\n".join(
        path.read_text(encoding="utf-8") for path in (REPO_ROOT / "tests").rglob("*.py")
    )
    for module in _CHECKOUT_ONLY:
        short = module.removeprefix("mergecraft.")
        assert module in callers or module in tests or short in tests, (
            f"{module} has no checkout caller; remove it rather than excluding it"
        )
