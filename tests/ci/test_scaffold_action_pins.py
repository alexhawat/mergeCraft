"""Every action a consumer copies must be pinned to a full commit SHA.

A tag is mutable: an org that allows Actions only from SHA-pinned refs rejects a
tagged action at resolution time, and a moved tag silently changes the code a
workflow runs. The self-workflow already pins by SHA; the docs, templates,
generated examples and the `mergecraft init` scaffold must too, from the one
`checkout_sha` / `action_sha_minimal` source of truth in the shared defaults.
Consumer runs are also serialized per pull request, so a review cannot race the
sticky comment upsert on the same PR.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml
from scripts.render_example_workflows import render_all

from mergecraft.cli.init_cmd import _workflow_template
from mergecraft.pins import action_pin_minimal, load_example_defaults
from tests.ci.workflow_support import REPO_ROOT

_SHA = re.compile(r"^[0-9a-f]{40}$")
_LOCAL = "./"
# The hardened template asks the operator for a SHA they must supply; it is not
# a mutable tag, so it is exempt from the 40-hex assertion.
_HARDENED_PLACEHOLDER = "REPLACE_WITH_FULL_COMMIT_SHA"

# Locked, published values. `make pins-check` re-derives `action_sha_minimal`
# from the tag; these constants pin the pair this plan ships.
LOCKED_CHECKOUT_SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
LOCKED_ACTION_SHA = "521c0aedbf525a80a5bf6eddf0119ada85a8d381"

_RENDERED = render_all()


def _readme_action_block() -> str:
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```ya?ml\n(.*?)```", text, re.S)
    matches = [block for block in blocks if "alexhawat/mergeCraft@" in block]
    assert matches, "README has no action example"
    return matches[0]


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _surfaces() -> list[tuple[str, dict[str, Any]]]:
    payloads: list[tuple[str, str]] = [
        ("self workflow", _read(".github/workflows/mergecraft.yml")),
        ("minimal example", _read("examples/workflows/mergecraft.yml")),
        ("hardened example", _read("examples/workflows/mergecraft-hardened.yml")),
        ("dogfood artifact", _read("docs/artifacts/dogfood-mergecraft.yml")),
        ("rendered minimal template", _RENDERED["minimal"]),
        ("rendered hardened template", _RENDERED["hardened"]),
        ("init scaffold", _workflow_template()),
        ("README example", _readme_action_block()),
    ]
    docs: list[tuple[str, dict[str, Any]]] = []
    for label, text in payloads:
        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as exc:  # pragma: no cover - parse failure is the assertion
            raise AssertionError(f"{label} is not valid YAML: {exc}") from exc
        assert isinstance(loaded, dict), f"{label} did not parse as a mapping"
        docs.append((label, loaded))
    return docs


def _ordered_uses(doc: dict[str, Any]) -> list[str]:
    found: list[str] = []
    jobs = doc.get("jobs") or {}
    assert isinstance(jobs, dict)
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        job_uses = job.get("uses")
        if isinstance(job_uses, str):
            found.append(job_uses)
        steps = job.get("steps") or []
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if isinstance(uses, str):
                found.append(uses)
    return found


@pytest.mark.xfail(reason="green after SW3.2/SW3.3: every action pinned by SHA", strict=False)
def test_every_action_reference_is_a_full_commit_sha() -> None:
    offenders: list[str] = []
    for label, doc in _surfaces():
        for uses in _ordered_uses(doc):
            if uses.startswith(_LOCAL):
                continue
            if uses.endswith(f"@{_HARDENED_PLACEHOLDER}"):
                continue
            if "@" not in uses or not _SHA.fullmatch(uses.rsplit("@", 1)[1]):
                offenders.append(f"{label}: {uses}")
    assert not offenders, (
        f"mutable action refs remain: {offenders}; pin every owner/repo to a full commit SHA"
    )


@pytest.mark.xfail(reason="green after SW3.1/SW3.2: one checkout_sha source", strict=False)
def test_every_actions_checkout_uses_the_shared_checkout_sha() -> None:
    defaults = load_example_defaults()
    assert defaults.get("checkout_sha") == LOCKED_CHECKOUT_SHA
    offenders: list[str] = []
    for label, doc in _surfaces():
        for uses in _ordered_uses(doc):
            if (
                uses.startswith("actions/checkout@")
                and uses != f"actions/checkout@{LOCKED_CHECKOUT_SHA}"
            ):
                offenders.append(f"{label}: {uses}")
    assert not offenders, f"actions/checkout pins disagree with checkout_sha: {offenders}"


@pytest.mark.xfail(reason="green after SW3.1: defaults carry the mergeCraft SHA", strict=False)
def test_action_sha_minimal_matches_the_published_commit() -> None:
    defaults = load_example_defaults()
    assert defaults.get("action_sha_minimal") == LOCKED_ACTION_SHA
    assert defaults.get("action_pin_minimal") == action_pin_minimal()


@pytest.mark.xfail(reason="green after SW3.2/SW3.5: scaffold serializes per PR", strict=False)
def test_scaffold_serializes_runs_per_pull_request() -> None:
    scaffold = yaml.safe_load(_workflow_template())
    concurrency = scaffold.get("concurrency")
    assert isinstance(concurrency, dict), "init scaffold must declare a concurrency group"
    group = str(concurrency.get("group", ""))
    assert "pull_request.number" in group, "the group must be keyed on the PR number"
    assert concurrency.get("cancel-in-progress") is True


@pytest.mark.xfail(reason="green after SW3.2: minimal example serializes per PR", strict=False)
def test_minimal_template_serializes_runs_per_pull_request() -> None:
    template = yaml.safe_load(
        (REPO_ROOT / "scripts/example_workflows/minimal.yml.tpl").read_text(encoding="utf-8")
    )
    concurrency = template.get("concurrency")
    assert isinstance(concurrency, dict), "the minimal template must declare a concurrency group"
    group = str(concurrency.get("group", ""))
    assert "pull_request.number" in group, "the group must be keyed on the PR number"
    assert concurrency.get("cancel-in-progress") is True
