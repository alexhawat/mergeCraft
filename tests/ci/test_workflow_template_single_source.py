"""The init scaffold and the example workflows come from one template (#1348).

``mergecraft init`` once carried its own copy of the workflow, which drifted from
``examples/workflows/mergecraft.yml``: the examples granted an unused
``id-token: write``, and a commented step pointed at a local path that only
exists inside the mergeCraft repository. Consumers copy these files into
workflows that hold secrets, so the surfaces must stay identical and must not
interpolate ``${{ }}`` context into ``run:`` scripts.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml
from scripts.render_example_workflows import render_all

from mergecraft.cli.init_cmd import _workflow_template
from tests.ci.workflow_support import REPO_ROOT

_EXPRESSION = re.compile(r"\$\{\{.*?\}\}", re.S)

_CONSUMER_SURFACES = (
    "examples/workflows/mergecraft.yml",
    "examples/workflows/mergecraft-hardened.yml",
    "docs/artifacts/dogfood-mergecraft.yml",
    "src/mergecraft/data/example_workflows/minimal.yml.tpl",
    "scripts/example_workflows/hardened.yml.tpl",
)


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_init_scaffold_equals_the_minimal_example() -> None:
    assert _workflow_template() == _read("examples/workflows/mergecraft.yml")


def test_init_scaffold_equals_the_rendered_minimal_template() -> None:
    assert _workflow_template() == render_all()["minimal"]


@pytest.mark.parametrize("relative", _CONSUMER_SURFACES)
def test_no_surface_grants_id_token(relative: str) -> None:
    """mergeCraft never mints OIDC tokens, so no copied workflow should request one."""
    assert "id-token" not in _read(relative)
    assert "id-token" not in _workflow_template()


def test_readme_example_does_not_grant_id_token() -> None:
    readme = _read("README.md")
    blocks = re.findall(r"```ya?ml\n(.*?)```", readme, re.S)
    assert any("alexhawat/mergeCraft@" in block for block in blocks)
    assert all("id-token" not in block for block in blocks if "alexhawat/mergeCraft@" in block)


def test_minimal_template_has_no_unusable_installation_token_step() -> None:
    """``./get-installation-token`` is a path inside this repo; a consumer cannot use it."""
    for text in (_workflow_template(), _read("examples/workflows/mergecraft.yml")):
        assert "./get-installation-token" not in text
        assert "get-installation-token" not in text


@pytest.mark.parametrize("relative", _CONSUMER_SURFACES)
def test_run_scripts_take_context_through_env(relative: str) -> None:
    """A ``${{ }}`` expression in ``run:`` is script injection; pass it via ``env:``."""
    doc: Any = yaml.safe_load(_read(relative).replace("__", "X"))
    offenders: list[str] = []
    for job_name, job in (doc.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            run = step.get("run")
            if isinstance(run, str) and _EXPRESSION.search(run):
                offenders.append(f"{job_name}: {step.get('name')}: {_EXPRESSION.findall(run)}")
    assert not offenders, offenders


@pytest.mark.parametrize(
    "relative",
    ["scripts/example_workflows/hardened.yml.tpl", "docs/artifacts/dogfood-mergecraft.yml"],
)
def test_base_ref_reaches_the_script_as_an_env_var(relative: str) -> None:
    doc: Any = yaml.safe_load(_read(relative).replace("__", "X"))
    steps = doc["jobs"]["review"]["steps"]
    step = next(s for s in steps if s.get("name") == "Ensure PR base ref exists locally")
    assert step["env"] == {"BASE_REF": "${{ github.event.pull_request.base.ref }}"}
    assert 'base="${BASE_REF}"' in step["run"]
