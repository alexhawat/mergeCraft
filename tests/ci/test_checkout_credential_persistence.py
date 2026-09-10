"""``persist-credentials`` must stay false wherever mergeCraft reviews a PR.

actions/checkout persists its token as
``http.https://github.com/.extraheader = AUTHORIZATION: basic ...`` in
``.git/config``. mergeCraft's git layer adds its own ``Authorization`` header
(``utils/git_setup.py`` ``git_env_for_token``). ``extraHeader`` is multi-valued
in git, so the second does not replace the first — both go on one request and
GitHub answers ``400 Duplicate header: "Authorization"``. ``checkout_pr`` then
fails, review scope is never established, and every terminal verdict is
rejected with "requires review scope".

Observed on PR #524 (run 33086156079): the agent looped on the unsatisfiable
error, mergeCraft resumed the whole session once, and the run died at
9,395,943 tokens against a 5,000,000 budget having posted no review at all.

The action authenticates from its own ``token:`` input, so nothing needs to be
persisted for it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.ci.workflow_support import REPO_ROOT

# Every file that checks out a repo mergeCraft then reviews: our own workflow,
# the shipped consumer example, the template that generates it, and the
# dogfood artifact copied into docs.
_WORKFLOWS = (
    ".github/workflows/mergecraft.yml",
    "examples/workflows/mergecraft-hardened.yml",
    "scripts/example_workflows/hardened.yml.tpl",
    "docs/artifacts/dogfood-mergecraft.yml",
)


def _checkout_steps(doc: object) -> list[dict[str, object]]:
    steps: list[dict[str, object]] = []
    jobs = doc.get("jobs") if isinstance(doc, dict) else None
    if not isinstance(jobs, dict):
        return steps
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        for step in job.get("steps") or []:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if isinstance(uses, str) and uses.startswith("actions/checkout@"):
                steps.append(step)
    return steps


@pytest.mark.parametrize("relpath", _WORKFLOWS)
def test_checkout_does_not_persist_credentials(relpath: str) -> None:
    path = Path(REPO_ROOT) / relpath
    assert path.is_file(), f"missing {relpath}"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = _checkout_steps(doc)
    assert steps, f"{relpath} has no actions/checkout step to check"
    for step in steps:
        with_block = step.get("with") or {}
        assert isinstance(with_block, dict)
        # Accept the bool and the YAML-string spellings alike.
        persist = str(with_block.get("persist-credentials")).lower()
        assert persist != "true", (
            f"{relpath}: actions/checkout must not persist credentials — a persisted "
            "extraheader collides with mergeCraft's own Authorization header and "
            "GitHub rejects the fetch with 400 Duplicate header"
        )


_PIN_EXAMPLES = (
    "examples/workflows/mergecraft.yml",
    "examples/workflows/mergecraft-hardened.yml",
)


@pytest.mark.parametrize("relative", _PIN_EXAMPLES)
def test_shipped_examples_export_the_pin_they_run(relative: str) -> None:
    """A consumer copying an example must record the pin it runs (#641).

    `resolve_action_pin_sha()` reads `MERGECRAFT_ACTION_SHA` and nothing else,
    and the container cannot see the workflow's `uses:` line. An example that
    omits it hands every copier an empty Action pin and no pin/image mismatch
    detection — the same gap `mergecraft init` had before #679.
    """
    import re

    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    uses = re.findall(r"uses:\s*alexhawat/mergeCraft@(\S+)", text)
    exported = re.findall(r"MERGECRAFT_ACTION_SHA:\s*(\S+)", text)

    assert uses, f"{relative} no longer references the action"
    assert exported, f"{relative} does not export MERGECRAFT_ACTION_SHA"
    assert set(exported) == set(uses), (
        f"{relative} exports {exported} but runs {uses}; "
        "the recorded pin would not be the code that ran"
    )


def _readme_workflow_examples() -> list[str]:
    """Fenced yaml blocks in README that configure the action."""
    import re

    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```ya?ml\n(.*?)```", text, re.S)
    return [block for block in blocks if "alexhawat/mergeCraft@" in block]


def test_readme_examples_honour_a_dispatch_prompt_they_declare() -> None:
    """An example that advertises `workflow_dispatch` must actually use it.

    README declared a required `prompt` input and then passed a hardcoded
    string to the action, so a manually dispatched run silently ignored what
    the operator typed — unlike the workflow `mergecraft init` generates and
    unlike both shipped example templates, which resolve it event-aware.
    """
    examples = _readme_workflow_examples()
    assert examples, "no action example found in README"
    for block in examples:
        if "workflow_dispatch" not in block or "inputs:" not in block:
            continue
        assert "github.event.inputs.prompt" in block or "inputs.prompt" in block, (
            "README example declares a workflow_dispatch prompt input but never "
            "passes it to the action; a dispatched run would ignore it"
        )
