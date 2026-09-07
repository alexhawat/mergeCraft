"""W2 — E2E reusable workflow must gate ``build-images`` (R-F1).

YAML-parse contracts only: these tests do not require a live GitHub Actions run.
W2 landed the ``workflow_call`` + ``e2e-gate`` graph; these are real passes.
SHA-pin assertions must stay green if a tag pin sneaks in.
"""

from __future__ import annotations

import pytest

from tests.ci.workflow_support import (
    as_list,
    assert_third_party_uses_sha_pinned,
    job,
    load_workflow,
    workflow_on,
)


def test_e2e_yml_on_includes_workflow_call() -> None:
    """D4 — ``e2e.yml`` is reusable; ``on:`` includes ``workflow_call``."""
    on_block = workflow_on(load_workflow("e2e.yml"))
    assert isinstance(on_block, dict), f"e2e.yml on: is not a mapping: {on_block!r}"
    assert "workflow_call" in on_block, "e2e.yml on: is missing workflow_call (D4)"
    for trigger in ("pull_request", "schedule", "workflow_dispatch"):
        assert trigger in on_block, f"e2e.yml dropped existing trigger {trigger!r}"


def test_ci_cd_has_e2e_gate_job() -> None:
    """``ci-cd.yml`` calls the reusable E2E workflow after ``verify``."""
    gate = job(load_workflow("ci-cd.yml"), "e2e-gate")
    assert as_list(gate.get("needs")) == ["verify"] or "verify" in as_list(gate.get("needs"))
    uses = gate.get("uses")
    assert uses == "./.github/workflows/e2e.yml", f"e2e-gate uses: {uses!r}"


def test_required_e2e_gate_has_no_live_provider_credentials() -> None:
    """The release gate uses fake providers and never inherits live provider keys."""
    gate = job(load_workflow("ci-cd.yml"), "e2e-gate")
    assert "secrets" not in gate
    assert gate["with"] == {"required-security": True}


def test_build_images_needs_e2e_gate() -> None:
    """D5 — an unproven SHA must not produce a pushed digest."""
    needs = as_list(job(load_workflow("ci-cd.yml"), "build-images").get("needs"))
    assert "e2e-gate" in needs, f"build-images.needs missing e2e-gate: {needs}"
    assert "verify" in needs, f"build-images.needs dropped verify: {needs}"


def test_removing_e2e_gate_from_build_images_needs_fails() -> None:
    """Guard-deletion: dropping ``e2e-gate`` from ``build-images.needs`` fails this test."""
    needs = as_list(job(load_workflow("ci-cd.yml"), "build-images").get("needs"))
    assert "e2e-gate" in needs, "e2e-gate was removed from build-images.needs (R-F1 regression)"


def test_build_dist_does_not_need_e2e_gate() -> None:
    """D11 — sdist/wheel is not gated on Action-image E2E."""
    dist = job(load_workflow("ci-cd.yml"), "build-dist")
    needs = as_list(dist.get("needs"))
    assert "e2e-gate" not in needs, f"build-dist must not need e2e-gate (D11): {needs}"
    assert "verify" in needs, f"build-dist.needs should remain verify: {needs}"


@pytest.mark.parametrize("workflow", ["e2e.yml", "ci-cd.yml"])
def test_touched_workflows_third_party_uses_are_sha_pinned(workflow: str) -> None:
    """Convention 2 — every third-party ``uses:`` stays 40-hex SHA-pinned."""
    assert_third_party_uses_sha_pinned(workflow)


