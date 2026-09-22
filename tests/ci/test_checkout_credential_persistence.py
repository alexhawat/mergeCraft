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


# ── #790 — every shipped example exports the Action pin it runs ─────────────


_PIN_EXAMPLES = (
    "examples/workflows/mergecraft.yml",
    "examples/workflows/mergecraft-hardened.yml",
)

_PIN_TEMPLATES = (
    "scripts/example_workflows/minimal.yml.tpl",
    "scripts/example_workflows/hardened.yml.tpl",
)


@pytest.mark.parametrize("relative", _PIN_EXAMPLES)
def test_shipped_examples_export_the_pin_they_run(relative: str) -> None:
    """A consumer copying an example must record the pin it runs (#641).

    `resolve_action_pin_sha()` reads `MERGECRAFT_ACTION_SHA` and nothing else,
    and the container cannot see the workflow's `uses:` line. An example that
    omits it hands every copier an empty Action pin and no pin/image mismatch
    detection — the same gap `mergecraft init` had before #679.

    Ported from `pre-0.0.1` #682 (commit b72d7abe), where it never reached
    `main`.
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


def _action_steps(doc: object) -> list[dict[str, object]]:
    """Steps that run the mergeCraft action in a workflow document."""
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
            if isinstance(uses, str) and uses.startswith(
                ("__ACTION_REPO__@", "alexhawat/mergeCraft@")
            ):
                steps.append(step)
    return steps


@pytest.mark.parametrize("relative", _PIN_TEMPLATES)
def test_workflow_templates_export_the_pin_placeholder(relative: str) -> None:
    """The templates the examples are generated from export the pin too.

    `examples/workflows/*.yml` are generated from these templates, so a pin
    that lands only in the generated files would drift on the next
    regeneration. The exported value tracks the template's own `uses:` pin —
    `__ACTION_PIN__` — in the same `env:` block as the credentials, where the
    container reads it (#790).
    """
    path = Path(REPO_ROOT) / relative
    assert path.is_file(), f"missing {relative}"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = _action_steps(doc)
    assert steps, f"{relative} has no mergeCraft action step to check"
    for step in steps:
        env_block = step.get("env") or {}
        assert isinstance(env_block, dict)
        assert env_block.get("MERGECRAFT_ACTION_SHA") == "__ACTION_PIN__", (
            f"{relative}: the mergeCraft step must export "
            "MERGECRAFT_ACTION_SHA: __ACTION_PIN__ so the generated example "
            "records the pin it runs"
        )


def _readme_workflow_examples() -> list[str]:
    """Fenced yaml blocks in README that configure the action."""
    import re

    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```ya?ml\n(.*?)```", text, re.S)
    return [block for block in blocks if "alexhawat/mergeCraft@" in block]


def test_readme_examples_honour_a_dispatch_prompt_they_declare() -> None:
    """An example that advertises `workflow_dispatch` must actually use it.

    Ported from `pre-0.0.1` #682 (commit 7274cad2), where it never reached
    `main`.

    The port is deliberately stricter than the `pre-0.0.1` guard: there, the
    README example already declared a required `prompt` input and hardcoded
    the text passed to the action, so the guard only had to catch the
    hardcoding. `main`'s example declares no input at all, which makes the
    verbatim guard vacuous — it would pass green while the advertised
    `workflow_dispatch` path ignores any prompt. So this pins the contract the
    `pre-0.0.1` example (and `mergecraft init`) satisfies: declare the prompt
    input, and honour it.
    """
    examples = _readme_workflow_examples()
    assert examples, "no action example found in README"
    for block in examples:
        if "workflow_dispatch" not in block:
            continue
        assert "inputs:" in block, (
            "README example advertises workflow_dispatch but declares no prompt "
            "input; the event-aware example `mergecraft init` generates does"
        )
        assert "prompt" in block, (
            "README example advertises workflow_dispatch but declares no prompt "
            "input; the event-aware example `mergecraft init` generates does"
        )
        assert "github.event.inputs.prompt" in block or "inputs.prompt" in block, (
            "README example declares a workflow_dispatch prompt input but never "
            "passes it to the action; a dispatched run would ignore it"
        )
