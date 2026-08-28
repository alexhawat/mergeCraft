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