def _condition(expression: str, context: dict[str, object]) -> bool:
    """Interpret the small Actions expression subset used by these release jobs.

    No Python eval: unsupported syntax fails the test instead of becoming true.
    """
    import re

    text = expression.removeprefix("${{").removesuffix("}}").strip()
    token_re = re.compile(r"\s*(\|\||&&|==|!=|!|\(|\)|,|'[^']*'|[A-Za-z_][A-Za-z0-9_.-]*)")
    tokens: list[str] = []
    while text:
        match = token_re.match(text)
        assert match is not None, f"unsupported release expression: {text!r}"
        tokens.append(match[1])
        text = text[match.end() :]
    index = 0

    def atom() -> object:
        nonlocal index
        token = tokens[index]
        index += 1
        if token == "!":
            return not atom()
        if token == "(":
            result = disjunction()
            assert tokens[index] == ")"
            index += 1
            return result
        if token == "startsWith":
            assert tokens[index] == "("
            index += 1
            value = atom()
            assert tokens[index] == ","
            index += 1
            prefix = atom()
            assert tokens[index] == ")"
            index += 1
            return str(value).startswith(str(prefix))
        if token.startswith("'"):
            return token[1:-1]
        if token in ("true", "false"):
            return token == "true"
        assert token in context, f"unrecognized release expression identifier {token}"
        return context[token]

    def equality() -> object:
        nonlocal index
        left = atom()
        if index < len(tokens) and tokens[index] in ("==", "!="):
            op = tokens[index]
            index += 1
            right = atom()
            return left == right if op == "==" else left != right
        return left

    def conjunction() -> bool:
        nonlocal index
        result = bool(equality())
        while index < len(tokens) and tokens[index] == "&&":
            index += 1
            right = bool(equality())
            result = result and right
        return result

    def disjunction() -> bool:
        nonlocal index
        result = conjunction()
        while index < len(tokens) and tokens[index] == "||":
            index += 1
            right = conjunction()
            result = result or right
        return result

    result = disjunction()
    assert index == len(tokens)
    return result


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "pull_request"])
@pytest.mark.parametrize(
    "ref",
    [
        "refs/heads/main",
        "refs/heads/pre-0.0.1",
        "refs/heads/release/1.0",
        "refs/tags/v1.0",
        "refs/heads/feature",
        "refs/pull/42/merge",
    ],
)
def test_release_graph_executes_required_e2e_for_allowed_events(event: str, ref: str) -> None:
    """Evaluate actual workflow predicates with the caller's event retained."""
    ci = load_workflow("ci-cd.yml")
    gate = job(ci, "e2e-gate")
    context: dict[str, object] = {
        "github.event_name": event,
        "github.ref": ref,
        "inputs.required-security": gate["with"]["required-security"],
    }
    e2e = job(load_workflow("e2e.yml"), "e2e-pr")
    assert _condition(e2e["if"], context)
    build = job(ci, "build-images")
    expected = event in ("push", "workflow_dispatch") and ref in (
        "refs/heads/main",
        "refs/heads/pre-0.0.1",
        "refs/heads/release/1.0",
        "refs/tags/v1.0",
    )
    assert _condition(build["if"], context) == expected
    assert not _condition(job(load_workflow("e2e.yml"), "e2e-nightly")["if"], context)


@pytest.mark.parametrize("failure", ["failure", "cancelled", "skipped"])
@pytest.mark.parametrize(
    "failed_job",
    ["verify", "e2e-gate", "build-images", "sbom-scan", "sign-attest", "verify-images"],
)
def test_release_graph_never_promotes_after_unsuccessful_prerequisite(
    failure: str, failed_job: str
) -> None:
    """Simulate Actions' implicit success gate across the real needs DAG."""
    ci = load_workflow("ci-cd.yml")
    context: dict[str, object] = {"github.event_name": "push", "github.ref": "refs/heads/main"}
    results: dict[str, str] = {}
    for name in (
        "verify",
        "e2e-gate",
        "build-images",
        "sbom-scan",
        "sign-attest",
        "verify-images",
        "promote",
    ):
        spec = job(ci, name)
        if name == failed_job:
            results[name] = failure
            continue
        assert "always(" not in str(spec.get("if", "")), (
            "publishing cannot bypass failed dependencies"
        )
        success = all(results[parent] == "success" for parent in as_list(spec.get("needs")))
        eligible = _condition(spec["if"], context) if spec.get("if") else True
        results[name] = "success" if success and eligible else "skipped"
    assert results["promote"] == "skipped"
