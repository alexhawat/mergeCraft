"""DG1 generated/vendored file classification (G5, D4).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG1).
Implementation: **DG1.2** — classify, do not delete from scope; policy decides
inclusion.
"""

from __future__ import annotations


def test_generated_minified_vendored_are_classified() -> None:
    """Generated, minified, and vendored paths are labelled explicitly (D4)."""
    from mergecraft.classify.generated_files import FileKind, classify_path

    assert classify_path("src/generated/schema.py") == FileKind.GENERATED
    assert classify_path("dist/app.min.js") == FileKind.MINIFIED
    assert classify_path("vendor/acme/widget.py") == FileKind.VENDORED
    assert classify_path("third_party/lib/foo.c") == FileKind.VENDORED
    assert classify_path("src/mergecraft/app.py") == FileKind.SOURCE


def test_generator_config_change_is_still_reviewed() -> None:
    """When generator config changes, generated output stays in review scope."""
    from mergecraft.classify.generated_files import (
        finding_survives_generated_policy,
        review_includes_path,
    )

    change = {
        "changed_paths": ["Makefile", "src/generated/schema.py"],
        "diff_stats": {"files_changed": 2},
    }

    assert review_includes_path("src/generated/schema.py", change=change) is True
    assert finding_survives_generated_policy("src/generated/schema.py", change=change) is True


def test_generated_output_without_generator_config_change_is_dropped() -> None:
    """Generated-file findings drop when only the output changed (D4)."""
    from mergecraft.classify.generated_files import finding_survives_generated_policy

    change = {
        "changed_paths": ["src/generated/schema.py"],
        "diff_stats": {"files_changed": 1},
    }

    assert finding_survives_generated_policy("src/generated/schema.py", change=change) is False


def test_minified_and_vendored_findings_are_dropped_after_diff_scope() -> None:
    """Minified and vendored findings do not survive post-diff filtering (D4)."""
    from mergecraft.classify.generated_files import finding_survives_generated_policy

    change = {
        "changed_paths": ["dist/app.min.js", "vendor/acme/widget.py"],
        "diff_stats": {"files_changed": 2},
    }

    assert finding_survives_generated_policy("dist/app.min.js", change=change) is False
    assert finding_survives_generated_policy("vendor/acme/widget.py", change=change) is False
