"""Blast radius reads source, dependency and deployment paths outside ``src/`` (#1309).

Any hand-written path that is not documentation, a test or generated output is
source, wherever the repository keeps it. Dependency manifests come from the
shared :mod:`mergecraft.review_policy.manifest_names` list, deployment paths
include Dockerfiles, composite actions and Kubernetes / Helm trees, and the
SQL and ``rm`` checks tolerate extra whitespace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from mergecraft.classify.blast_radius import BlastRadiusClassification


def _classify(
    paths: list[str], *, added: int = 400, deleted: int = 300, diff: str = ""
) -> BlastRadiusClassification:
    from mergecraft.classify.blast_radius import classify_blast_radius

    stats: dict[str, Any] = {"lines_added": added, "lines_deleted": deleted}
    if diff:
        stats["diff"] = diff
    return classify_blast_radius({"changed_paths": paths, "diff_stats": stats})


def _codes(result: BlastRadiusClassification) -> set[str]:
    return {reason.code for reason in result.reasons}


@pytest.mark.parametrize(
    "path",
    ["app/server.py", "lib/payments_api.py", "cmd/main.go", "server.js"],
    ids=["app-dir", "lib-dir", "go-cmd", "root-file"],
)
def test_a_large_source_change_outside_src_is_not_eligible(path: str) -> None:
    result = _classify([path])

    assert result.auto_merge_lane != "eligible"
    assert "source.changed" in _codes(result)


@pytest.mark.parametrize(
    "path",
    [
        "Dockerfile",
        "docker/Dockerfile.prod",
        ".github/actions/deploy/action.yml",
        "deploy/k8s/prod.yaml",
        "k8s/service.yaml",
        "charts/helm/values.yaml",
    ],
    ids=["dockerfile", "dockerfile-variant", "composite-action", "deploy-dir", "k8s", "helm"],
)
def test_deployment_paths_are_high(path: str) -> None:
    result = _classify([path], added=1, deleted=1)

    assert result.lane == "high"
    assert "paths.deployment" in _codes(result)


@pytest.mark.parametrize(
    "path",
    ["Gemfile", "composer.json", "Pipfile.lock", "requirements-dev.txt", "requirements/prod.txt"],
    ids=["gemfile", "composer", "pipfile-lock", "requirements-dev", "requirements-dir"],
)
def test_shared_dependency_manifests_are_a_dependency_change(path: str) -> None:
    result = _classify([path], added=1, deleted=1)

    assert "deps.changed" in _codes(result)
    assert result.auto_merge_lane != "eligible"


@pytest.mark.parametrize(
    ("diff", "code"),
    [
        ("+DROP  TABLE users;", "diff.destructive_sql"),
        ("+alter\ttable users add column x int;", "diff.destructive_sql"),
        ("+rm -fr /", "diff.irreversible_command"),
        ("+rm  -rf build", "diff.irreversible_command"),
        ("+rm --recursive --force /srv", "diff.irreversible_command"),
        ("+terraform   destroy -auto-approve", "diff.irreversible_command"),
    ],
    ids=["drop-double-space", "alter-tab", "rm-fr", "rm-double-space", "rm-long-flags", "tf"],
)
def test_diff_checks_tolerate_whitespace_and_flag_order(diff: str, code: str) -> None:
    result = _classify(["scripts/clean.sh"], added=1, deleted=0, diff=diff)

    assert code in _codes(result)
    assert result.lane == "high"


def test_a_small_single_source_file_outside_src_keeps_the_carve_out() -> None:
    result = _classify(["app/util.py"], added=2, deleted=1)

    assert result.lane == "low"
    assert "source.small_isolated" in _codes(result)


@pytest.mark.parametrize(
    "paths",
    [["README.md"], ["docs/guide.md"], ["tests/test_app.py"], ["app/test_util.py"]],
    ids=["readme", "docs", "tests-dir", "test-file"],
)
def test_docs_and_tests_are_not_source(paths: list[str]) -> None:
    result = _classify(paths)

    assert "source.changed" not in _codes(result)
    assert "tests.missing" not in _codes(result)


def test_source_with_a_test_change_beside_it_has_tests() -> None:
    result = _classify(["app/server.py", "app/server_test.py"])

    assert "tests.missing" not in _codes(result)
    assert "source.changed" in _codes(result)


@pytest.mark.parametrize(
    "diff",
    [
        "+db_password = hunter2",
        "+DB_PASSWORD = hunter2",
        "+dbPassword = hunter2",
        "+jwt_secret_key = abc",
        "+ssh_private_key=abc",
        "+password = hunter2",
    ],
    ids=["prefixed", "upper", "camel", "jwt-secret-key", "no-space", "plain"],
)
def test_prefixed_secret_assignments_are_detected(diff: str) -> None:
    result = _classify(["app/settings.py"], added=1, deleted=0, diff=diff)

    assert "diff.secret_assignment" in _codes(result)


@pytest.mark.parametrize(
    "paths",
    [
        ["LICENSE"],
        ["NOTICE"],
        [".github/CODEOWNERS"],
        ["docs/page.mdx"],
        ["host/evals/case.jsonl"],
        ["data/rows.csv"],
        ["config/schema.xml"],
    ],
    ids=["license", "notice", "codeowners", "mdx", "jsonl", "csv", "xml"],
)
def test_docs_and_data_files_are_not_source(paths: list[str]) -> None:
    result = _classify(paths)

    assert "source.changed" not in _codes(result)
    assert "tests.missing" not in _codes(result)


@pytest.mark.parametrize(
    "path",
    [
        "charts/api/templates/deployment.yaml",
        "charts/api/Chart.yaml",
        "kustomize/overlays/prod/patch.yaml",
        "base/kustomization.yaml",
    ],
    ids=["helm-chart-template", "chart-yaml", "kustomize-overlay", "kustomization"],
)
def test_helm_and_kustomize_layouts_are_deployment(path: str) -> None:
    result = _classify([path], added=1, deleted=1)

    assert "paths.deployment" in _codes(result)


@pytest.mark.parametrize(
    "path",
    ["docs/deploy/runbook.md", "tests/fixtures/k8s/values.yaml"],
    ids=["docs-under-deploy", "test-fixture-under-k8s"],
)
def test_docs_and_test_fixtures_under_deploy_dirs_are_not_deployment(path: str) -> None:
    result = _classify([path], added=1, deleted=1)

    assert "paths.deployment" not in _codes(result)
