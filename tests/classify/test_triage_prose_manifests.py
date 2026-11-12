"""``.txt`` build and dependency manifests are never ``prose``.

``CMakeLists.txt`` and every requirements or constraints file, whatever its exact
name or directory, gets a full review. Every case runs through :func:`triage_diff`
with ``prose`` opted in to ``skipLlm``.
"""

from __future__ import annotations

import pytest


def _prose_diff(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        "@@ -1,1 +1,1 @@\n-hello world\n+hello there\n"
    )


def _tier(path: str) -> str:
    from mergecraft.classify.triage import triage_diff
    from mergecraft.config.settings import FastPathSettings

    config = FastPathSettings.model_validate({"enabled": True, "skipLlm": ["prose"]})
    return triage_diff(_prose_diff(path), config=config, head_files={path: "hello there\n"}).tier


_MANIFEST_PATHS = [
    "CMakeLists.txt",
    "src/CMakeLists.txt",
    "requirements/prod.txt",
    "requirements-test.txt",
    "dev-requirements.txt",
    "constraints.txt",
    "constraints-py311.txt",
    "Requirements.txt",
    "requirements.txt",
    "requirements-dev.txt",
]


@pytest.mark.parametrize("path", _MANIFEST_PATHS, ids=_MANIFEST_PATHS)
def test_txt_build_and_dependency_manifests_get_a_full_review(path: str) -> None:
    assert _tier(path) == "full"


def test_a_docs_text_file_still_skips() -> None:
    assert _tier("docs/notes.txt") == "skip"


@pytest.mark.parametrize(
    "path",
    ["requirements/prod.txt", "requirements-test.txt", "constraints.txt", "Requirements.txt"],
    ids=["requirements-dir", "requirements-suffix", "constraints", "mixed-case"],
)
def test_manifest_names_recognise_requirements_variants(path: str) -> None:
    from mergecraft.review_policy.manifest_names import is_dependency_manifest_path

    assert is_dependency_manifest_path(path)


def test_manifest_names_leave_prose_alone() -> None:
    from mergecraft.review_policy.manifest_names import is_dependency_manifest_path

    assert not is_dependency_manifest_path("docs/notes.txt")
    assert not is_dependency_manifest_path("README.md")
