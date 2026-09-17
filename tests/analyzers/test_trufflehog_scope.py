"""Plan 26 H3 / P7 — trufflehog excludes virtualenvs; fixtures suppressed by name.

Decision 9a: no blanket ``tests/**`` skip. A newly committed secret in a test still fires.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.analyzers.support import import_module

H3 = pytest.mark.xfail(
    reason="green after H3: trufflehog virtualenv exclude and named fixture suppressions",
    strict=False,
)

# Observed noise on run 34542726646 — each exemption names why, not a path glob.
_NAMED_FIXTURES: tuple[tuple[str, str], ...] = (
    (
        "tests/analyzers/fixtures/repo/config/planted-secret.env",
        "planted-secret",
    ),
    (
        "tests/tracing/test_redact_url.py",
        "redact",
    ),
    (
        "tests/security/test_credentials.py",
        "credential",
    ),
    (
        "tests/scripts/test_native_output_to_sarif.py",
        "sarif",
    ),
)


def _config() -> object:
    return import_module("mergecraft.analyzers.config")


def _ci_sarif() -> object:
    return import_module("scripts.ci_extended_sarif")


@H3
def test_trufflehog_exclude_paths_cover_venv_dev_and_virtualenv_trees(
    tmp_path: Path,
) -> None:
    module = _ci_sarif()
    path = module.write_trufflehog_exclude_paths(tmp_path)
    text = path.read_text(encoding="utf-8")
    assert ".venv-dev" in text
    assert r"\.venv/" in text or ".venv/" in text
    assert "site-packages" in text or "virtualenv" in text.casefold()


def test_trufflehog_exclude_paths_do_not_blanket_skip_tests(tmp_path: Path) -> None:
    module = _ci_sarif()
    path = module.write_trufflehog_exclude_paths(tmp_path)
    text = path.read_text(encoding="utf-8")
    for forbidden in ("^tests/", "tests/**", r"tests/\*\*"):
        assert forbidden not in text.splitlines()
    assert not any(line.strip() in {"tests/", "tests/**"} for line in text.splitlines())


@H3
def test_trufflehog_named_fixture_suppressions_cover_each_intentional_fixture() -> None:
    config = _config()
    suppressions = dict(config.trufflehog_named_fixture_suppressions())
    for path, needle in _NAMED_FIXTURES:
        assert path in suppressions, f"missing named suppression for {path}"
        reason = suppressions[path]
        assert reason.strip(), f"suppression for {path} must name why it is exempt"
        assert needle.casefold() in reason.casefold()


@H3
def test_named_fixture_is_suppressed_and_a_new_test_secret_is_not() -> None:
    config = _config()
    planted = "tests/analyzers/fixtures/repo/config/planted-secret.env"
    assert config.is_trufflehog_path_suppressed(planted) is True
    assert config.is_trufflehog_path_suppressed("tests/new_committed_secret.env") is False
    assert config.is_trufflehog_path_suppressed("tests/security/test_unrelated.py") is False


@H3
def test_virtualenv_tree_is_out_of_trufflehog_scope() -> None:
    config = _config()
    assert (
        config.is_trufflehog_path_suppressed(
            ".venv-dev/lib/python3.14/site-packages/httpx/_urls.py"
        )
        is True
    )
    assert config.is_trufflehog_path_suppressed("src/mergecraft/cli/app.py") is False
